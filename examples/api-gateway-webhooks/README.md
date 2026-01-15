# API Gateway & Webhook Handler

Uniwersalny gateway API z obsługą webhooków Allegro, InPost, Stripe, GitHub - alternatywa dla Cloudflare Workers.

## Architektura

```
┌─────────────┐     ┌──────────────────────────────────────┐
│   Client    │────▶│         Pactown API Gateway          │
└─────────────┘     │  ┌─────────┐ ┌─────────┐ ┌────────┐  │
                    │  │ Auth    │ │ Rate    │ │ Cache  │  │
                    │  │ Layer   │ │ Limiter │ │ Layer  │  │
                    │  └────┬────┘ └────┬────┘ └───┬────┘  │
                    │       └───────────┼─────────┘        │
                    │                   ▼                  │
                    │  ┌────────────────────────────────┐  │
                    │  │        Route Matcher           │  │
                    │  └────────────────────────────────┘  │
                    └──────────────┬───────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼
┌──────────────┐          ┌──────────────┐          ┌──────────────┐
│   Allegro    │          │    InPost    │          │   Stripe     │
│   API        │          │   Webhook    │          │   Webhook    │
└──────────────┘          └──────────────┘          └──────────────┘
```

## Funkcje

- **Webhook routing** - Allegro, InPost, Stripe, GitHub
- **Request transformation** - Header injection, body mapping
- **Rate limiting** - Per-tenant, per-endpoint
- **Caching** - In-memory response cache
- **Auth middleware** - API keys, JWT, HMAC signatures
- **Retry logic** - Automatic retries with exponential backoff

## Deploy

```bash
pactown quadlet deploy ./README.md \
    --domain yourdomain.com \
    --subdomain api \
    --tenant gateway \
    --tls
```

## API Endpoints

| Endpoint | Method | Opis |
|----------|--------|------|
| `/health` | GET | Health check |
| `/stats` | GET | Statystyki gateway |
| `/routes` | GET | Lista skonfigurowanych tras |
| `/webhooks/{provider}` | POST | Obsługa webhooków |
| `/api/{path}` | ALL | Proxy do backendu |

## Porównanie z Cloudflare Workers

| Aspekt | Pactown Gateway | CF Workers |
|--------|-----------------|------------|
| Cold start | 0ms (always hot) | ~50ms |
| Execution | Unlimited | 50ms CPU |
| Memory | Configurable | 128MB |
| Subrequests | Unlimited | 50/request |
| WebSockets | Full support | Limited |
| Self-hosted | ✓ | ✗ |
| Cost | €5/mc VPS | $5+ usage |

## Konfiguracja routingu

```yaml routes.yaml
routes:
  - path: /webhooks/allegro
    target: http://allegro-handler:8080
    auth: webhook_secret
    rate_limit: 100/min
    
  - path: /webhooks/inpost
    target: http://inpost-handler:8080
    auth: hmac_sha256
    
  - path: /webhooks/stripe
    target: http://stripe-handler:8080
    auth: stripe_signature
    
  - path: /api/v1/*
    target: http://backend:8080
    auth: jwt
    cache: 60s
    rate_limit: 1000/min
```

## Kod źródłowy

