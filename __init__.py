"""Hermes plugin entrypoint.

Hermes loads this directory as a package (``<root>/<name>/__init__.py``), where the
relative import below works. Tooling that loads the directory as a plain top-level
module (pytest collecting the repo root) has no parent package, so fall back to an
absolute import of the sibling module.
"""

from __future__ import annotations

try:  # loaded as a package (the Hermes plugin loader path)
    from .home_subscribe import on_dispatch_tick
except ImportError:  # loaded as a top-level module (tooling / pytest)
    from home_subscribe import on_dispatch_tick

__all__ = ["register", "on_dispatch_tick"]


def register(ctx):
    ctx.register_hook("on_kanban_dispatch_tick", on_dispatch_tick)
