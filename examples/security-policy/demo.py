#!/usr/bin/env python3
"""
Security Policy Demo - Demonstrates rate limiting and user profiles.

Usage:
    python demo.py
"""
import asyncio
from pathlib import Path

# Add pactown to path if running from source
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from pactown import SecurityPolicy, UserProfile, UserTier, AnomalyType


async def main():
    print("=" * 50)
    print("🛡️  Security Policy Demo")
    print("=" * 50)
    print()
    
    # Create security policy
    policy = SecurityPolicy(
        anomaly_log_path=Path("./demo_anomalies.jsonl"),
        default_rate_limit=20,  # 20 requests per minute for demo
        cpu_threshold=80.0,
        memory_threshold=85.0,
    )
    
    # Create user profiles
    print("Creating user profiles...")
    
    free_user = UserProfile.from_tier("free_user", UserTier.FREE)
    pro_user = UserProfile.from_tier("pro_user", UserTier.PRO)
    
    policy.set_user_profile(free_user)
    policy.set_user_profile(pro_user)
    
    print(f"  ✓ free_user (FREE): max {free_user.max_concurrent_services} services, {free_user.max_requests_per_minute} req/min")
    print(f"  ✓ pro_user (PRO): max {pro_user.max_concurrent_services} services, {pro_user.max_requests_per_minute} req/min")
    print()
    
    # Test rate limiting
    print("Testing rate limiting (free_user)...")
    
    for i in range(25):
        result = await policy.check_can_start_service(
            user_id="free_user",
            service_id=f"test-service-{i}",
            port=10000 + i,
        )
        
        if result.allowed:
            print(f"  Request {i+1}: ✓ allowed")
        else:
            print(f"  Request {i+1}: ✗ {result.reason}")
            if result.wait_seconds:
                print(f"             Wait {result.wait_seconds:.1f}s before retry")
            break
    
    print()
    
    # Test concurrent limits
    print("Testing concurrent service limits (free_user)...")
    
    # Simulate starting services
    for i in range(4):
        service_id = f"concurrent-test-{i}"
        
        # Check if allowed
        result = await policy.check_can_start_service(
            user_id="free_user",
            service_id=service_id,
            port=11000 + i,
        )
        
        if result.allowed:
            # Register the service as running
            policy.register_service("free_user", service_id)
            count = policy.get_user_service_count("free_user")
            print(f"  Service {i+1}: ✓ started (running: {count}/{free_user.max_concurrent_services})")
        else:
            print(f"  Service {i+1}: ✗ {result.reason}")
    
    print()
    
    # Show anomaly summary
    print("Anomaly summary:")
    summary = policy.get_anomaly_summary(hours=1)
    print(f"  Total events: {summary.get('total_count', 0)}")
    
    by_type = summary.get('by_type', {})
    for anomaly_type, count in by_type.items():
        print(f"  - {anomaly_type}: {count}")
    
    print()
    print("=" * 50)
    print("Demo complete! Check demo_anomalies.jsonl for logged events.")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