```python main.py
"""API Gateway & Webhook Handler - Pactown Worker.

Universal API gateway with webhook routing, rate limiting, and caching.
Alternative to Cloudflare Workers for API management.
"""

import os
import time
import hmac
import hashlib
import asyncio
import logging
from datetime import datetime
from typing import Optional, Any
from collections import defaultdict

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
import httpx
import yaml

# Configuration
ROUTES_CONFIG = os.getenv("ROUTES_CONFIG", "routes.yaml")
DEFAULT_TIMEOUT = int(os.getenv("DEFAULT_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# Secrets
ALLEGRO_WEBHOOK_SECRET = os.getenv("ALLEGRO_WEBHOOK_SECRET", "")
INPOST_WEBHOOK_SECRET = os.getenv("INPOST_WEBHOOK_SECRET", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
JWT_SECRET = os.getenv("JWT_SECRET", "")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory cache and rate limits
cache: dict[str, tuple[Any, float]] = {}
rate_limits: dict[str, list[float]] = defaultdict(list)

stats = {
    "requests_total": 0,
    "requests_cached": 0,
    "requests_rate_limited": 0,
    "webhooks_received": 0,
    "errors": 0,
    "started_at": datetime.utcnow().isoformat(),
}

app = FastAPI(title="Pactown API Gateway", version="1.0.0")


class RouteConfig(BaseModel):
    path: str
    target: str
    auth: Optional[str] = None
    rate_limit: Optional[str] = None
    cache: Optional[str] = None
    timeout: int = 30
    retries: int = 3


def load_routes() -> list[RouteConfig]:
    """Load routes from config file."""
    try:
        if os.path.exists(ROUTES_CONFIG):
            with open(ROUTES_CONFIG) as f:
                config = yaml.safe_load(f)
                return [RouteConfig(**r) for r in config.get("routes", [])]
    except Exception as e:
        logger.error(f"Failed to load routes: {e}")
    return [
        RouteConfig(path="/webhooks/allegro", target="http://localhost:8081", auth="webhook_secret"),
        RouteConfig(path="/webhooks/inpost", target="http://localhost:8082", auth="hmac_sha256"),
        RouteConfig(path="/webhooks/stripe", target="http://localhost:8083", auth="stripe_signature"),
        RouteConfig(path="/api/v1", target="http://localhost:8080", auth="jwt", cache="60s"),
    ]


ROUTES = load_routes()


def check_rate_limit(key: str, limit_str: str) -> bool:
    """Check rate limit (e.g., '100/min')."""
    try:
        count, period = limit_str.split("/")
        count = int(count)
        window = {"min": 60, "hour": 3600, "day": 86400}.get(period, 60)
        now = time.time()
        rate_limits[key] = [t for t in rate_limits[key] if t > now - window]
        if len(rate_limits[key]) >= count:
            return False
        rate_limits[key].append(now)
        return True
    except:
        return True


def get_cache(key: str, ttl_str: str) -> Optional[Any]:
    """Get cached response."""
    if key in cache:
        value, expires = cache[key]
        if time.time() < expires:
            return value
        del cache[key]
    return None


def set_cache(key: str, value: Any, ttl_str: str):
    """Set cached response."""
    try:
        ttl = int(ttl_str.rstrip("s"))
        cache[key] = (value, time.time() + ttl)
    except:
        pass


def verify_webhook_signature(provider: str, request_body: bytes, signature: str, timestamp: Optional[str] = None) -> bool:
    """Verify webhook signature for various providers."""
    if provider == "allegro":
        expected = hmac.new(ALLEGRO_WEBHOOK_SECRET.encode(), request_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
    elif provider == "inpost":
        expected = hmac.new(INPOST_WEBHOOK_SECRET.encode(), request_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, f"sha256={expected}")
    elif provider == "stripe":
        if not timestamp:
            return False
        payload = f"{timestamp}.{request_body.decode()}"
        expected = hmac.new(STRIPE_WEBHOOK_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, f"v1={expected}")
    return False


def verify_jwt(token: str) -> bool:
    """Verify JWT token."""
    if not JWT_SECRET:
        return True
    try:
        import jwt
        jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return True
    except:
        return False


def find_route(path: str) -> Optional[RouteConfig]:
    """Find matching route for path."""
    for route in ROUTES:
        if route.path.endswith("*"):
            if path.startswith(route.path[:-1]):
                return route
        elif path == route.path or path.startswith(route.path + "/"):
            return route
    return None


async def proxy_request(request: Request, route: RouteConfig) -> Response:
    """Proxy request to target with retries."""
    path_suffix = request.url.path[len(route.path):]
    target_url = f"{route.target}{path_suffix}"
    if request.url.query:
        target_url += f"?{request.url.query}"
    
    headers = dict(request.headers)
    headers.pop("host", None)
    body = await request.body()
    
    last_error = None
    for attempt in range(route.retries):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method=request.method, url=target_url, headers=headers,
                    content=body, timeout=route.timeout,
                )
                return Response(content=response.content, status_code=response.status_code, headers=dict(response.headers))
        except Exception as e:
            last_error = e
            if attempt < route.retries - 1:
                await asyncio.sleep(2 ** attempt)
    
    stats["errors"] += 1
    raise HTTPException(status_code=502, detail=f"Upstream error: {last_error}")


@app.get("/health")
async def health():
    return {"status": "healthy", "routes": len(ROUTES)}


@app.get("/stats")
async def get_stats():
    return {**stats, "cache_size": len(cache), "rate_limit_keys": len(rate_limits)}


@app.get("/routes")
async def list_routes():
    return {"routes": [r.dict() for r in ROUTES]}


@app.api_route("/webhooks/{provider}", methods=["POST"])
async def handle_webhook(provider: str, request: Request):
    """Handle incoming webhooks from various providers."""
    stats["webhooks_received"] += 1
    body = await request.body()
    
    signature, timestamp = "", None
    if provider == "allegro":
        signature = request.headers.get("X-Allegro-Signature", "")
    elif provider == "inpost":
        signature = request.headers.get("X-InPost-Signature", "")
    elif provider == "stripe":
        sig_header = request.headers.get("Stripe-Signature", "")
        for part in sig_header.split(","):
            if part.startswith("t="):
                timestamp = part[2:]
            elif part.startswith("v1="):
                signature = part
    elif provider == "github":
        signature = request.headers.get("X-Hub-Signature-256", "")
    
    if not verify_webhook_signature(provider, body, signature, timestamp):
        logger.warning(f"Invalid webhook signature from {provider}")
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    route = find_route(f"/webhooks/{provider}")
    if route:
        return await proxy_request(request, route)
    return {"status": "accepted", "provider": provider}


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def handle_api(path: str, request: Request):
    """Handle API requests with routing, caching, rate limiting."""
    stats["requests_total"] += 1
    full_path = f"/api/{path}"
    route = find_route(full_path)
    
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    
    if route.auth == "jwt":
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            if not verify_jwt(auth_header[7:]):
                raise HTTPException(status_code=401, detail="Invalid token")
        else:
            raise HTTPException(status_code=401, detail="Missing token")
    
    if route.rate_limit:
        client_ip = request.client.host if request.client else "unknown"
        if not check_rate_limit(f"{route.path}:{client_ip}", route.rate_limit):
            stats["requests_rate_limited"] += 1
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
    
    if route.cache and request.method == "GET":
        cache_key = f"{request.method}:{request.url}"
        cached = get_cache(cache_key, route.cache)
        if cached:
            stats["requests_cached"] += 1
            return Response(content=cached["content"], status_code=cached["status"], headers=cached["headers"])
    
    response = await proxy_request(request, route)
    
    if route.cache and request.method == "GET" and response.status_code == 200:
        set_cache(cache_key, {"content": response.body, "status": response.status_code, "headers": dict(response.headers)}, route.cache)
    
    return response


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
pyyaml>=6.0
pyjwt>=2.0
```

## Wygenerowane pliki (./sandbox)

Po uruchomieniu `pactown quadlet deploy` zostaną wygenerowane:

- `./sandbox/main.py` - Kod z tego README
- `./sandbox/routes.yaml` - Konfiguracja routingu
- `./sandbox/requirements.txt` - Zależności
- `./sandbox/Dockerfile` - Obraz kontenera
- `./sandbox/api-gateway.container` - Quadlet unit file
