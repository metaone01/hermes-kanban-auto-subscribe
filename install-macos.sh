#!/usr/bin/env bash
# kanban-auto-subscribe installer for macOS (Homebrew-aware)
# Usage: ./install-macos.sh [--force] [--uninstall] [--no-deps] [--enable|--no-enable]
#
# Written for the Bash 3.2 that ships with macOS: no associative arrays, no
# ${var,,}, no mapfile.

set -euo pipefail

# ── 颜色 ────────────────────────────────────────────────────────────
if [ -t 1 ]; then
    RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
    BLUE=$'\033[34m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
else
    RED=""; GREEN=""; YELLOW=""; BLUE=""; BOLD=""; RESET=""
fi

TAG="kanban-auto-subscribe"
log()   { printf "%s[%s]%s %s\n" "$BLUE"   "$TAG" "$RESET" "$*"; }
ok()    { printf "%s[%s]%s %s\n" "$GREEN"  "$TAG" "$RESET" "$*"; }
warn()  { printf "%s[%s]%s %s\n" "$YELLOW" "$TAG" "$RESET" "$*" >&2; }
err()   { printf "%s[%s]%s %s\n" "$RED"    "$TAG" "$RESET" "$*" >&2; }
die()   { err "$*"; exit 1; }

PLUGIN_NAME="kanban-auto-subscribe"

# ── 参数解析 ────────────────────────────────────────────────────────
FORCE=0
UNINSTALL=0
NO_DEPS=0
ENABLE=""
for arg in "$@"; do
    case "$arg" in
        --force|-f)      FORCE=1 ;;
        --uninstall)     UNINSTALL=1 ;;
        --no-deps)       NO_DEPS=1 ;;
        --enable)        ENABLE=1 ;;
        --no-enable)     ENABLE=0 ;;
        --help|-h)
            cat <<EOF
$TAG installer (macOS)

Usage: ./install-macos.sh [options]

Options:
  -f, --force       Overwrite an existing installation (old copy is backed up)
      --uninstall   Remove the plugin
      --no-deps     Skip the Python / Hermes preflight checks
      --enable      Enable the plugin without prompting
      --no-enable   Install without enabling
  -h, --help        Show this help
EOF
            exit 0
            ;;
        *) die "Unknown argument: $arg" ;;
    esac
done

# ── 平台检查 ────────────────────────────────────────────────────────
[ "$(uname -s)" = "Darwin" ] || warn "This script targets macOS; on Linux use ./install.sh"

# ── 定位脚本所在目录与插件源 ────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$SCRIPT_DIR/$PLUGIN_NAME"

[ -d "$SRC_DIR" ] || die "Plugin source not found: $SRC_DIR
Run this script from a full clone of the repository."

# ── 定位 Hermes 插件目录 ────────────────────────────────────────────
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PLUGIN_DIR="$HERMES_HOME/plugins"
DEST_DIR="$PLUGIN_DIR/$PLUGIN_NAME"

# ── 卸载 ────────────────────────────────────────────────────────────
if [ "$UNINSTALL" -eq 1 ]; then
    if [ -d "$DEST_DIR" ]; then
        rm -rf "$DEST_DIR"
        ok "Uninstalled: $DEST_DIR"
        log "State DB left in place: $HERMES_HOME/plugin-data/$PLUGIN_NAME/"
    else
        warn "Not installed: $DEST_DIR"
    fi
    exit 0
fi

