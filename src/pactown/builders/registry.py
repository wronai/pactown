"""Builder registry – resolve the right Builder for a given target."""

from __future__ import annotations

from typing import Optional

from ..targets import TargetConfig, TargetPlatform
from .base import Builder
from .desktop import DesktopBuilder
from .mobile import MobileBuilder
from .web import WebBuilder

_BUILDERS: dict[TargetPlatform, Builder] = {
    TargetPlatform.WEB: WebBuilder(),
    TargetPlatform.DESKTOP: DesktopBuilder(),
    TargetPlatform.MOBILE: MobileBuilder(),
}


def get_builder(platform: TargetPlatform) -> Builder:
    """Return the builder instance for the given platform."""
    builder = _BUILDERS.get(platform)
    if builder is None:
        raise ValueError(f"No builder registered for platform: {platform}")
    return builder


def get_builder_for_target(target: Optional[TargetConfig] = None) -> Builder:
    """Return the builder for a TargetConfig (defaults to web)."""
    if target is None:
        return _BUILDERS[TargetPlatform.WEB]
    return get_builder(target.platform)
