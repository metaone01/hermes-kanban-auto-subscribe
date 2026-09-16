<div align="center">
<h1>📣 kanban-auto-subscribe — Auto-subscribe every Hermes Kanban card to your home channels</h1>

<p>
  <img src="https://img.shields.io/badge/version-0.1.0-blue.svg" alt="version">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="python">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="license">
  <img src="https://img.shields.io/badge/Hermes-Plugin-purple.svg" alt="hermes-plugin">
  <img src="https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey.svg" alt="platform">
  <img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs welcome">
</p>

[中文](./README.md) | [English](./README.en.md)

<p>
  <b>Every card on your <a href="https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban">Hermes Kanban</a> board, automatically subscribed to every configured home channel.</b><br>
  No per-card clicking · Idempotent · Passive notify, no agent wake · Backfill never replays history
</p>
</div>

---

## 💡 The problem

Hermes Kanban has a dashboard toggle called **“Notify home channels”**: turn it on for a card and
its terminal events (`completed` / `blocked` / `gave_up` / `crashed` / `timed_out` …) get delivered
to that platform's home channel.

It is a **per-card, per-platform manual toggle**, and the two built-in mechanisms don't cover it:

| Mechanism | What it actually does |
|---|---|
| `kanban.auto_subscribe_on_create` (default `true`) | Subscribes the **originating session** (platform + chat id + thread id), **not** the home channel. Only fires in a persistent gateway/TUI session — CLI and cron calls are skipped entirely. |
| `/kanban create` auto-subscribe | Also subscribes **the current chat**, always in `notify+wake` mode, and ignores `auto_subscribe_on_create`. |
| Dashboard “Notify home channels” | Correct behaviour, but you click it **once per card**. |

There is no `notify_home_on_create`-style config key anywhere, so “new cards subscribe to the home
channel by default” is not achievable through configuration. This plugin closes that gap.

---

## 📥 Install

### Option 1 — Hermes plugin command (recommended)

The plugin lives in the `kanban-auto-subscribe/` subdirectory of this repository, so the install
command must name that subdirectory:

```bash
hermes plugins install metaone01/hermes-kanban-auto-subscribe/kanban-auto-subscribe
hermes plugins enable kanban-auto-subscribe
```

> Plugins are opt-in (the `plugins.enabled` allow-list), so `enable` is required.
> This plugin requests no capabilities — it only reads and writes Kanban's own subscription table.

Restart the gateway so the plugin gets loaded:

```bash
hermes gateway restart
```

