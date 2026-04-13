#!/usr/bin/env bash
# Pull required Ollama models for Pillywiggins.
#
# Usage:
#   ./scripts/pull-models.sh [OLLAMA_BASE_URL]
#
# Defaults to http://localhost:11434 if not specified.

set -euo pipefail

OLLAMA_URL="${1:-http://localhost:11434}"

echo "Pulling LLM model: qwen3.5:8b ..."
OLLAMA_HOST="$OLLAMA_URL" ollama pull qwen3.5:8b

echo "Pulling embedding model: nomic-embed-text ..."
OLLAMA_HOST="$OLLAMA_URL" ollama pull nomic-embed-text

echo "Done. Models pulled successfully."