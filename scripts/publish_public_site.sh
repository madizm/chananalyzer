#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

REMOTE_HOST="${REMOTE_HOST:-117.50.199.81}"
REMOTE_USER="${REMOTE_USER:-root}"
REMOTE_BASE_DIR="${REMOTE_BASE_DIR:-/srv/chananalyzer}"

LIMIT="${LIMIT:-0}"
GOOS="${GOOS:-linux}"
GOARCH="${GOARCH:-amd64}"
VERSION="${VERSION:-1}"
INSTALL_SERVICE_FILES="${INSTALL_SERVICE_FILES:-0}"
SKIP_FEEDBACK_BUILD="${SKIP_FEEDBACK_BUILD:-1}"
FEEDBACK_BINARY_NAME="${FEEDBACK_BINARY_NAME:-}"

MIN_AMOUNT="${MIN_AMOUNT:-1}"
MIN_TURNOVER_RATE="${MIN_TURNOVER_RATE:-1}"

usage() {
  cat <<EOF
Usage:
  REMOTE_HOST=117.50.199.81 bash scripts/publish_public_site.sh [options]

Options:
  --remote-host <host>         Override REMOTE_HOST
  --remote-user <user>         Override REMOTE_USER (default: root)
  --remote-base-dir <dir>      Override REMOTE_BASE_DIR (default: /srv/chananalyzer)
  --limit <n>                  Scan/export limit (default: 100, <=0 means all)
  --goos <value>               GOOS for feedback binary (default: linux)
  --goarch <value>             GOARCH for feedback binary (default: amd64)
  --version <value>            Manifest version string (default: 1)
  --install-service-files      Also upload nginx/systemd example files
  --skip-feedback-build        Only publish static site, skip Go binary build
  --help                       Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote-host)
      REMOTE_HOST="$2"
      shift 2
      ;;
    --remote-user)
      REMOTE_USER="$2"
      shift 2
      ;;
    --remote-base-dir)
      REMOTE_BASE_DIR="$2"
      shift 2
      ;;
    --limit)
      LIMIT="$2"
      shift 2
      ;;
    --goos)
      GOOS="$2"
      shift 2
      ;;
    --goarch)
      GOARCH="$2"
      shift 2
      ;;
    --version)
      VERSION="$2"
      shift 2
      ;;
    --install-service-files)
      INSTALL_SERVICE_FILES=1
      shift
      ;;
    --skip-feedback-build)
      SKIP_FEEDBACK_BUILD=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$FEEDBACK_BINARY_NAME" ]]; then
  FEEDBACK_BINARY_NAME="feedback-service-${GOOS}-${GOARCH}"
fi

if [[ -z "$REMOTE_HOST" ]]; then
  echo "REMOTE_HOST is required"
  usage
  exit 1
fi

echo "==> Exporting public scan results"
python "$ROOT_DIR/scripts/export_public_results.py" \
  --output-dir "$ROOT_DIR/dist/publish" \
  --limit "$LIMIT" \
  --min-amount "$MIN_AMOUNT" \
  --min-turnover-rate "$MIN_TURNOVER_RATE" \
  --version "$VERSION" >/dev/null

echo "==> Building release artifacts"
if [[ "$SKIP_FEEDBACK_BUILD" == "1" ]]; then
  python "$ROOT_DIR/scripts/build_public_release.py" \
    --skip-feedback-build \
    --goos "$GOOS" \
    --goarch "$GOARCH"
else
  python "$ROOT_DIR/scripts/build_public_release.py" \
    --goos "$GOOS" \
    --goarch "$GOARCH"
fi

echo "==> Deploying to ${REMOTE_USER}@${REMOTE_HOST}"
REMOTE_HOST="$REMOTE_HOST" \
REMOTE_USER="$REMOTE_USER" \
REMOTE_BASE_DIR="$REMOTE_BASE_DIR" \
FEEDBACK_BINARY_NAME="$FEEDBACK_BINARY_NAME" \
INSTALL_SERVICE_FILES="$INSTALL_SERVICE_FILES" \
bash "$ROOT_DIR/scripts/deploy_public_release.sh"

echo "==> Publish completed"
