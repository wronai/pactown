# Pactown vs Cloudflare Workers

Porównanie Pactown Quadlet z Cloudflare Workers jako platformy edge/serverless.

## Podsumowanie

| Aspekt | Pactown Quadlet | Cloudflare Workers |
|--------|-----------------|-------------------|
| **Model** | Self-hosted VPS | Edge serverless |
| **Koszt** | €5-20/mc (VPS) | $5/mc + $0.50/M req |
| **Latency** | 20-50ms (single region) | 5-15ms (edge) |
| **Cold start** | 0ms (always hot) | 0-50ms |
| **CPU limit** | Unlimited | 50ms/10ms |
| **Memory** | Configurable (GB) | 128MB |
| **Execution** | Unlimited | 30s/15min |
| **WebSocket** | Full support | Limited |
| **State** | Redis/SQLite/Postgres | KV/D1/Durable Objects |
| **Self-hosted** | ✓ | ✗ |
| **GDPR** | Full control | CF datacenters |

## Kiedy wybrać Pactown?

### ✅ Idealne dla:

1. **MVP / Startupy** - Niski koszt, pełna kontrola
2. **GDPR / Compliance** - Dane w EU, własny serwer
3. **Long-running tasks** - Bez limitu czasu wykonania
4. **LLM integration** - Wywołania API bez timeoutów
5. **WebSocket apps** - Pełne wsparcie bidirectional
6. **High memory** - Aplikacje wymagające > 128MB
7. **Development** - Łatwiejsze debugowanie, logi

### ❌ Nie najlepsze dla:

1. **Global edge latency** - CF ma 300+ PoPs
2. **Massive scale** - Auto-scaling CF jest prostszy
3. **Zero-ops** - Wymaga zarządzania VPS

## Kiedy wybrać Cloudflare Workers?

### ✅ Idealne dla:

1. **Global latency** - Edge locations worldwide
2. **High traffic** - Auto-scaling bez konfiguracji
3. **Static + dynamic** - Integracja z Pages
4. **Simple functions** - Krótkie requesty
5. **DDoS protection** - Built-in

### ❌ Nie najlepsze dla:

1. **Long tasks** - 50ms CPU limit
2. **Large payloads** - 1MB request limit
3. **Complex state** - Durable Objects kosztowne
4. **Self-hosting** - Brak opcji

## Architektura porównanie

### Pactown Quadlet (Self-hosted)

```
┌─────────────────────────────────────────────────┐
│                  Hetzner VPS                     │
│  ┌─────────────────────────────────────────┐    │
│  │              Traefik Proxy               │    │
│  │  - Let's Encrypt TLS                    │    │
│  │  - Rate limiting                        │    │
│  │  - Load balancing                       │    │
│  └────────────────┬────────────────────────┘    │
│                   │                              │
│  ┌────────────────┼────────────────────────┐    │
│  │           Quadlet Containers             │    │
│  │  ┌──────┐  ┌──────┐  ┌──────┐           │    │
│  │  │email │  │ api  │  │notify│           │    │
│  │  │worker│  │gateway│ │websock│          │    │
│  │  └──────┘  └──────┘  └──────┘           │    │
│  └──────────────────────────────────────────┘   │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │  Redis │ PostgreSQL │ SQLite             │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

### Cloudflare Workers (Edge)

```
┌─────────────────────────────────────────────────┐
│              Cloudflare Edge Network             │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │  300+ Global PoPs (Points of Presence)   │   │
│  │                                          │   │
│  │  ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐     │   │
│  │  │ WAW │  │ FRA │  │ NYC │  │ SIN │ ... │   │
│  │  └──┬──┘  └──┬──┘  └──┬──┘  └──┬──┘     │   │
│  │     └────────┴────────┴────────┘         │   │
│  │              V8 Isolates                 │   │
│  └──────────────────────────────────────────┘   │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │  KV Store │ D1 (SQLite) │ R2 (S3)        │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

## Migracja z Cloudflare Workers do Pactown

### Worker → Pactown Container

**Cloudflare Worker:**
```javascript
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    
    if (url.pathname === '/api/hello') {
      return new Response(JSON.stringify({ hello: 'world' }), {
        headers: { 'Content-Type': 'application/json' }
      });
    }
    
    return new Response('Not found', { status: 404 });
  }
}
```

**Pactown (FastAPI):**
```python
from fastapi import FastAPI
app = FastAPI()

@app.get("/api/hello")
async def hello():
    return {"hello": "world"}
```

**Quadlet deployment:**
```bash
# Example using a README.md-based service (recommended pattern)
pactown quadlet deploy ./examples/api-gateway-webhooks/README.md \
    --domain example.com \
    --subdomain api \
    --tenant gateway \
    --tls
```

### KV Store → Redis

**Cloudflare KV:**
```javascript
await env.MY_KV.put('key', 'value');
const value = await env.MY_KV.get('key');
```

**Pactown (Redis):**
```python
import redis
r = redis.Redis.from_url(os.getenv("REDIS_URL"))
r.set('key', 'value')
value = r.get('key')
```

