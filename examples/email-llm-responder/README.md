# Email LLM Auto-Responder

Automatyczna obsługa emaili z integracją LLM (OpenAI/Anthropic/Ollama) - alternatywa dla Cloudflare Workers Email Routing.

## Architektura

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Mailgun/SES   │────▶│  Pactown Worker  │────▶│   LLM API       │
│   Webhook       │     │  (email.*)       │     │   (Claude/GPT)  │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌──────────────────┐
                        │   SMTP Send      │
                        │   (response)     │
                        └──────────────────┘
```

## Funkcje

- **Webhook receiver** - Odbiera emaile z Mailgun/SES/SendGrid
- **LLM Processing** - Generuje odpowiedzi via Claude/GPT/Ollama
- **Auto-reply** - Wysyła odpowiedzi SMTP
- **Rate limiting** - Ochrona przed flood
- **Audit log** - Historia wszystkich operacji

## Deploy

```bash
# Generate sandbox and deploy
pactown quadlet deploy ./README.md \
    --domain yourdomain.com \
    --subdomain email \
    --tenant email-automation \
    --tls
```

## Konfiguracja

### Zmienne środowiskowe

```yaml
# config.yaml
env:
  LLM_PROVIDER: anthropic          # anthropic, openai, ollama
  ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
  OPENAI_API_KEY: ${OPENAI_API_KEY}
  SMTP_HOST: smtp.mailgun.org
  SMTP_PORT: "587"
  SMTP_USER: postmaster@yourdomain.com
  SMTP_PASS: ${SMTP_PASS}
  MAILGUN_WEBHOOK_SECRET: ${MAILGUN_WEBHOOK_SECRET}
  RATE_LIMIT_PER_HOUR: "100"
  MAX_RESPONSE_LENGTH: "2000"
```

## API Endpoints

| Endpoint | Method | Opis |
|----------|--------|------|
| `/health` | GET | Health check |
| `/stats` | GET | Statystyki przetworzonych emaili |
| `/webhook/mailgun` | POST | Odbiera emaile z Mailgun |
| `/webhook/sendgrid` | POST | Odbiera emaile z SendGrid |
| `/test` | POST | Test endpoint dla manual processing |

## Porównanie z Cloudflare Workers

| Aspekt | Pactown | Cloudflare Workers |
|--------|---------|-------------------|
| Koszt | VPS ~€5/mc | $5/mc + usage |
| Latency | ~50ms (EU) | ~10ms (edge) |
| Limits | Brak | 50ms CPU, 128MB |
| LLM calls | Pełna kontrola | Ograniczone timeout |
| Self-hosted | ✓ | ✗ |
| GDPR | Pełna kontrola | CF servers |

## Kod źródłowy

```python main.py
"""Email LLM Auto-Responder - Pactown Worker.

Receives emails via webhook, processes with LLM, sends auto-replies.
Alternative to Cloudflare Workers Email Routing.
"""

import os
import hmac
import hashlib
import logging
from datetime import datetime
from typing import Optional
from collections import defaultdict
import time

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
import httpx

# Configuration
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.mailgun.org")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

MAILGUN_WEBHOOK_SECRET = os.getenv("MAILGUN_WEBHOOK_SECRET", "")
SENDGRID_WEBHOOK_SECRET = os.getenv("SENDGRID_WEBHOOK_SECRET", "")

RATE_LIMIT_PER_HOUR = int(os.getenv("RATE_LIMIT_PER_HOUR", "100"))
MAX_RESPONSE_LENGTH = int(os.getenv("MAX_RESPONSE_LENGTH", "2000"))

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Rate limiting storage
rate_limits: dict[str, list[float]] = defaultdict(list)

# Stats
stats = {
    "emails_received": 0,
    "emails_processed": 0,
    "emails_replied": 0,
    "errors": 0,
    "started_at": datetime.utcnow().isoformat(),
}

app = FastAPI(
    title="Email LLM Auto-Responder",
    description="Pactown Worker for email automation with LLM",
    version="1.0.0",
)


class EmailPayload(BaseModel):
    """Parsed email data."""
    sender: EmailStr
    recipient: str
    subject: str
    body_plain: str
    body_html: Optional[str] = None
    timestamp: Optional[str] = None
    message_id: Optional[str] = None


class LLMResponse(BaseModel):
    """LLM generated response."""
    reply_text: str
    category: str
    confidence: float
    should_reply: bool


def check_rate_limit(sender: str) -> bool:
    """Check if sender is within rate limits."""
    now = time.time()
    hour_ago = now - 3600
    rate_limits[sender] = [t for t in rate_limits[sender] if t > hour_ago]
    if len(rate_limits[sender]) >= RATE_LIMIT_PER_HOUR:
        return False
    rate_limits[sender].append(now)
    return True


def verify_mailgun_signature(token: str, timestamp: str, signature: str) -> bool:
    """Verify Mailgun webhook signature."""
    if not MAILGUN_WEBHOOK_SECRET:
        logger.warning("MAILGUN_WEBHOOK_SECRET not set, skipping verification")
        return True
    hmac_digest = hmac.new(
        key=MAILGUN_WEBHOOK_SECRET.encode(),
        msg=f"{timestamp}{token}".encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, hmac_digest)


