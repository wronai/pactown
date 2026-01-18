"""
LLM Integration for Pactown.

Provides LLM rotation, fallback, and management using the lolm library.
This module enables AI-powered features in pactown with automatic
provider rotation when rate limits are hit.
"""

import os
from typing import Any, Callable, Dict, List, Optional
from pathlib import Path

try:
    from lolm import (
        LLMManager,
        RotationQueue,
        ProviderHealth,
        ProviderState,
        RateLimitInfo,
        RateLimitType,
        LLMRotationManager,
        LLMRateLimitError,
        get_client,
        list_available_providers,
        load_config as load_lolm_config,
        save_config as save_lolm_config,
        LLMConfig,
    )
    LOLM_AVAILABLE = True
except ImportError:
    LOLM_AVAILABLE = False
    LLMManager = None
    RotationQueue = None


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
                "lolm library not available. Install with: pip install lolm"
            )
        
        self._manager = LLMManager(verbose=verbose, enable_rotation=True)
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
        
        # Set up rotation queue callbacks
        queue = self._manager.get_rotation_queue()
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
        
        return self._manager.generate_with_rotation(
            prompt, system=system, max_tokens=max_tokens, max_retries=max_retries
        )
    
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
        health = self._manager.get_provider_health()
        
        # Merge status with health info
        for name in status:
            if name in health:
                status[name]['health'] = health[name]
        
        return {
            'providers': status,
            'available_providers': list_available_providers() if LOLM_AVAILABLE else [],
            'is_available': self.is_available,
        }
    
    def get_provider_health(self, name: str = None) -> Dict:
        """Get health info for providers."""
        if not self._initialized:
            self.initialize()
        return self._manager.get_provider_health(name)
    
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
            'available': False,
            'error': 'lolm library not installed',
            'install': 'pip install lolm',
        }
    
    try:
        llm = get_llm()
        return llm.get_status()
    except Exception as e:
        return {
            'available': False,
            'error': str(e),
        }


def set_provider_priority(name: str, priority: int) -> bool:
    """Set priority for an LLM provider."""
    if not LOLM_AVAILABLE:
        return False
    llm = get_llm()
    return llm.set_provider_priority(name, priority)


def reset_provider(name: str) -> bool:
    """Reset an LLM provider's health metrics."""
    if not LOLM_AVAILABLE:
        return False
    llm = get_llm()
    return llm.reset_provider(name)
