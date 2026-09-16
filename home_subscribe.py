"""Kanban home-channel auto-subscription.

Every dispatcher tick, ensure each non-archived card on the ticking board has a
passive notification subscription to every configured home channel.

Design notes that matter:

* Subscription is written exactly the way the dashboard's "Notify home channels"
  toggle writes it (``kanban_db_notify.add_notify_sub``), so the gateway notifier
  needs no extra plumbing and `hermes kanban notify-list` shows the same rows.
  ``add_notify_sub`` runs its own IMMEDIATE transaction, so it must NOT be wrapped
  in an outer one (nesting is opt-in and this helper does not opt in).
* It seeds ``last_event_id`` to the task's current max event id, so first-run
  backfill never replays history.
* Cards are subscribed ONCE. The plugin records what it subscribed in its own
  state DB and never resurrects a subscription removed afterwards -- whether the
  user unsubscribed it deliberately or the notifier dropped it after 12
  consecutive send failures (a dead chat). Re-adding those every tick would spin
  against a dead channel forever.
* Default delivery mode is used, i.e. a passive message with no agent wake: this
  is a notification destination, not a dispatch decision.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterable

logger = logging.getLogger(__name__)

PLUGIN_NAME = "kanban-home-subscribe"

# Cards handled per board per tick. First enable backfills the whole board; the
# cap keeps a large board from holding the dispatcher's tick thread for long.
_DEFAULT_MAX_PER_TICK = 500
# Home-channel config is re-read at most this often (seconds): the gateway config
# loader re-reads YAML + .env on every call, and a 60s tick does not need that.
_HOME_CACHE_TTL_SECONDS = 60.0

_home_cache: tuple[float, list[dict]] | None = None

# (board, task_id, platform) rows this plugin created. Kept in the plugin's own
# store (never in the board DB) so a later removal is respected.
_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscribed (
    board      TEXT NOT NULL,
    task_id    TEXT NOT NULL,
    platform   TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (board, task_id, platform)
)
"""


def _home_channels() -> list[dict]:
    """Every platform with a configured home channel, from the live GatewayConfig
    (so ``<PLATFORM>_HOME_CHANNEL`` env overlays are honoured), sorted by platform.
    Cached briefly; any failure yields no channels."""
    global _home_cache
    now = time.monotonic()
    if _home_cache is not None and now - _home_cache[0] < _HOME_CACHE_TTL_SECONDS:
        return _home_cache[1]
    homes: list[dict] = []
    try:
        from gateway.config import load_gateway_config

        gw_cfg = load_gateway_config()
        homes = [
            {
                "platform": platform.value,
                "chat_id": pcfg.home_channel.chat_id,
                "thread_id": pcfg.home_channel.thread_id or "",
            }
            for platform, pcfg in (gw_cfg.platforms or {}).items()
            if pcfg and pcfg.home_channel and pcfg.home_channel.chat_id
        ]
        homes.sort(key=lambda r: r["platform"])
    except Exception as exc:
        logger.debug("%s: home channel lookup failed: %s", PLUGIN_NAME, exc)
        homes = []
    _home_cache = (now, homes)
    return homes


def _active_profile() -> str:
    try:
        from hermes_cli.profiles import get_active_profile_name

        return get_active_profile_name() or "default"
    except Exception:
        return "default"


def _state_open():
    """Open (and migrate) the plugin-private state DB.

    Prefers Hermes' ``plugins.plugin_storage.plugin_db`` (state under
    ``<hermes home>/plugin-data/<name>/``, which survives plugin updates).
    Falls back to a private file for Hermes builds that predate that module —
    deliberately NOT the plugin install dir, which ``plugins update`` replaces.
    """
    import sqlite3

    conn = _state_connect()
    conn.row_factory = sqlite3.Row
    conn.execute(_STATE_SCHEMA)
    conn.commit()
    return conn


def _state_connect():
    """Best available state-DB connection for this Hermes build."""
    try:
        from plugins.plugin_storage import plugin_db

        return plugin_db(PLUGIN_NAME)
    except Exception:
        pass
    import sqlite3
    from pathlib import Path

    try:
        from hermes_constants import get_hermes_home

        base = get_hermes_home() / "plugin-data"
    except Exception:
        base = Path.home() / ".hermes" / "plugin-data"
    path = base / PLUGIN_NAME / "data.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(path))


def _kb_modules():
    """``(kanban_db, connect_module)`` for this Hermes build.

    Newer Hermes splits the connection helpers into ``kanban_db_connect``; older
    builds keep ``connect``/``write_txn`` directly on ``kanban_db``. Resolve once
    per call so the plugin works on both.
    """
    from hermes_cli import kanban_db as kb

    try:
        from hermes_cli import kanban_db_connect as kbc
    except ImportError:
        kbc = kb
    return kb, kbc


