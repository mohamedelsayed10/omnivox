#!/usr/bin/env bash
# Calls every endpoint with curl. Usage: ./examples/curl.sh
# Reads OMNIVOX_BASE_URL (default http://localhost:8100) and OMNIVOX_API_KEY (optional).
set -euo pipefail

BASE_URL="${OMNIVOX_BASE_URL:-http://localhost:8100}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTH=()
if [[ -n "${OMNIVOX_API_KEY:-}" ]]; then
  AUTH=(-H "X-API-Key: ${OMNIVOX_API_KEY}")
fi

call() {
  echo
  echo "### $1"
  shift
  curl --silent --show-error --fail-with-body "$@"
  echo
}

call "health" "${BASE_URL}/health"
call "info" "${AUTH[@]}" "${BASE_URL}/api/v1/info"
call "livekit token" "${AUTH[@]}" -X POST "${BASE_URL}/api/v1/livekit/token" \
  -H "Content-Type: application/json" -d @"${HERE}/requests/token.json"
call "chat (invoke)" "${AUTH[@]}" -X POST "${BASE_URL}/api/v1/agent/invoke" \
  -H "Content-Type: application/json" -d @"${HERE}/requests/chat.json"

echo
echo "### chat (stream)"
curl --silent --show-error --no-buffer "${AUTH[@]}" -X POST "${BASE_URL}/api/v1/agent/stream" \
  -H "Content-Type: application/json" -d @"${HERE}/requests/chat.json"

call "upload document" "${AUTH[@]}" -X POST "${BASE_URL}/api/v1/knowledge/documents" \
  -F "file=@${HERE}/sample_document.md" -F "source=sample_document.md"
call "list documents" "${AUTH[@]}" "${BASE_URL}/api/v1/knowledge/documents"
call "search knowledge base" "${AUTH[@]}" -X POST "${BASE_URL}/api/v1/knowledge/search" \
  -H "Content-Type: application/json" -d @"${HERE}/requests/search.json"
call "delete document" "${AUTH[@]}" -X DELETE "${BASE_URL}/api/v1/knowledge/documents/sample_document.md"