# ── 预检 ────────────────────────────────────────────────────────────
if [ "$NO_DEPS" -eq 0 ]; then
    # Homebrew (optional, but the usual source of a modern python3 on macOS)
    if command -v brew >/dev/null 2>&1; then
        ok "Homebrew found at $(brew --prefix)"
    else
        warn "Homebrew not found. That's fine as long as some python3 is on PATH."
    fi

    # Hermes CLI
    if command -v hermes >/dev/null 2>&1; then
        ok "Hermes CLI found: $(command -v hermes)"
    else
        warn "hermes not found in PATH — install it before enabling the plugin."
    fi

    # Python: Hermes requires 3.11+; prefer a Homebrew python3 when present.
    PYTHON_BIN=""
    if command -v brew >/dev/null 2>&1; then
        BREW_PREFIX="$(brew --prefix 2>/dev/null || true)"
        for candidate in "$BREW_PREFIX/bin/python3" "/opt/homebrew/bin/python3" "/usr/local/bin/python3"; do
            [ -n "$candidate" ] && [ -x "$candidate" ] && { PYTHON_BIN="$candidate"; break; }
        done
    fi
    if [ -z "$PYTHON_BIN" ]; then
        for candidate in python3 python; do
            if command -v "$candidate" >/dev/null 2>&1; then
                PYTHON_BIN="$candidate"
                break
            fi
        done
    fi

    if [ -n "$PYTHON_BIN" ]; then
        PY_VER=$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
        PY_MAJOR=${PY_VER%%.*}
        PY_MINOR=${PY_VER##*.}
        if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
            # /usr/bin/python3 on macOS is typically 3.9 — too old for Hermes.
            warn "$PYTHON_BIN is Python $PY_VER, but Hermes needs 3.11+."
            warn "Install a newer one:  brew install python@3.12"
        else
            ok "Python $PY_VER detected ($PYTHON_BIN)"
        fi
    else
        warn "No python3 in PATH. Install Python 3.11+:  brew install python@3.12"
    fi

    # Home channel: the plugin is a no-op without one.
    HOME_CHANNEL_FOUND=0
    for f in "$HERMES_HOME/.env" "$HERMES_HOME/config.yaml"; do
        [ -f "$f" ] || continue
        if grep -qE '^[A-Z0-9_]*_HOME_CHANNEL=' "$f" 2>/dev/null; then
            HOME_CHANNEL_FOUND=1
            break
        fi
    done
    if [ "$HOME_CHANNEL_FOUND" -eq 1 ]; then
        ok "A home channel is configured"
    else
        warn "No *_HOME_CHANNEL found in $HERMES_HOME."
        warn "The plugin does nothing until a platform has a home channel"
        warn "(use /sethome from the chat, or set e.g. TELEGRAM_HOME_CHANNEL in .env)."
    fi
else
    warn "Skipping preflight checks (--no-deps)"
fi

# ── 备份已存在的安装 ────────────────────────────────────────────────
mkdir -p "$PLUGIN_DIR"

if [ -d "$DEST_DIR" ]; then
    if [ "$FORCE" -eq 1 ]; then
        BACKUP="$DEST_DIR.backup.$(date +%Y%m%d-%H%M%S)"
        mv "$DEST_DIR" "$BACKUP"
        ok "Existing installation backed up to: $BACKUP"
    elif [ -t 0 ]; then
        warn "Already installed at: $DEST_DIR"
        read -r -p "Overwrite? Existing files will be backed up. [y/N]: " ans
        if [[ ! "${ans:-}" =~ ^[Yy]$ ]]; then
            die "Aborted by user"
        fi
        BACKUP="$DEST_DIR.backup.$(date +%Y%m%d-%H%M%S)"
        mv "$DEST_DIR" "$BACKUP"
        ok "Existing installation backed up to: $BACKUP"
    else
        die "Already installed at $DEST_DIR (non-interactive). Re-run with --force."
    fi
fi

# ── 复制插件（排除 macOS 元数据与本地缓存）──────────────────────────
log "Installing plugin to: $DEST_DIR"
cp -R "$SRC_DIR" "$DEST_DIR"
find "$DEST_DIR" -name '.DS_Store' -delete 2>/dev/null || true
find "$DEST_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$DEST_DIR" -name '*.pyc' -delete 2>/dev/null || true
xattr -cr "$DEST_DIR" 2>/dev/null || true   # drop quarantine flags on a fresh copy
ok "Files copied"

# ── 验证 ────────────────────────────────────────────────────────────
log "Verifying installation..."
MISSING_FILES=()
for f in plugin.yaml __init__.py auto_subscribe.py; do
    [ -f "$DEST_DIR/$f" ] || MISSING_FILES+=("$f")
done

if [ ${#MISSING_FILES[@]} -gt 0 ]; then
    die "Installation incomplete; missing: ${MISSING_FILES[*]}"
fi

MANIFEST_NAME="$(sed -n 's/^name:[[:space:]]*//p' "$DEST_DIR/plugin.yaml" | head -1 | tr -d '[:space:]')"
[ "$MANIFEST_NAME" = "$PLUGIN_NAME" ] \
    || die "plugin.yaml declares name '$MANIFEST_NAME' but the directory is '$PLUGIN_NAME'."
ok "All files present; manifest name matches"

# ── 启用 ────────────────────────────────────────────────────────────
if [ -z "$ENABLE" ]; then
    if [ -t 0 ] && command -v hermes >/dev/null 2>&1; then
        read -r -p "Enable the plugin now? [Y/n]: " ans
        ans=${ans:-Y}
        [[ "$ans" =~ ^[Yy]$ ]] && ENABLE=1 || ENABLE=0
    else
        ENABLE=0
    fi
fi

if [ "$ENABLE" -eq 1 ]; then
    if command -v hermes >/dev/null 2>&1; then
        if hermes plugins enable "$PLUGIN_NAME"; then
            ok "Plugin enabled"
        else
            warn "Could not enable automatically. Run: hermes plugins enable $PLUGIN_NAME"
        fi
    else
        warn "hermes not in PATH. Run: hermes plugins enable $PLUGIN_NAME"
    fi
else
    log "Plugin installed but not enabled."
    log "Run: hermes plugins enable $PLUGIN_NAME"
fi

# ── 完成 ────────────────────────────────────────────────────────────
cat <<EOF

${BOLD}${GREEN}✓ $TAG installed${RESET}

  Plugin dir:  $DEST_DIR
  Hermes home: $HERMES_HOME

Next steps:
  1. Restart the gateway so the plugin loads:
       hermes gateway restart
  2. Watch it work (one line per board that had cards to subscribe):
       grep $PLUGIN_NAME $HERMES_HOME/logs/gateway.log
  3. Confirm the subscriptions:
       hermes kanban notify-list

To preview before writing anything, set dry_run to true in
  $HERMES_HOME/config.yaml
    plugins.entries.$PLUGIN_NAME.settings.dry_run

Docs:  https://github.com/metaone01/hermes-kanban-auto-subscribe
EOF
