"""Pactown – Decentralized Service Ecosystem Orchestrator using markpact"""

__version__ = "0.1.94"

from .config import CacheConfig, DependencyConfig, EcosystemConfig, ServiceConfig
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
from .platform import (
    DomainConfig,
    ProjectHostParts,
    SubdomainSeparator,
    api_base_url,
    build_origin,
    build_project_host,
    build_project_subdomain,
    build_service_subdomain,
    coerce_subdomain_separator,
    is_local_domain,
    normalize_domain,
    normalize_host,
    parse_project_host,
    parse_project_subdomain,
    to_dns_label,
    web_base_url,
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
from .llm import (
    PactownLLM,
    PactownLLMError,
    LLMNotAvailableError,
    get_llm,
    is_lolm_available,
    generate as llm_generate,
    get_llm_status,
    set_provider_priority as set_llm_priority,
    reset_provider as reset_llm_provider,
)

from .error_context import build_error_context

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
    # Platform
    "DomainConfig",
    "ProjectHostParts",
    "SubdomainSeparator",
    "api_base_url",
    "build_origin",
    "build_project_host",
    "build_project_subdomain",
    "build_service_subdomain",
    "coerce_subdomain_separator",
    "is_local_domain",
    "normalize_domain",
    "normalize_host",
    "parse_project_host",
    "parse_project_subdomain",
    "to_dns_label",
    "web_base_url",
    # Orchestration
    "EcosystemConfig",
    "ServiceConfig",
    "CacheConfig",
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
    # LLM
    "PactownLLM",
    "PactownLLMError",
    "LLMNotAvailableError",
    "get_llm",
    "is_lolm_available",
    "llm_generate",
    "get_llm_status",
    "set_llm_priority",
    "reset_llm_provider",
    "build_error_context",
    "__version__",
]
