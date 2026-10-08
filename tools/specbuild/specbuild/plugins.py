"""Plugin registry for specbuild build pipeline.

Provides decorator-based registration for quality checks, enhancements,
and output tasks.  Plugins self-register at import time; the build driver
queries the registry to discover enabled plugins for each pipeline phase.

Usage::

    from specbuild.plugins import register_quality_check
    from specbuild.context import BuildContext

    @register_quality_check(
        name='editorial',
        cli_flags=['--editorial', '--editorial-strict'],
        description='Run editorial consistency check',
    )
    def editorial_check(ctx: BuildContext):
        from specbuild.checks.editorial import (check_editorial_soup,
                                          report_editorial_issues,
                                          load_editorial_rules)
        extra_rules = None
        if ctx.args.editorial_rules:
            extra_rules = load_editorial_rules(Path(ctx.args.editorial_rules))
        issues = check_editorial_soup(ctx.soup, extra_rules=extra_rules)
        report_editorial_issues(issues, strict=ctx.args.editorial_strict)
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Plugin specification
# ---------------------------------------------------------------------------


@dataclass
class PluginSpec:
    """Metadata and callable for a registered plugin."""

    name: str
    phase: str  # 'quality_check', 'enhancement', or 'output_task'
    cli_flags: list[str] = field(default_factory=list)
    description: str = ""
    func: Callable | None = None
    enabled: Callable[[argparse.Namespace], bool] | None = None
    order: int = 100
    """Execution order within a phase (lower runs first).

    Only meaningful for enhancements (which run sequentially).
    Quality checks and output tasks ignore this field.
    """
    precompute: Callable[[argparse.Namespace], Any] | None = None
    """Optional I/O-bound pre-computation callable.

    If set, the enhancement runner calls ``precompute(args)`` in a
    thread pool *before* the sequential apply phase.  The result is
    stored in ``ctx.precomputed[name]`` for the plugin's ``func``
    to retrieve.
    """

    def is_enabled(self, args: argparse.Namespace) -> bool:
        """Check whether this plugin should run for the given CLI args."""
        if self.enabled is not None:
            return self.enabled(args)
        # Default: true if any associated CLI flag attribute is truthy
        for flag in self.cli_flags:
            attr = flag.lstrip("-").replace("-", "_")
            if getattr(args, attr, False):
                return True
        return False


# ---------------------------------------------------------------------------
# Global registries
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, list[PluginSpec]] = {
    "quality_check": [],
    "enhancement": [],
    "output_task": [],
}


def _register(
    phase: str,
    *,
    name: str,
    cli_flags: list[str] | None = None,
    description: str = "",
    enabled: Callable | None = None,
    order: int = 100,
    precompute: Callable[[argparse.Namespace], Any] | None = None,
):
    """Internal decorator factory for plugin registration."""

    def decorator(func: Callable) -> Callable:
        spec = PluginSpec(
            name=name,
            phase=phase,
            cli_flags=cli_flags or [],
            description=description,
            func=func,
            enabled=enabled,
            order=order,
            precompute=precompute,
        )
        _REGISTRY[phase].append(spec)
        return func

    return decorator


def register_quality_check(**kwargs):
    """Register a read-only quality check plugin.

    The decorated function receives a single :class:`BuildContext` argument.
    """
    return _register("quality_check", **kwargs)


def register_enhancement(**kwargs):
    """Register a soup-mutating enhancement plugin.

    The decorated function receives a single :class:`BuildContext` argument.
    It should set ``ctx.dirty = True`` when it modifies the soup.
    """
    return _register("enhancement", **kwargs)


def register_output_task(**kwargs):
    """Register an output generation task plugin.

    The decorated function receives a single :class:`BuildContext` argument.
    """
    return _register("output_task", **kwargs)


# ---------------------------------------------------------------------------
# Query API
# ---------------------------------------------------------------------------


def get_enabled_plugins(phase: str, args: argparse.Namespace) -> list[PluginSpec]:
    """Return plugins for *phase* that are enabled by *args*.

    Results are sorted by :attr:`PluginSpec.order` (lower runs first).

    Args:
        phase: One of ``'quality_check'``, ``'enhancement'``, ``'output_task'``.
        args: Parsed CLI arguments.

    Returns:
        List of enabled :class:`PluginSpec` instances, sorted by order.
    """
    return sorted(
        [p for p in _REGISTRY.get(phase, []) if p.is_enabled(args)],
        key=lambda p: p.order,
    )


def list_all_plugins() -> list[PluginSpec]:
    """Return all registered plugins across all phases."""
    result: list[PluginSpec] = []
    for phase_plugins in _REGISTRY.values():
        result.extend(phase_plugins)
    return result


# ---------------------------------------------------------------------------
# Feature help generator
# ---------------------------------------------------------------------------

_PHASE_LABELS = {
    "quality_check": "Quality Checks",
    "enhancement": "Enhancements",
    "output_task": "Output Tasks",
}


def generate_feature_help() -> str:
    """Generate a formatted feature listing grouped by pipeline phase.

    Returns:
        Human-readable string suitable for terminal output.
    """
    lines: list[str] = []
    lines.append("Available build features:")
    lines.append("")

    for phase, label in _PHASE_LABELS.items():
        plugins = _REGISTRY.get(phase, [])
        if not plugins:
            continue

        lines.append(f"  {label}:")
        for p in sorted(plugins, key=lambda x: x.name):
            flags = ", ".join(p.cli_flags) if p.cli_flags else "(always)"
            lines.append(f"    {p.name:<24s} {p.description}")
            lines.append(f"    {'':24s} Flags: {flags}")
        lines.append("")

    if not any(_REGISTRY.values()):
        lines.append("  (no plugins registered)")
        lines.append("")

    return "\n".join(lines)
