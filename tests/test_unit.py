"""Unit tests that need no Hermes install: settings parsing and home filtering.

    python -m pytest tests/test_unit.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "kanban-auto-subscribe"
sys.path.insert(0, str(PACKAGE_DIR))

import auto_subscribe as hs  # noqa: E402


class FakeCtx:
    """Minimal stand-in for the plugin context's ``get_config``."""

    def __init__(self, values=None, raises=False):
        self.values = values or {}
        self.raises = raises

    def get_config(self, key, default=None):
        if self.raises:
            raise RuntimeError("boom")
        return self.values.get(key, default)


def test_settings_default_to_enabled_and_no_dry_run():
    settings = hs._settings(None)
    assert settings["enabled"] is True
    assert settings["dry_run"] is False
    assert settings["max_per_tick"] == hs._DEFAULT_MAX_PER_TICK


def test_settings_read_from_ctx():
    ctx = FakeCtx({"enabled": False, "dry_run": True, "max_per_tick": 7})
    settings = hs._settings(ctx)
    assert settings == {"enabled": False, "max_per_tick": 7, "dry_run": True}


def test_bad_max_per_tick_falls_back():
    for bad in ("nope", None, 0, -3, 1.5j):
        settings = hs._settings(FakeCtx({"max_per_tick": bad}))
        assert settings["max_per_tick"] == hs._DEFAULT_MAX_PER_TICK, bad


def test_unreadable_config_does_not_raise():
    settings = hs._settings(FakeCtx(raises=True))
    assert settings["enabled"] is True


def test_home_cache_is_bounded(monkeypatch):
    """``_home_channels`` must never raise and must cache within the TTL."""
    calls = []

    def fake_loader():
        calls.append(1)
        raise RuntimeError("no gateway here")

    fake_mod = type(sys)("gateway.config")
    fake_mod.load_gateway_config = fake_loader
    monkeypatch.setitem(sys.modules, "gateway.config", fake_mod)
    monkeypatch.setattr(hs, "_home_cache", None)

    assert hs._home_channels() == []
    assert hs._home_channels() == []
    assert len(calls) == 1, "second call should hit the TTL cache"

    monkeypatch.setattr(hs, "_home_cache", None)