def subscribe_board(
    board: str,
    homes: Iterable[dict],
    *,
    state_conn: Any,
    max_per_tick: int = _DEFAULT_MAX_PER_TICK,
    notifier_profile: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Subscribe up to ``max_per_tick`` unhandled non-archived cards on *board*.

    Returns counters: ``cards`` (cards subscribed), ``subs`` (rows written),
    ``skipped`` (already handled), ``candidates`` (non-archived cards seen),
    ``pruned_state`` (state rows dropped for cards no longer live).
    """
    kb, kbc = _kb_modules()
    try:
        from hermes_cli import kanban_db_notify as kbn
    except ImportError:
        # Older builds predate the module split; notify helpers live on kanban_db.
        kbn = kb
    if not hasattr(kbn, "add_notify_sub"):
        kbn = kb

    homes = [h for h in homes if h.get("platform") and h.get("chat_id")]
    result = {"cards": 0, "subs": 0, "skipped": 0, "candidates": 0, "pruned_state": 0}
    if not homes:
        return result

    profile = notifier_profile or _active_profile()
    conn = kbc.connect(board=board)
    try:
        rows = conn.execute(
            "SELECT id FROM tasks WHERE status != 'archived' ORDER BY created_at ASC, id ASC",
        ).fetchall()
        result["candidates"] = len(rows)

        handled: set[tuple[str, str]] = set()
        if rows:
            handled = {
                (r["task_id"], r["platform"])
                for r in state_conn.execute(
                    "SELECT task_id, platform FROM subscribed WHERE board = ?", (board,),
                ).fetchall()
            }

        written: list[tuple[str, str]] = []
        for row in rows:
            if len(written) >= max_per_tick:
                break
            task_id = row["id"]
            need = [h for h in homes if (task_id, h["platform"]) not in handled]
            if not need:
                result["skipped"] += 1
                continue
            if dry_run:
                written.extend((task_id, h["platform"]) for h in need)
                result["cards"] += 1
                result["subs"] += len(need)
                continue
            try:
                # add_notify_sub opens its own IMMEDIATE txn; wrapping it would nest.
                for home in need:
                    kbn.add_notify_sub(
                        conn,
                        task_id=task_id,
                        platform=home["platform"],
                        chat_id=home["chat_id"],
                        thread_id=home["thread_id"] or None,
                        notifier_profile=profile,
                    )
                    written.append((task_id, home["platform"]))
                result["cards"] += 1
                result["subs"] += len(need)
            except Exception as exc:
                # One bad task must not abort the sweep; unrecorded rows retry next tick.
                logger.warning("%s: subscribe failed for %s on %s: %s", PLUGIN_NAME, task_id, board, exc)

        if written and not dry_run:
            now = int(time.time())
            state_conn.executemany(
                "INSERT OR IGNORE INTO subscribed (board, task_id, platform, created_at) "
                "VALUES (?, ?, ?, ?)",
                [(board, task_id, platform, now) for task_id, platform in written],
            )
            state_conn.commit()

        # Forget cards that left the board's live set (archived/removed) so an
        # unarchived card is eligible again. The live ids come from the BOARD
        # connection: `tasks` does not exist in the plugin's own state DB.
        live_ids = {row["id"] for row in rows}
        stale = [
            (r["task_id"], r["platform"])
            for r in state_conn.execute(
                "SELECT task_id, platform FROM subscribed WHERE board = ?", (board,),
            ).fetchall()
            if r["task_id"] not in live_ids
        ]
        if stale and not dry_run:
            cur = state_conn.executemany(
                "DELETE FROM subscribed WHERE board = ? AND task_id = ? AND platform = ?",
                [(board, task_id, platform) for task_id, platform in stale],
            )
            state_conn.commit()
            result["pruned_state"] = int(cur.rowcount or 0)
    finally:
        conn.close()
    return result


def on_dispatch_tick(ctx: Any = None, **kwargs: Any) -> None:
    """``on_kanban_dispatch_tick`` observer: fires per board, after the dispatch
    lock is released, in the gateway-embedded dispatcher."""
    try:
        settings = _settings(ctx)
        if not settings["enabled"]:
            return
        board = kwargs.get("board")
        if not board:
            from hermes_cli import kanban_db as kb

            board = kb.get_current_board()
        homes = _home_channels()
        if not homes:
            logger.debug("%s: no home channel configured; nothing to do", PLUGIN_NAME)
            return
        state_conn = _state_open()
        try:
            stats = subscribe_board(
                board,
                homes,
                state_conn=state_conn,
                max_per_tick=settings["max_per_tick"],
                dry_run=settings["dry_run"],
            )
        finally:
            state_conn.close()
        if stats["subs"] or stats["pruned_state"]:
            logger.info(
                "%s: board %s — %d card(s) / %d subscription(s)%s on %s (state pruned %d)",
                PLUGIN_NAME, board, stats["cards"], stats["subs"],
                " [dry-run]" if settings["dry_run"] else "",
                ", ".join(h["platform"] for h in homes), stats["pruned_state"],
            )
    except Exception as exc:  # observer hooks must never break dispatch
        logger.warning("%s: tick failed: %s", PLUGIN_NAME, exc, exc_info=True)


def _settings(ctx: Any) -> dict:
    """Read plugin settings with safe defaults."""
    def _get(key: str, default: Any) -> Any:
        try:
            return ctx.get_config(key, default) if ctx is not None else default
        except Exception:
            return default

    try:
        max_per_tick = int(_get("max_per_tick", _DEFAULT_MAX_PER_TICK))
    except (TypeError, ValueError):
        max_per_tick = _DEFAULT_MAX_PER_TICK
    if max_per_tick < 1:
        max_per_tick = _DEFAULT_MAX_PER_TICK
    return {
        "enabled": bool(_get("enabled", True)),
        "max_per_tick": max_per_tick,
        "dry_run": bool(_get("dry_run", False)),
    }
