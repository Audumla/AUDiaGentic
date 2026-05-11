#!/usr/bin/env bash
# Download llamafile base and GGUF model for the embedded rig.
# Runs them separately (no bundling). Two files, one command to launch.
# Output: .audiagentic/provisioning/rig/embedded/bin/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../../../../.." && pwd)"
BIN_DIR="$ROOT/.audiagentic/provisioning/rig/embedded/bin"

mkdir -p "$BIN_DIR"

MODEL_URL="${MODEL_URL:-https://huggingface.co/bartowski/Qwen_Qwen3.5-2B-GGUF/resolve/main/Qwen_Qwen3.5-2B-Q4_K_S.gguf}"
MODEL_FILE="$BIN_DIR/Qwen_Qwen3.5-2B-Q4_K_S.gguf"

LLAMAFILE_VERSION="${LLAMAFILE_VERSION:-0.10.1}"
LLAMAFILE_URL="https://github.com/mozilla-ai/llamafile/releases/download/${LLAMAFILE_VERSION}/llamafile-${LLAMAFILE_VERSION}"
LLAMAFILE_BIN="$BIN_DIR/llamafile"

# Download llamafile base
if [ ! -f "$LLAMAFILE_BIN" ]; then
  printf 'Downloading llamafile %s...\n' "$LLAMAFILE_VERSION"
  curl -fL "$LLAMAFILE_URL" -o "$LLAMAFILE_BIN"
  chmod +x "$LLAMAFILE_BIN"
  printf '  -> %s\n' "$LLAMAFILE_BIN"
else
  printf 'llamafile already present: %s\n' "$LLAMAFILE_BIN"
fi

# Download GGUF model
if [ ! -f "$MODEL_FILE" ]; then
  printf 'Downloading model (this may take a while)...\n  %s\n' "$MODEL_URL"
  curl -fL "$MODEL_URL" -o "$MODEL_FILE"
  printf '  -> %s\n' "$MODEL_FILE"
else
  printf 'Model already present: %s\n' "$MODEL_FILE"
fi

printf '\nReady. Launch with:\n'
printf '  src/audiagentic/provisioning/rig/embedded/scripts/start-rig.sh\n'
