"""
LLM Integration for Pactown.

Provides LLM rotation, fallback, and management using the lolm library.
This module enables AI-powered features in pactown with automatic
provider rotation when rate limits are hit.
"""

import os
import importlib
import inspect
from typing import Any, Callable, Dict, List, Optional
from pathlib import Path

LOLM_AVAILABLE = False
LOLM_VERSION: Optional[str] = None
LOLM_IMPORT_ERROR: Optional[str] = None

ROTATION_AVAILABLE = False
ROTATION_IMPORT_ERROR: Optional[str] = None

LLMManager = None
RotationQueue = None
ProviderHealth = None
ProviderState = None
RateLimitInfo = None
RateLimitType = None
LLMRotationManager = None
LLMRateLimitError = None
parse_rate_limit_headers = None
is_rate_limit_error = None
create_rotation_manager = None

get_client = None
list_available_providers = None
load_lolm_config = None
save_lolm_config = None
LLMConfig = None

try:
    _lolm = importlib.import_module("lolm")
    LOLM_VERSION = getattr(_lolm, "__version__", None)

    # Core APIs (exist in older lolm versions too)
    from lolm import LLMManager as _LLMManager  # type: ignore
    from lolm import get_client as _get_client  # type: ignore
    from lolm import list_available_providers as _list_available_providers  # type: ignore

    LLMManager = _LLMManager
    get_client = _get_client
    list_available_providers = _list_available_providers
    LOLM_AVAILABLE = True

    # Optional config helpers
    try:
        from lolm import load_config as _load_lolm_config  # type: ignore
        from lolm import save_config as _save_lolm_config  # type: ignore
        from lolm import LLMConfig as _LLMConfig  # type: ignore

        load_lolm_config = _load_lolm_config
        save_lolm_config = _save_lolm_config
        LLMConfig = _LLMConfig
    except Exception:
        pass

    # Rotation APIs (may not exist in older lolm versions)
    try:
        from lolm.rotation import (  # type: ignore
            RotationQueue as _RotationQueue,
            ProviderHealth as _ProviderHealth,
            ProviderState as _ProviderState,
            RateLimitInfo as _RateLimitInfo,
            RateLimitType as _RateLimitType,
            LLMRotationManager as _LLMRotationManager,
            parse_rate_limit_headers as _parse_rate_limit_headers,
            is_rate_limit_error as _is_rate_limit_error,
            create_rotation_manager as _create_rotation_manager,
        )

        RotationQueue = _RotationQueue
        ProviderHealth = _ProviderHealth
        ProviderState = _ProviderState
        RateLimitInfo = _RateLimitInfo
        RateLimitType = _RateLimitType
        LLMRotationManager = _LLMRotationManager
        parse_rate_limit_headers = _parse_rate_limit_headers
        is_rate_limit_error = _is_rate_limit_error
        create_rotation_manager = _create_rotation_manager
        ROTATION_AVAILABLE = True
    except Exception as e:
        ROTATION_AVAILABLE = False
        ROTATION_IMPORT_ERROR = str(e)

    # Optional rate limit error type
    try:
        from lolm.clients import LLMRateLimitError as _LLMRateLimitError  # type: ignore

        LLMRateLimitError = _LLMRateLimitError
    except Exception:
        pass

except Exception as e:
    LOLM_AVAILABLE = False
    LOLM_IMPORT_ERROR = str(e)


class PactownLLMError(Exception):
    """Base exception for Pactown LLM errors."""
    pass


class LLMNotAvailableError(PactownLLMError):
    """Raised when no LLM provider is available."""
    pass