The first run backfills every board (see [How it works](#-how-it-works)).

### Option 2 — install scripts

Three platform scripts ship in the repo root. They locate your Hermes directory, copy the plugin,
verify the files and optionally enable it:

```bash
# Linux
./install.sh

# macOS (Homebrew-aware)
./install-macos.sh

# Windows (PowerShell 5.1+ / 7+)
.\install.ps1
```

Common flags: `--force` (overwrite, backing up the old copy), `--uninstall`, `--no-deps`, `--help`.
The PowerShell equivalents are `-Force` / `-Uninstall` / `-NoDeps` / `-Help`.
If your execution policy blocks the script:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
```

### Option 3 — manual copy

```bash
git clone https://github.com/metaone01/hermes-kanban-auto-subscribe.git
cd hermes-kanban-auto-subscribe
cp -r kanban-auto-subscribe ~/.hermes/plugins/     # Windows: %USERPROFILE%\.hermes\plugins\
hermes plugins enable kanban-auto-subscribe
```

Replace the path if your `HERMES_HOME` is not the default.

---

## ⚙️ How it works

The plugin hooks `on_kanban_dispatch_tick`. The gateway-embedded dispatcher fires that hook
**per board** every `kanban.dispatch_interval_seconds` (60s by default). On each tick the plugin:

1. reads every **non-`archived`** card on that board;
2. finds the (card, platform) pairs it has not subscribed yet;
3. writes the subscription using **exactly the same call** the dashboard toggle uses.

The row it writes:

```
task_id | platform | chat_id | thread_id | chat_type | delivery_mode | notifier_profile
t_xxxx  | qqbot    | <home>  |           | dm        | notify        | <active profile>
```

`hermes kanban notify-list` shows these rows; they are indistinguishable from manually created ones.

### Three design decisions that matter

**1. Passive delivery — no agent wake.**
The default `notify` delivery mode is used: one message, no extra agent turn on the destination.
(`/kanban create` auto-subscribe uses `notify+wake`; waking an agent for every card would spend
tokens you probably didn't budget for.)

**2. First run never replays history.**
`add_notify_sub` seeds `last_event_id` to the task's current max event id, so enabling the plugin
does not dump every card's past events into your chat.

**3. Subscribe once, never resurrect.**
The plugin records which (board, task, platform) triples it wrote in its own state DB
(`~/.hermes/plugin-data/kanban-auto-subscribe/data.db`) and **never re-adds** a subscription that
was removed afterwards. That matters because:

- if you **unsubscribe** a card from the dashboard, the plugin will not silently put it back;
- if the gateway notifier **drops** a subscription after 12 consecutive send failures (dead chat),
  the plugin will not re-add it either — otherwise it would spin against a dead channel every 60s.

If a card is archived and later returns to an active status, the plugin forgets it and subscribes
again. That is intended.

---

## 🔧 Configuration

Settings live under `plugins.entries.kanban-auto-subscribe.settings` in `~/.hermes/config.yaml`:

```yaml
plugins:
  entries:
    kanban-auto-subscribe:
      settings:
        enabled: true        # master switch, default true
        max_per_tick: 500    # cards handled per board per tick, default 500
        dry_run: false       # report only, write nothing, default false
```

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Set `false` to pause without uninstalling. |
| `max_per_tick` | `500` | Per-board write cap per tick, so a huge board can't occupy the dispatcher thread for long. Remaining cards are handled on later ticks. |
| `dry_run` | `false` | Count what would be written without writing it — useful before enabling for real. |

### Want to preview the impact first?

Set `dry_run: true`, restart the gateway, then read the log:

```bash
grep kanban-auto-subscribe ~/.hermes/logs/gateway.log
```

```
kanban-auto-subscribe: board agent-unified — 191 card(s) / 191 subscription(s) [dry-run] on qqbot (state pruned 0)
```

### Requirements

- Hermes Agent (with Kanban)
- At least one platform with a configured home channel — via `/sethome` or a
  `<PLATFORM>_HOME_CHANNEL` env var (e.g. `QQBOT_HOME_CHANNEL`)

With no home channel configured, the plugin quietly does nothing each tick.

### Compatibility

Hermes moved the Kanban connection and notify helpers into separate modules
(`hermes_cli.kanban_db_connect`, `hermes_cli.kanban_db_notify`) and added
`plugins.plugin_storage` for plugin state. The plugin resolves both layouts at
runtime, so it runs on older builds too, falling back to a private
`plugin-data/` state DB when `plugin_storage` is absent.

Tested against:

| Hermes | Result |
|---|---|
| local git build 0.21.3 | 15/15 tests pass |
| PyPI release 0.19.0 (module layout predates the split) | 15/15 tests pass |

On a pre-split build, subscription rows have no `delivery_mode` column — that is
a schema difference, not a behaviour difference.

### Verify

```bash
hermes plugins list | grep kanban-auto-subscribe   # should show enabled
grep kanban-auto-subscribe ~/.hermes/logs/gateway.log
```

---

## 🧪 Development

```bash
git clone https://github.com/metaone01/hermes-kanban-auto-subscribe.git
cd hermes-kanban-auto-subscribe
pip install pytest hermes-agent            # hermes-agent provides the Kanban modules
python -m pytest tests/ -v
```

Two test layers:

- `tests/test_unit.py` — no Hermes needed: settings parsing, home-channel caching and failure tolerance.
- `tests/test_integration.py` — runs the real sweep against a **throwaway** board DB (isolated via
  `HERMES_KANBAN_HOME`, so your real board is never touched): first subscribe, idempotence, archive
  skipping, no-resurrection after manual unsubscribe, new-card pickup, `dry_run` writes nothing,
  `max_per_tick` cap.

## 📁 Layout

```
hermes-kanban-auto-subscribe/
├── kanban-auto-subscribe/       # ← the plugin itself (copy this dir to install)
│   ├── plugin.yaml              #   manifest: name: kanban-auto-subscribe
│   ├── __init__.py              #   register() entrypoint
│   └── auto_subscribe.py        #   subscription logic
├── tests/                       # tests
├── install.sh                   # Linux installer
├── install-macos.sh             # macOS installer (Homebrew-aware)
├── install.ps1                  # Windows installer
├── pytest.ini
├── LICENSE
├── README.md / README.en.md
└── .github/workflows/tests.yml
```
