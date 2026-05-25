#!/usr/bin/env bash
set -Eeuo pipefail

IMAGE_NAME="${1:-}"
REMOTE_HOST="${2:-}"

log() {
    printf '[%s] %s\n' \
        "$(date '+%H:%M:%S')" \
        "$1"
}

if [[ -z "$IMAGE_NAME" || -z "$REMOTE_HOST" ]]; then
    echo "Usage:"
    echo "  $0 image:tag user@host"
    echo
    echo "Exemple:"
    echo "  $0 u2pitchjami/cutmind:3.0.0 pipo@192.168.50.173"
    exit 1
fi

if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
    log "❌ Image introuvable : $IMAGE_NAME"
    exit 1
fi

log "📦 Export image : $IMAGE_NAME"
log "🚀 Destination : $REMOTE_HOST"

docker save "$IMAGE_NAME" \
| pv \
| gzip \
| ssh "$REMOTE_HOST" \
    "gunzip | docker load"

log "✅ Transfert terminé"