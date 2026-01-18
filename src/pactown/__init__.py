"""Pactown – Decentralized Service Ecosystem Orchestrator using markpact"""

__version__ = "0.1.31"

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
from .events import (
    # Core event types
    Event,
    EventType,
    EventStore,
    get_event_store,
    set_event_store,
    # Aggregates
    Aggregate,
    ServiceAggregate,
    # Commands (Write side)
    ServiceCommands,
    ProjectCommands,
    SecurityCommands,
    get_service_commands,
    get_project_commands,
    get_security_commands,
    # Queries (Read side)
    ServiceQueries,
    ProjectQueries,
    SecurityQueries,
    get_service_queries,
    get_project_queries,
    get_security_queries,
    # Projections
    Projection,
    ServiceStatusProjection,
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
    # CQRS/Event Sourcing
    "Event",
    "EventType",
    "EventStore",
    "get_event_store",
    "set_event_store",
    "Aggregate",
    "ServiceAggregate",
    "ServiceCommands",
    "ProjectCommands",
    "SecurityCommands",
    "get_service_commands",
    "get_project_commands",
    "get_security_commands",
    "ServiceQueries",
    "ProjectQueries",
    "SecurityQueries",
    "get_service_queries",
    "get_project_queries",
    "get_security_queries",
    "Projection",
    "ServiceStatusProjection",
    "__version__",
]
