"""Shared test fixtures.

The plugin package lives in ``kanban-auto-subscribe/`` (repo root holds the docs,
licence and install scripts). Its ``__init__.py`` does a relative import that only
resolves when Hermes loads the directory as a package, so tests load
``auto_subscribe.py`` from the package directory directly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "kanban-auto-subscribe"

# Make ``import auto_subscribe`` work from the tests, matching what a standalone
# module load does below.
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))


def load_plugin_module():
    """Import ``auto_subscribe.py`` from the plugin package as a standalone module."""
    if "auto_subscribe" in sys.modules:
        return sys.modules["auto_subscribe"]
    spec = importlib.util.spec_from_file_location(
        "auto_subscribe", PACKAGE_DIR / "auto_subscribe.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["auto_subscribe"] = module
    spec.loader.exec_module(module)
    return module