### Durable Objects → SQLite/PostgreSQL

**Cloudflare Durable Objects:**
```javascript
export class Counter {
  constructor(state) {
    this.state = state;
  }
  
  async fetch(request) {
    let count = await this.state.storage.get('count') || 0;
    count++;
    await this.state.storage.put('count', count);
    return new Response(count.toString());
  }
}
```

**Pactown (SQLite):**
```python
import sqlite3

conn = sqlite3.connect('/data/state.db')

@app.post("/counter/{id}")
async def increment(id: str):
    cursor = conn.execute(
        "INSERT INTO counters (id, count) VALUES (?, 1) "
        "ON CONFLICT(id) DO UPDATE SET count = count + 1 "
        "RETURNING count",
        (id,)
    )
    count = cursor.fetchone()[0]
    conn.commit()
    return {"count": count}
```

## Praktyczne przypadki użycia

### 1. Email Automation (Pactown lepszy)

- **Problem:** Przetwarzanie emaili z LLM zajmuje > 50ms
- **Cloudflare:** Limity CPU, timeouty
- **Pactown:** Bez limitów, pełna integracja LLM

```bash
# Pactown deployment
pactown quadlet deploy ./examples/email-llm-responder/README.md \
    --domain mail.example.com \
    --subdomain email
```

### 2. API Gateway z cache (Podobne)

- **Cloudflare:** Świetny edge cache
- **Pactown:** Redis cache, pełna kontrola

### 3. Real-time WebSocket (Pactown lepszy)

- **Problem:** WebSocket wymaga persistent connections
- **Cloudflare:** Durable Objects kosztowne dla wielu połączeń
- **Pactown:** Natywne wsparcie, 10k+ connections/node

```bash
# Pactown deployment
pactown quadlet deploy ./examples/realtime-notifications/README.md \
    --domain notify.example.com \
    --subdomain ws
```

### 4. Static site + API (Cloudflare lepszy)

- **Cloudflare:** Pages + Workers integration
- **Pactown:** Wymaga osobnego hostingu static

### 5. Global latency-critical (Cloudflare lepszy)

- **Problem:** Użytkownicy na całym świecie
- **Cloudflare:** 300+ edge locations
- **Pactown:** Single region, ale można multi-VPS

## Koszty porównanie

### Scenario: 1M requests/miesiąc

| | Pactown | Cloudflare |
|--|---------|-----------|
| Base | €5 (Hetzner CX22) | $5 (Workers Paid) |
| Requests | $0 | $0.50 (1M incl.) |
| KV/Redis | €0 (self-hosted) | $0.50/M reads |
| **Total** | **€5** | **~$6** |

### Scenario: 100M requests/miesiąc

| | Pactown | Cloudflare |
|--|---------|-----------|
| Base | €20 (Hetzner CX42) | $5 |
| Requests | $0 | $49.50 (99M × $0.50) |
| KV/Redis | €5 (managed Redis) | $50+ |
| **Total** | **€25** | **~$105** |

### Scenario: Enterprise z Durable Objects

| | Pactown | Cloudflare |
|--|---------|-----------|
| Base | €50 (dedicated) | $5 |
| Requests | $0 | $50 |
| DO/Database | €20 (PostgreSQL) | $500+ (DO) |
| **Total** | **€70** | **~$555** |

## Hybrid Architecture

Można łączyć oba podejścia:

```
┌─────────────────────────────────────────────────────────────┐
│                    Cloudflare Edge                           │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  - DDoS protection                                   │    │
│  │  - Global CDN                                        │    │
│  │  - Simple routing Worker                             │    │
│  └────────────────────────┬────────────────────────────┘    │
└───────────────────────────┼─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Pactown VPS (Origin)                      │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  - Long-running tasks                                │    │
│  │  - WebSocket connections                             │    │
│  │  - LLM integrations                                  │    │
│  │  - Complex state management                          │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

**Cloudflare Worker (proxy):**
```javascript
export default {
  async fetch(request, env) {
    // Quick edge logic
    if (isBot(request)) {
      return new Response('Blocked', { status: 403 });
    }
    
    // Proxy to Pactown origin for heavy lifting
    return fetch('https://api.pactown-origin.com' + new URL(request.url).pathname, {
      method: request.method,
      headers: request.headers,
      body: request.body
    });
  }
}
```

## Podsumowanie

**Wybierz Pactown gdy:**
- Potrzebujesz pełnej kontroli i GDPR compliance
- Masz long-running tasks lub LLM integrations
- Potrzebujesz WebSocket/real-time
- Budujesz MVP z ograniczonym budżetem
- Chcesz uniknąć vendor lock-in

**Wybierz Cloudflare Workers gdy:**
- Potrzebujesz global edge latency
- Masz proste, krótkie funkcje
- Chcesz zero-ops serverless
- Integrujesz z Cloudflare ecosystem (Pages, R2, D1)

**Hybrid gdy:**
- Potrzebujesz edge + complex backend
- DDoS protection + heavy processing
- Global CDN + stateful applications
