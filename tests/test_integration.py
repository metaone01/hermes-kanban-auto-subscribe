"""Integration tests: run the plugin's sweep against a throwaway board DB.

Requires a Hermes install (``pip install hermes-agent``) — skipped otherwise.

    python -m pytest tests/ -v
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "kanban-auto-subscribe"
sys.path.insert(0, str(PACKAGE_DIR))

kb = pytest.importorskip("hermes_cli.kanban_db", reason="hermes-agent is not installed")

import auto_subscribe as hs  # noqa: E402

# Resolve the module layout the same way the plugin does: newer Hermes splits the
# connection/notify helpers out of ``kanban_db``, older builds keep them there.
_kb, kbc = hs._kb_modules()
try:
    from hermes_cli import kanban_db_notify as kbn
except ImportError:  # older build
    kbn = _kb

if not hasattr(kbn, "add_notify_sub"):  # pragma: no cover - layout guard
    kbn = _kb

HOMES = [{"platform": "qqbot", "chat_id": "TESTCHAT", "thread_id": ""}]
BOARD = "plugintest"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated kanban home + hermes home so neither real store is touched."""
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(tmp_path / "kanban-home"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)
    return tmp_path


@pytest.fixture()
def conn(env):
    c = kbc.connect(board=BOARD)
    yield c
    c.close()


@pytest.fixture()
def state(env):
    s = hs._state_open()
    yield s
    s.close()


def _make(conn, **kw):
    return kb.create_task(conn, title=kw.pop("title", "card"), **kw)


def test_subscribes_live_cards_and_skips_archived(conn, state):
    live = _make(conn, title="live")
    blocked = _make(conn, title="blocked")
    kb.block_task(conn, blocked, reason="hold")
    archived = _make(conn, title="gone")
    kb.archive_task(conn, archived)

    stats = hs.subscribe_board(BOARD, HOMES, state_conn=state)

    assert stats["cards"] == 2
    assert stats["subs"] == 2
    subs = kbn.list_notify_subs(conn)
    assert {s["task_id"] for s in subs} == {live, blocked}
    assert all(s["platform"] == "qqbot" and s["chat_id"] == "TESTCHAT" for s in subs)


def test_writes_the_same_row_shape_as_the_dashboard_toggle(conn, state):
    _make(conn)
    hs.subscribe_board(BOARD, HOMES, state_conn=state)
    sub = kbn.list_notify_subs(conn)[0]
    assert sub["platform"] == "qqbot"
    assert sub["chat_id"] == "TESTCHAT"
    assert sub["notifier_profile"]
    assert sub["thread_id"] in ("", None)
    # Newer schemas carry a delivery_mode; it must be the passive "notify", never
    # an agent wake. Older builds predate the column entirely.
    if "delivery_mode" in sub:
        assert sub["delivery_mode"] == "notify"
    # Cursor seeded to "now", so a first-run backfill cannot replay history.
    if "last_event_id" in sub:
        assert sub["last_event_id"] >= 0


def test_is_idempotent(conn, state):
    _make(conn)
    first = hs.subscribe_board(BOARD, HOMES, state_conn=state)
    second = hs.subscribe_board(BOARD, HOMES, state_conn=state)
    assert first["subs"] == 1
    assert second["subs"] == 0
    assert second["skipped"] == 1
    assert len(kbn.list_notify_subs(conn)) == 1


def test_manual_unsubscribe_is_not_resurrected(conn, state):
    """A deliberately removed (or dead-chat-dropped) sub must stay removed --
    re-adding it every tick would spin against the channel forever."""
    task = _make(conn)
    hs.subscribe_board(BOARD, HOMES, state_conn=state)
    kbn.remove_notify_sub(conn, task_id=task, platform="qqbot", chat_id="TESTCHAT")

    stats = hs.subscribe_board(BOARD, HOMES, state_conn=state)

    assert stats["subs"] == 0
    assert kbn.list_notify_subs(conn) == []


def test_new_card_is_picked_up_on_a_later_sweep(conn, state):
    _make(conn, title="first")
    hs.subscribe_board(BOARD, HOMES, state_conn=state)
    fresh = _make(conn, title="second")

    stats = hs.subscribe_board(BOARD, HOMES, state_conn=state)

    assert stats["cards"] == 1
    assert fresh in {s["task_id"] for s in kbn.list_notify_subs(conn)}


def test_state_pruned_on_archive_and_card_becomes_eligible_again(conn, state):
    task = _make(conn)
    hs.subscribe_board(BOARD, HOMES, state_conn=state)
    kb.archive_task(conn, task)

    pruned = hs.subscribe_board(BOARD, HOMES, state_conn=state)
    assert pruned["pruned_state"] == 1

    # Back to a live status: the plugin forgets it left, so it subscribes again.
    conn.execute("UPDATE tasks SET status = 'ready' WHERE id = ?", (task,))
    conn.commit()
    again = hs.subscribe_board(BOARD, HOMES, state_conn=state)
    assert again["cards"] == 1


def test_dry_run_writes_nothing(conn, state):
    _make(conn)
    stats = hs.subscribe_board(BOARD, HOMES, state_conn=state, dry_run=True)
    assert stats["cards"] == 1
    assert kbn.list_notify_subs(conn) == []
    # ...and leaves the card eligible for a real sweep.
    real = hs.subscribe_board(BOARD, HOMES, state_conn=state)
    assert real["cards"] == 1


def test_max_per_tick_caps_one_sweep(conn, state):
    for i in range(5):
        _make(conn, title=f"card {i}")
    stats = hs.subscribe_board(BOARD, HOMES, state_conn=state, max_per_tick=2)
    assert stats["cards"] == 2
    # The rest are picked up by later sweeps.
    rest = hs.subscribe_board(BOARD, HOMES, state_conn=state, max_per_tick=2)
    assert rest["cards"] == 2


def test_no_homes_is_a_noop(conn, state):
    _make(conn)
    stats = hs.subscribe_board(BOARD, [], state_conn=state)
    assert stats == {"cards": 0, "subs": 0, "skipped": 0, "candidates": 0, "pruned_state": 0}
    assert kbn.list_notify_subs(conn) == []


def test_multiple_homes_subscribe_each_platform(conn, state):
    _make(conn)
    homes = HOMES + [{"platform": "telegram", "chat_id": "TG", "thread_id": "7"}]
    stats = hs.subscribe_board(BOARD, homes, state_conn=state)
    assert stats["subs"] == 2
    subs = {s["platform"]: s for s in kbn.list_notify_subs(conn)}
    assert subs["telegram"]["thread_id"] == "7"
