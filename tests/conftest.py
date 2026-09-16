"""Shared test fixtures.

The repo root IS the Hermes plugin package (``__init__.py`` + ``register()``), so
its own module-level relative import (``from .home_subscribe import ...``) fails
when a test loads the root directory as a top-level module. Load the plugin's
``home_subscribe`` module directly instead of importing the package.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_plugin_module():
    """Import ``home_subscribe.py`` from the repo root as a standalone module."""
    if "home_subscribe" in sys.modules:
        return sys.modules["home_subscribe"]
    spec = importlib.util.spec_from_file_location(
        "home_subscribe", REPO_ROOT / "home_subscribe.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["home_subscribe"] = module
    spec.loader.exec_module(module)
    return module
