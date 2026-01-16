#!/usr/bin/env python3
"""
Fast Start Demo - Demonstrates dependency caching for fast startup.

Usage:
    python demo.py
"""
import asyncio
import time
from pathlib import Path

# Add pactown to path if running from source
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from pactown import ServiceRunner


API_README = '''# Demo API

Simple FastAPI service for demonstrating fast start.

```python markpact:deps
fastapi
uvicorn
```

```python markpact:file path=main.py
from fastapi import FastAPI

app = FastAPI(title="Fast Start Demo")

@app.get("/")
def root():
    return {"message": "Hello from Fast Start Demo!"}

@app.get("/health")
def health():
    return {"status": "ok"}
```

```bash markpact:run
uvicorn main:app --host 0.0.0.0 --port $PORT
```
'''


async def main():
    print("=" * 50)
    print("⚡ Fast Start Demo")
    print("=" * 50)
    print()
    
    runner = ServiceRunner(
        sandbox_root="/tmp/fast-start-demo",
        enable_fast_start=True,
    )
    
    # Run 1 - First run (cold start)
    print("Run 1 (fresh install):")
    print("  Creating sandbox and installing dependencies...")
    
    start = time.time()
    result1 = await runner.fast_run(
        service_id="demo-api-1",
        content=API_README,
        port=10091,
    )
    time1 = time.time() - start
    
    if result1.success:
        print(f"  ✓ Started in {time1:.2f}s")
    else:
        print(f"  ❌ Failed: {result1.message}")
        return
    
    # Stop first service
    runner.stop("demo-api-1")
    
    print()
    
    # Run 2 - Second run (cache hit)
    print("Run 2 (cached):")
    print("  ⚡ Checking cache...")
    
    start = time.time()
    result2 = await runner.fast_run(
        service_id="demo-api-2",
        content=API_README,  # Same deps!
        port=10092,
    )
    time2 = time.time() - start
    
    if result2.success:
        print(f"  ✓ Started in {time2:.2f}s")
    else:
        print(f"  ❌ Failed: {result2.message}")
    
    # Stop second service
    runner.stop("demo-api-2")
    
    print()
    print("=" * 50)
    print(f"Results:")
    print(f"  First run:  {time1:.2f}s")
    print(f"  Second run: {time2:.2f}s")
    if time2 > 0:
        print(f"  Speedup:    {time1/time2:.1f}x faster!")
    print("=" * 50)
    
    # Show cache stats
    stats = runner.get_cache_stats()
    print()
    print("Cache Statistics:")
    print(f"  Entries: {stats.get('cache_entries', 0)}")
    print(f"  Caching enabled: {stats.get('caching_enabled', False)}")


if __name__ == "__main__":
    asyncio.run(main())
