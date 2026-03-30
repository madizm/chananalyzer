#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE_DIR="$ROOT_DIR/dist/site"
RELEASE_DIR="$ROOT_DIR/dist/release"
NGINX_EXAMPLE="$ROOT_DIR/deploy/nginx/chanalyzer-public.conf.example"
SYSTEMD_EXAMPLE="$ROOT_DIR/deploy/systemd/feedback-service.service.example"

REMOTE_HOST="${REMOTE_HOST:-117.50.199.81}"
REMOTE_USER="${REMOTE_USER:-root}"
REMOTE_BASE_DIR="${REMOTE_BASE_DIR:-/srv/chananalyzer}"
REMOTE_SITE_DIR="$REMOTE_BASE_DIR/site"
REMOTE_FEEDBACK_DIR="$REMOTE_BASE_DIR/feedback"
REMOTE_SYSTEMD_DIR="${REMOTE_SYSTEMD_DIR:-/etc/systemd/system}"
FEEDBACK_BINARY_NAME="${FEEDBACK_BINARY_NAME:-feedback-service-linux-amd64}"
INSTALL_SERVICE_FILES="${INSTALL_SERVICE_FILES:-0}"

if [[ -z "$REMOTE_HOST" ]]; then
  echo "REMOTE_HOST is required"
  exit 1
fi

if [[ ! -d "$SITE_DIR" ]]; then
  echo "Missing $SITE_DIR. Run scripts/build_public_release.py first."
  exit 1
fi

SSH_TARGET="${REMOTE_USER}@${REMOTE_HOST}"

ssh "$SSH_TARGET" "mkdir -p '$REMOTE_SITE_DIR' '$REMOTE_FEEDBACK_DIR'"

rsync -av --delete "$SITE_DIR"/ "$SSH_TARGET:$REMOTE_SITE_DIR/"

if [[ -f "$RELEASE_DIR/$FEEDBACK_BINARY_NAME" ]]; then
  rsync -av "$RELEASE_DIR/$FEEDBACK_BINARY_NAME" "$SSH_TARGET:$REMOTE_FEEDBACK_DIR/feedback-service"
  ssh "$SSH_TARGET" "chmod +x '$REMOTE_FEEDBACK_DIR/feedback-service'"
fi

if [[ "$INSTALL_SERVICE_FILES" == "1" ]]; then
  rsync -av "$NGINX_EXAMPLE" "$SSH_TARGET:$REMOTE_BASE_DIR/chanalyzer-public.conf"
  rsync -av "$SYSTEMD_EXAMPLE" "$SSH_TARGET:$REMOTE_SYSTEMD_DIR/feedback-service.service"
  echo "Uploaded nginx and systemd example files. Review paths before enabling them."
fi

echo "Deployment complete."
echo "Site synced to: $REMOTE_SITE_DIR"
if [[ -f "$RELEASE_DIR/$FEEDBACK_BINARY_NAME" ]]; then
  echo "Feedback binary synced to: $REMOTE_FEEDBACK_DIR/feedback-service"
fi