class PactownLLM:
    """
    Pactown LLM Manager with rotation and fallback support.
    
    Integrates with the lolm library for multi-provider LLM management
    with automatic rotation when rate limits are hit.
    
    Usage:
        llm = PactownLLM()
        llm.initialize()
        
        # Simple generation
        response = llm.generate("Explain this code")
        
        # With rotation (automatic failover on rate limits)
        response = llm.generate_with_rotation("Explain this code")
        
        # Check status
        status = llm.get_status()
    """
    
    _instance: Optional['PactownLLM'] = None
    
    def __init__(self, verbose: bool = False):
        if not LOLM_AVAILABLE:
            raise ImportError(
                "lolm library not available. Install with: pip install -U pactown[llm]"
            )

        # lolm versions differ; detect whether rotation is supported and whether
        # the LLMManager supports `enable_rotation`.
        enable_rotation = ROTATION_AVAILABLE
        try:
            sig = inspect.signature(LLMManager.__init__)  # type: ignore[union-attr]
            if "enable_rotation" in sig.parameters:
                self._manager = LLMManager(verbose=verbose, enable_rotation=enable_rotation)
            else:
                self._manager = LLMManager(verbose=verbose)
        except Exception:
            self._manager = LLMManager(verbose=verbose)
        self._verbose = verbose
        self._initialized = False
        
        # Callbacks for events
        self._on_rate_limit: Optional[Callable[[str, Dict], None]] = None
        self._on_rotation: Optional[Callable[[str, str], None]] = None
        self._on_provider_unavailable: Optional[Callable[[str, str], None]] = None
    
    @classmethod
    def get_instance(cls, verbose: bool = False) -> 'PactownLLM':
        """Get or create the global PactownLLM instance."""
        if cls._instance is None:
            cls._instance = cls(verbose=verbose)
        return cls._instance
    
    @classmethod
    def set_instance(cls, instance: 'PactownLLM') -> None:
        """Set the global PactownLLM instance."""
        cls._instance = instance
    
    def initialize(self) -> None:
        """Initialize the LLM manager and all providers."""
        if self._initialized:
            return
        
        self._manager.initialize()
        
        # Set up rotation queue callbacks (only if supported by this lolm)
        get_queue = getattr(self._manager, "get_rotation_queue", None)
        queue = get_queue() if callable(get_queue) else None
        if queue:
            if self._on_rate_limit:
                queue.on_rate_limit(lambda name, info: self._on_rate_limit(name, info.to_dict() if hasattr(info, 'to_dict') else {}))
            if self._on_rotation:
                queue.on_rotation(self._on_rotation)
            if self._on_provider_unavailable:
                queue.on_provider_unavailable(self._on_provider_unavailable)
        
        self._initialized = True
    
    @property
    def is_available(self) -> bool:
        """Check if any LLM provider is available."""
        if not self._initialized:
            self.initialize()
        return self._manager.is_available
    
    def generate(
        self,
        prompt: str,
        system: str = None,
        max_tokens: int = 4000,
        provider: str = None
    ) -> str:
        """
        Generate completion using available provider.
        
        Args:
            prompt: User prompt
            system: System prompt
            max_tokens: Maximum tokens
            provider: Specific provider to use (optional)
            
        Returns:
            Generated text
            
        Raises:
            LLMNotAvailableError: If no provider is available
        """
        if not self._initialized:
            self.initialize()
        
        if not self.is_available:
            raise LLMNotAvailableError("No LLM provider available. Run: lolm status")
        
        return self._manager.generate(prompt, system=system, max_tokens=max_tokens, provider=provider)
    
    def generate_with_rotation(
        self,
        prompt: str,
        system: str = None,
        max_tokens: int = 4000,
        max_retries: int = 3
    ) -> str:
        """
        Generate with intelligent rotation based on provider health.
        
        Automatically rotates to next available provider when one
        hits rate limits or becomes unavailable.
        
        Args:
            prompt: User prompt
            system: System prompt
            max_tokens: Maximum tokens
            max_retries: Maximum number of providers to try
            
        Returns:
            Generated text
        """
        if not self._initialized:
            self.initialize()
        
        gen_rot = getattr(self._manager, "generate_with_rotation", None)
        if callable(gen_rot):
            return gen_rot(prompt, system=system, max_tokens=max_tokens, max_retries=max_retries)

        # Older lolm: no rotation method; fall back.
        return self._manager.generate_with_fallback(prompt, system=system, max_tokens=max_tokens)
    
    def generate_with_fallback(
        self,
        prompt: str,
        system: str = None,
        max_tokens: int = 4000,
        providers: List[str] = None
    ) -> str:
        """
        Generate with fallback to other providers on failure.
        
        Args:
            prompt: User prompt
            system: System prompt
            max_tokens: Maximum tokens
            providers: List of providers to try (in order)
            
        Returns:
            Generated text from first successful provider
        """
        if not self._initialized:
            self.initialize()
        
        return self._manager.generate_with_fallback(
            prompt, system=system, max_tokens=max_tokens, providers=providers
        )
    
    def get_status(self) -> Dict[str, Any]:
        """Get status of all providers including health info."""
        if not self._initialized:
            self.initialize()
        
        status = self._manager.get_status()
        get_health = getattr(self._manager, "get_provider_health", None)
        health = get_health() if callable(get_health) else {}
        
        # Merge status with health info
        for name in status:
            if name in health:
                status[name]['health'] = health[name]
        
        return {
            'providers': status,
            'available_providers': list_available_providers() if callable(list_available_providers) else [],
            'is_available': self.is_available,
            'lolm_version': LOLM_VERSION,
            'rotation_available': ROTATION_AVAILABLE,
            'rotation_import_error': ROTATION_IMPORT_ERROR,
        }
    
    def get_provider_health(self, name: str = None) -> Dict:
        """Get health info for providers."""
        if not self._initialized:
            self.initialize()
        get_health = getattr(self._manager, "get_provider_health", None)
        if callable(get_health):
            return get_health(name)
        return {}
    
    def set_provider_priority(self, name: str, priority: int) -> bool:
        """Set priority for a provider (lower = higher priority)."""
        if not self._initialized:
            self.initialize()
        return self._manager.set_provider_priority(name, priority)
    
    def reset_provider(self, name: str) -> bool:
        """Reset a provider's health metrics."""
        if not self._initialized:
            self.initialize()
        return self._manager.reset_provider(name)
    
    def get_rotation_queue(self) -> Optional[RotationQueue]:
        """Get the rotation queue for advanced control."""
        return self._manager.get_rotation_queue()
    
    # Event handlers
    def on_rate_limit(self, callback: Callable[[str, Dict], None]) -> None:
        """Set callback for rate limit events."""
        self._on_rate_limit = callback
    
    def on_rotation(self, callback: Callable[[str, str], None]) -> None:
        """Set callback for provider rotation events."""
        self._on_rotation = callback
    
    def on_provider_unavailable(self, callback: Callable[[str, str], None]) -> None:
        """Set callback for when a provider becomes unavailable."""
        self._on_provider_unavailable = callback


