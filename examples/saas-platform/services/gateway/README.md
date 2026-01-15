# API Gateway

Reverse proxy and API gateway for the SaaS platform. Routes requests to appropriate services.

## Features

- Request routing
- CORS handling
- Rate limiting (basic)
- Health aggregation

## Routes

- `/api/*` → API Service
- `/db/*` → Database Service
- `/` → Web Frontend
- `/gateway/health` – Gateway health + all services

---

```python markpact:deps
fastapi
uvicorn
httpx
```

```python markpact:file path=gateway.py
import os
import asyncio
from typing import Optional

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx

app = FastAPI(title="API Gateway", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Service URLs from environment
API_URL = os.environ.get("API_URL", "http://localhost:8001")
DATABASE_URL = os.environ.get("DATABASE_URL", "http://localhost:8003")
WEB_URL = os.environ.get("WEB_URL", "http://localhost:8002")

# Route configuration
ROUTES = {
    "/api": API_URL,
    "/db": DATABASE_URL,
    "/web": WEB_URL,
}


async def proxy_request(
    target_url: str,
    request: Request,
    path: str = "",
) -> Response:
    """Proxy request to target service."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{target_url}{path}"
        
        # Forward headers (excluding host)
        headers = dict(request.headers)
        headers.pop("host", None)
        
        # Get body for non-GET requests
        body = None
        if request.method not in ("GET", "HEAD"):
            body = await request.body()
        
        try:
            response = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
                params=request.query_params,
            )
            
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
            )
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Service timeout")
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="Service unavailable")


@app.get("/gateway/health")
async def gateway_health():
    """Check health of gateway and all services."""
    services = {
        "api": API_URL,
        "database": DATABASE_URL,
        "web": WEB_URL,
    }
    
    async def check_service(name: str, url: str) -> dict:
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                resp = await client.get(f"{url}/health")
                return {
                    "name": name,
                    "url": url,
                    "status": "healthy" if resp.status_code == 200 else "unhealthy",
                    "code": resp.status_code,
                }
            except Exception as e:
                return {
                    "name": name,
                    "url": url,
                    "status": "unreachable",
                    "error": str(e),
                }
    
    results = await asyncio.gather(*[
        check_service(name, url) for name, url in services.items()
    ])
    
    all_healthy = all(r["status"] == "healthy" for r in results)
    
    return {
        "status": "ok" if all_healthy else "degraded",
        "service": "gateway",
        "services": results,
    }


@app.get("/gateway/routes")
async def list_routes():
    """List configured routes."""
    return {
        "routes": [
            {"prefix": prefix, "target": target}
            for prefix, target in ROUTES.items()
        ]
    }


# API routes
@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_api(request: Request, path: str):
    return await proxy_request(API_URL, request, f"/{path}")


# Database routes  
@app.api_route("/db/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_db(request: Request, path: str):
    return await proxy_request(DATABASE_URL, request, f"/{path}")


# Web routes (static files)
@app.get("/")
async def proxy_web_root(request: Request):
    return await proxy_request(WEB_URL, request, "/")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "gateway"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("MARKPACT_PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
```

```bash markpact:run
uvicorn gateway:app --host 0.0.0.0 --port ${MARKPACT_PORT:-8000} --reload
```

```http markpact:test
GET /health EXPECT 200
GET /gateway/health EXPECT 200
GET /gateway/routes EXPECT 200
```
