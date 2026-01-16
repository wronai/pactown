"""Pactown – Decentralized Service Ecosystem Orchestrator using markpact"""

__version__ = "0.1.17"

from .config import DependencyConfig, EcosystemConfig, ServiceConfig
from .network import PortAllocator, ServiceEndpoint, ServiceRegistry, find_free_port
from .orchestrator import Orchestrator
from .resolver import DependencyResolver
from .sandbox_manager import SandboxManager
from .service_runner import (
    ServiceRunner,
    RunResult,
    EndpointTestResult,
    ValidationResult,
    ErrorCategory,
    DiagnosticInfo,
    AutoFixSuggestion,
)
from .security import (
    SecurityPolicy,
    UserProfile,
    UserTier,
    AnomalyType,
    AnomalyEvent,
    AnomalyLogger,
    RateLimiter,
    ResourceMonitor,
    SecurityCheckResult,
    get_security_policy,
    set_security_policy,
)
from .fast_start import (
    FastServiceStarter,
    DependencyCache,
    SandboxPool,
    ParallelServiceRunner,
    FastStartResult,
    get_fast_starter,
)
from .user_isolation import (
    UserIsolationManager,
    IsolatedUser,
    get_isolation_manager,
)

__all__ = [
    # High-level API
    "ServiceRunner",
    "RunResult",
    "EndpointTestResult",
    "ValidationResult",
    "ErrorCategory",
    "DiagnosticInfo",
    "AutoFixSuggestion",
    # Security
    "SecurityPolicy",
    "UserProfile",
    "UserTier",
    "AnomalyType",
    "AnomalyEvent",
    "AnomalyLogger",
    "RateLimiter",
    "ResourceMonitor",
    "SecurityCheckResult",
    "get_security_policy",
    "set_security_policy",
    # Fast Start
    "FastServiceStarter",
    "DependencyCache",
    "SandboxPool",
    "ParallelServiceRunner",
    "FastStartResult",
    "get_fast_starter",
    # User Isolation
    "UserIsolationManager",
    "IsolatedUser",
    "get_isolation_manager",
    # Orchestration
    "EcosystemConfig",
    "ServiceConfig",
    "DependencyConfig",
    "Orchestrator",
    "DependencyResolver",
    "SandboxManager",
    # Network
    "ServiceRegistry",
    "PortAllocator",
    "ServiceEndpoint",
    "find_free_port",
    "__version__",
]
