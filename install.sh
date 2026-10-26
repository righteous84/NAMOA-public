#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

INSTALL_DOCKER=0
USE_IMAGE=0

usage() {
  cat <<'EOF'
NAMOA Ubuntu installer

Usage:
  ./install.sh                 Build the image locally and start NAMOA
  ./install.sh --image         Pull the published image and start NAMOA
  ./install.sh --install-docker
                               Install Docker and the Compose plugin with apt,
                               then build locally and start NAMOA

Before the first run:
  cp .env.example .env
  edit .env and set NAMOA_MEDIA_ROOT, PUID, and PGID

The media path is mounted at the same path inside the container, so paths
already recorded in the NAMOA database remain valid.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --install-docker) INSTALL_DOCKER=1 ;;
    --image) USE_IMAGE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage; exit 2 ;;
  esac
done

need_sudo() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

install_docker_if_requested() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    return
  fi

  if [ "$INSTALL_DOCKER" -ne 1 ]; then
    echo "Docker Engine and the Docker Compose plugin are required." >&2
    echo "Install them, or re-run: ./install.sh --install-docker" >&2
    exit 1
  fi

  if ! command -v apt-get >/dev/null 2>&1; then
    echo "--install-docker supports Ubuntu and Debian systems with apt-get." >&2
    exit 1
  fi

  need_sudo apt-get update
  need_sudo apt-get install -y docker.io docker-compose-v2
  need_sudo systemctl enable --now docker
  need_sudo usermod -aG docker "${USER}" || true

  echo
  echo "Docker was installed. If this shell cannot access Docker yet,"
  echo "log out and back in, then run ./install.sh again."
}

install_docker_if_requested

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not available on PATH." >&2
  exit 1
fi

DOCKER=(docker)

if ! docker info >/dev/null 2>&1; then
  if command -v sudo >/dev/null 2>&1 && sudo -n docker info >/dev/null 2>&1; then
    DOCKER=(sudo docker)
  else
    echo "Docker is installed but this user cannot access the daemon." >&2
    echo "Add the user to the docker group and log in again, or run with sudo." >&2
    exit 1
  fi
fi

if ! "${DOCKER[@]}" compose version >/dev/null 2>&1; then
  echo "The Docker Compose plugin is not available." >&2
  echo "Install the docker-compose-plugin package and try again." >&2
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  sed -i "s/^PUID=.*/PUID=$(id -u)/" .env
  sed -i "s/^PGID=.*/PGID=$(id -g)/" .env
  echo "Created .env with PUID=$(id -u) and PGID=$(id -g)."
fi

set -a
# shellcheck disable=SC1091
. ./.env
set +a

: "${NAMOA_MEDIA_ROOT:?Set NAMOA_MEDIA_ROOT in .env}"

if [ ! -d "$NAMOA_MEDIA_ROOT" ]; then
  echo "Media root does not exist: $NAMOA_MEDIA_ROOT" >&2
  echo "Edit .env and set NAMOA_MEDIA_ROOT to your media library path." >&2
  exit 1
fi

mkdir -p "$NAMOA_DATA_DIR" "$NAMOA_CONFIG_DIR" "$NAMOA_LOG_DIR"

if [ "$USE_IMAGE" -eq 1 ]; then
  "${DOCKER[@]}" compose pull
  "${DOCKER[@]}" compose up -d --no-build
else
  "${DOCKER[@]}" compose up -d --build
fi

echo
echo "NAMOA is starting."
echo "Open: http://localhost:${NAMOA_PORT:-8080}"
echo "Data: ${NAMOA_DATA_DIR}"
echo "Config: ${NAMOA_CONFIG_DIR}"
echo "Logs: ${NAMOA_LOG_DIR}"
echo "Media: ${NAMOA_MEDIA_ROOT}"
echo
echo "The GUI has no built-in authentication. Keep it on a trusted network"
echo "or put it behind an authenticated reverse proxy."
