#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-"$ROOT/.venv/bin/python"}"
LOG_DIR="$ROOT/.local/logs"

KILL_FIRST=1
KILL_ONLY=0
BACKGROUND=0
LIST_DEVICES=0
HEADLESS=0

usage() {
  cat <<'USAGE'
Usage: scripts/run-local.sh [options] [-- extra agent.main args]

Starts Voice Keyboard Engine locally with the Software Capture Path.
By default it kills existing local agent.main processes, then runs:
  .venv/bin/python -m agent.main --no-serial --no-ui

Options:
  --no-kill       Do not kill existing agent.main processes first.
  --kill-only     Kill existing agent.main processes and exit.
  --background    Start in background and write a log under .local/logs/.
  --headless      Disable the floating status window and run terminal-only.
  --list-devices  List microphone devices and exit.
  -h, --help      Show this help.

Examples:
  scripts/run-local.sh
  scripts/run-local.sh --background
  scripts/run-local.sh --headless
  scripts/run-local.sh --kill-only
  scripts/run-local.sh -- --headless
USAGE
}

AGENT_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-kill)
      KILL_FIRST=0
      shift
      ;;
    --kill-only)
      KILL_ONLY=1
      shift
      ;;
    --background)
      BACKGROUND=1
      shift
      ;;
    --headless)
      HEADLESS=1
      shift
      ;;
    --list-devices)
      LIST_DEVICES=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      AGENT_ARGS+=("$@")
      break
      ;;
    *)
      AGENT_ARGS+=("$1")
      shift
      ;;
  esac
done

cd "$ROOT"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[run-local] Python not found or not executable: $PYTHON_BIN" >&2
  echo "[run-local] Create .venv first or set PYTHON=/path/to/python." >&2
  exit 1
fi

find_engine_pids() {
  pgrep -f 'python.*(-m[[:space:]]+agent\.main|agent/main\.py)' 2>/dev/null || true
}

kill_existing() {
  local pids
  pids="$(find_engine_pids | tr '\n' ' ' | xargs || true)"
  if [[ -z "$pids" ]]; then
    echo "[run-local] No existing agent.main process found."
    return
  fi

  echo "[run-local] Killing existing agent.main process(es): $pids"
  kill $pids 2>/dev/null || true
  sleep 0.8

  local survivors
  survivors="$(find_engine_pids | tr '\n' ' ' | xargs || true)"
  if [[ -n "$survivors" ]]; then
    echo "[run-local] Force killing remaining process(es): $survivors"
    kill -9 $survivors 2>/dev/null || true
  fi
}

if [[ "$KILL_FIRST" == "1" ]]; then
  kill_existing
fi

if [[ "$KILL_ONLY" == "1" ]]; then
  exit 0
fi

if [[ "$LIST_DEVICES" == "1" ]]; then
  if [[ ${#AGENT_ARGS[@]} -gt 0 ]]; then
    exec "$PYTHON_BIN" -m agent.main --list-devices "${AGENT_ARGS[@]}"
  fi
  exec "$PYTHON_BIN" -m agent.main --list-devices
fi

CMD=("$PYTHON_BIN" -m agent.main --no-serial)
if [[ "$HEADLESS" == "1" ]]; then
  CMD+=(--headless)
else
  CMD+=(--no-ui)
fi
if [[ ${#AGENT_ARGS[@]} -gt 0 ]]; then
  CMD+=("${AGENT_ARGS[@]}")
fi
echo "[run-local] Starting: ${CMD[*]}"

if [[ "$BACKGROUND" == "1" ]]; then
  mkdir -p "$LOG_DIR"
  LOG_FILE="$LOG_DIR/voice-keyboard-local.log"
  nohup "${CMD[@]}" >"$LOG_FILE" 2>&1 &
  echo "[run-local] Started PID=$!"
  echo "[run-local] Log: $LOG_FILE"
else
  exec "${CMD[@]}"
fi
