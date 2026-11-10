#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
MODEL_NAME="$(sed -n 's/^OLLAMA_MODEL=//p' "$BACKEND_DIR/.env" | head -n 1)"
MODEL_NAME="${MODEL_NAME:-qwen2.5:7b-instruct}"
TESSERACT_CMD="${TESSERACT_CMD:-$(sed -n 's/^TESSERACT_CMD=//p' "$BACKEND_DIR/.env" | head -n 1)}"
OLLAMA_PID=""
BACKEND_PID=""
FRONTEND_PID=""

for command_name in python3 node npm ollama curl; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$command_name" >&2
    exit 1
  fi
done

TESSERACT_CMD="${TESSERACT_CMD%\"}"
TESSERACT_CMD="${TESSERACT_CMD#\"}"
TESSERACT_CMD="${TESSERACT_CMD%\'}"
TESSERACT_CMD="${TESSERACT_CMD#\'}"
if [[ -n "$TESSERACT_CMD" ]]; then
  if [[ -x "$TESSERACT_CMD" ]]; then
    TESSERACT_BIN="$TESSERACT_CMD"
  elif command -v "$TESSERACT_CMD" >/dev/null 2>&1; then
    TESSERACT_BIN="$(command -v "$TESSERACT_CMD")"
  else
    printf 'Tesseract OCR executable was not found: %s\n' "$TESSERACT_CMD" >&2
    exit 1
  fi
else
  TESSERACT_BIN="$(command -v tesseract || true)"
fi
if [[ -z "$TESSERACT_BIN" ]]; then
  printf 'Tesseract OCR is required. Install it with tur and eng language data, or set TESSERACT_CMD in backend/.env.\n' >&2
  exit 1
fi
TESSERACT_LANGUAGES="$("$TESSERACT_BIN" --list-langs 2>/dev/null)"
if ! grep --fixed-strings --line-regexp --quiet tur <<<"$TESSERACT_LANGUAGES" ||
   ! grep --fixed-strings --line-regexp --quiet eng <<<"$TESSERACT_LANGUAGES"; then
  printf 'Tesseract must have both tur and eng language data installed.\n' >&2
  exit 1
fi

if ! curl --silent --fail http://127.0.0.1:11434/api/tags >/dev/null; then
  ollama serve >"$ROOT_DIR/ollama.log" 2>&1 &
  OLLAMA_PID=$!
  for _ in $(seq 1 60); do
    if curl --silent --fail http://127.0.0.1:11434/api/tags >/dev/null; then
      break
    fi
    sleep 1
  done
  if ! curl --silent --fail http://127.0.0.1:11434/api/tags >/dev/null; then
    printf 'Ollama did not start; see %s\n' "$ROOT_DIR/ollama.log" >&2
    exit 1
  fi
fi

if ! ollama list | awk 'NR > 1 {print $1}' | grep --fixed-strings --line-regexp --quiet "$MODEL_NAME"; then
  ollama pull "$MODEL_NAME"
fi

if [[ ! -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  python3 -m venv "$BACKEND_DIR/.venv"
fi
"$BACKEND_DIR/.venv/bin/python" -m pip install --upgrade pip
"$BACKEND_DIR/.venv/bin/python" -m pip install -r "$BACKEND_DIR/requirements.txt"

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  (cd "$FRONTEND_DIR" && npm ci)
fi
(cd "$FRONTEND_DIR" && npm run build -- --webpack)

cleanup() {
  for process_id in "$FRONTEND_PID" "$BACKEND_PID" "$OLLAMA_PID"; do
    if [[ -n "$process_id" ]]; then
      kill "$process_id" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

(cd "$BACKEND_DIR" && exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000) \
  >"$ROOT_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

(cd "$FRONTEND_DIR" && exec node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3000) \
  >"$ROOT_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!

printf 'Frontend: http://127.0.0.1:3000\n'
printf 'Backend API: proxied through Next.js at /api/v1/clinical/*\n'
printf 'Local-only bind is intentional. Do not expose clinical traffic without TLS and authentication.\n'

set +e
wait -n "$BACKEND_PID" "$FRONTEND_PID"
exit_code=$?
set -e
exit "$exit_code"