async def call_llm(email: EmailPayload) -> LLMResponse:
    """Call LLM to generate response."""
    system_prompt = """You are an AI email assistant. Analyze incoming emails and generate appropriate responses.

Rules:
1. Be professional and helpful
2. If email is spam/marketing, set should_reply=false
3. Categorize emails: support, sales, partnership, spam, personal, other
4. Keep responses concise (max 500 words)
5. If you can't help, politely redirect to human support

Output JSON with: reply_text, category, confidence (0-1), should_reply (bool)"""

    user_prompt = f"""Analyze this email and generate a response:

From: {email.sender}
Subject: {email.subject}
Body:
{email.body_plain[:2000]}

Generate JSON response."""

    try:
        if LLM_PROVIDER == "anthropic":
            return await call_anthropic(system_prompt, user_prompt)
        elif LLM_PROVIDER == "openai":
            return await call_openai(system_prompt, user_prompt)
        elif LLM_PROVIDER == "ollama":
            return await call_ollama(system_prompt, user_prompt)
        else:
            raise ValueError(f"Unknown LLM provider: {LLM_PROVIDER}")
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return LLMResponse(reply_text="", category="error", confidence=0.0, should_reply=False)


async def call_anthropic(system: str, user: str) -> LLMResponse:
    """Call Anthropic Claude API."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-3-haiku-20240307",
                "max_tokens": 1024,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        import json
        text = data["content"][0]["text"]
        try:
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            result = json.loads(text)
            return LLMResponse(**result)
        except:
            return LLMResponse(reply_text=text[:MAX_RESPONSE_LENGTH], category="other", confidence=0.5, should_reply=True)


async def call_openai(system: str, user: str) -> LLMResponse:
    """Call OpenAI GPT API."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "max_tokens": 1024,
                "response_format": {"type": "json_object"},
            },
            timeout=30.0,
        )
        response.raise_for_status()
        import json
        result = json.loads(response.json()["choices"][0]["message"]["content"])
        return LLMResponse(**result)


async def call_ollama(system: str, user: str) -> LLMResponse:
    """Call local Ollama API."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": "llama3.2", "prompt": f"{system}\n\n{user}", "stream": False, "format": "json"},
            timeout=60.0,
        )
        response.raise_for_status()
        import json
        result = json.loads(response.json()["response"])
        return LLMResponse(**result)


async def send_email(to: str, subject: str, body: str, in_reply_to: Optional[str] = None):
    """Send email via SMTP."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    
    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = to
    msg["Subject"] = f"Re: {subject}" if not subject.startswith("Re:") else subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.attach(MIMEText(body, "plain"))
    
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        logger.info(f"Email sent to {to}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


async def process_email(email: EmailPayload):
    """Process email with LLM and send reply."""
    stats["emails_received"] += 1
    if not check_rate_limit(email.sender):
        logger.warning(f"Rate limit exceeded for {email.sender}")
        return
    llm_response = await call_llm(email)
    stats["emails_processed"] += 1
    logger.info(f"Email categorized as: {llm_response.category} (confidence: {llm_response.confidence:.2f})")
    if llm_response.should_reply and llm_response.reply_text:
        success = await send_email(to=email.sender, subject=email.subject, body=llm_response.reply_text, in_reply_to=email.message_id)
        if success:
            stats["emails_replied"] += 1


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "provider": LLM_PROVIDER}


@app.get("/stats")
async def get_stats():
    """Get processing statistics."""
    return stats


@app.post("/webhook/mailgun")
async def mailgun_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive emails from Mailgun webhook."""
    form = await request.form()
    token, timestamp, signature = form.get("token", ""), form.get("timestamp", ""), form.get("signature", "")
    if not verify_mailgun_signature(token, timestamp, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
    email = EmailPayload(
        sender=form.get("sender", ""), recipient=form.get("recipient", ""), subject=form.get("subject", ""),
        body_plain=form.get("body-plain", ""), body_html=form.get("body-html"), timestamp=timestamp, message_id=form.get("Message-Id"),
    )
    background_tasks.add_task(process_email, email)
    return {"status": "accepted"}


@app.post("/webhook/sendgrid")
async def sendgrid_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive emails from SendGrid Inbound Parse."""
    form = await request.form()
    email = EmailPayload(
        sender=form.get("from", ""), recipient=form.get("to", ""), subject=form.get("subject", ""),
        body_plain=form.get("text", ""), body_html=form.get("html"),
    )
    background_tasks.add_task(process_email, email)
    return {"status": "accepted"}


@app.post("/test")
async def test_email(email: EmailPayload):
    """Test endpoint for manual email processing."""
    llm_response = await call_llm(email)
    return {"email": email.dict(), "response": llm_response.dict()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
```

## Requirements

```txt requirements.txt
fastapi>=0.100.0
uvicorn>=0.20.0
httpx>=0.24.0
pydantic>=2.0
```

## Wygenerowane pliki (./sandbox)

Po uruchomieniu `pactown quadlet deploy` zostaną wygenerowane:

- `./sandbox/main.py` - Kod z tego README
- `./sandbox/requirements.txt` - Zależności
- `./sandbox/Dockerfile` - Obraz kontenera
- `./sandbox/email-responder.container` - Quadlet unit file
- `./sandbox/.env.example` - Przykład zmiennych środowiskowych