# Global instance accessor
def get_llm(verbose: bool = False) -> PactownLLM:
    """Get the global PactownLLM instance."""
    return PactownLLM.get_instance(verbose=verbose)


def is_lolm_available() -> bool:
    """Check if lolm library is available."""
    return LOLM_AVAILABLE


def get_lolm_info() -> Dict[str, Any]:
    """Get diagnostic info about lolm availability/features."""
    return {
        "lolm_installed": LOLM_AVAILABLE,
        "lolm_version": LOLM_VERSION,
        "lolm_import_error": LOLM_IMPORT_ERROR,
        "rotation_available": ROTATION_AVAILABLE,
        "rotation_import_error": ROTATION_IMPORT_ERROR,
    }


# Convenience functions
def generate(
    prompt: str,
    system: str = None,
    max_tokens: int = 4000,
    with_rotation: bool = True
) -> str:
    """
    Generate completion using the global LLM instance.
    
    Args:
        prompt: User prompt
        system: System prompt
        max_tokens: Maximum tokens
        with_rotation: Use rotation for automatic failover
        
    Returns:
        Generated text
    """
    llm = get_llm()
    if with_rotation:
        return llm.generate_with_rotation(prompt, system=system, max_tokens=max_tokens)
    return llm.generate(prompt, system=system, max_tokens=max_tokens)


def get_llm_status() -> Dict[str, Any]:
    """Get status of all LLM providers."""
    if not LOLM_AVAILABLE:
        return {
            'lolm_installed': False,
            'is_available': False,
            'error': 'lolm library not available in this environment',
            'install': 'pip install -U pactown[llm]  # or: pip install -U lolm',
            'lolm_import_error': LOLM_IMPORT_ERROR,
        }
    
    try:
        llm = get_llm()
        status = llm.get_status()
        status.setdefault('lolm_installed', True)
        status.setdefault('lolm_version', LOLM_VERSION)
        status.setdefault('rotation_available', ROTATION_AVAILABLE)
        status.setdefault('rotation_import_error', ROTATION_IMPORT_ERROR)
        return status
    except Exception as e:
        return {
            'lolm_installed': True,
            'is_available': False,
            'error': str(e),
            'lolm_version': LOLM_VERSION,
            'rotation_available': ROTATION_AVAILABLE,
            'rotation_import_error': ROTATION_IMPORT_ERROR,
        }


def set_provider_priority(name: str, priority: int) -> bool:
    """Set priority for an LLM provider."""
    if not LOLM_AVAILABLE:
        return False
    llm = get_llm()
    set_prio = getattr(llm, "set_provider_priority", None)
    if callable(set_prio):
        return set_prio(name, priority)
    return False


def reset_provider(name: str) -> bool:
    """Reset an LLM provider's health metrics."""
    if not LOLM_AVAILABLE:
        return False
    llm = get_llm()
    reset = getattr(llm, "reset_provider", None)
    if callable(reset):
        return reset(name)
    return False
