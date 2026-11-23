#!/usr/bin/env bash
# Update the server to the latest code on GitHub, with a health check and an
# automatic rollback.
#
#   cd ~/mhtalk && bash deploy/deploy.sh
#
# GitHub Actions runs this over SSH after the tests pass
# (.github/workflows/deploy.yml). It can also be run by hand.
#
# 1. Tag the images that are running now as ":rollback".
# 2. Pull the new code, build, restart.
# 3. Wait for the backend health check and for the site through Caddy.
# 4. If either fails: go back to the previous commit and images.
#
# Database migrations run on start (deploy/entrypoint.sh) and are not undone
# by a rollback, so keep migrations backward compatible (add columns, don't
# drop or rename them in the same release).
set -euo pipefail

# The braces make bash read the whole script before running it: "git reset"
# below replaces this file while it runs.
{
cd "$(dirname "$0")/.."
BRANCH="${DEPLOY_BRANCH:-main}"
PROJECT="${COMPOSE_PROJECT_NAME:-nsat-mhtalk-prod}"
ENV_FILE=".env.prod"
[ -f "$ENV_FILE" ] || { echo "Missing $ENV_FILE (see docs/DEPLOY_ORACLE.md)"; exit 1; }

env_value() { grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '"' || true; }
DOMAIN="$(env_value DOMAIN)"
TURN_SECRET="$(env_value TURN_SECRET)"
log() { echo "[deploy $(date +%H:%M:%S)] $*"; }

COMPOSE=(docker compose -p "$PROJECT" -f docker-compose.prod.yml --env-file "$ENV_FILE")
TARGET_SERVICES=()
HOST_PROXY_MODE=0
# Preserve the host-proxy deployment mode when the currently running stack was
# started with docker-compose.host-proxy.yml. In that mode the host owns HTTPS;
# backend, scheduler, and host-served frontend bundle should be updated.
EXISTING_WEB="$("${COMPOSE[@]}" ps -q web)"
if [ -n "$EXISTING_WEB" ]; then
  EXISTING_COMPOSE_FILES="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' "$EXISTING_WEB" 2>/dev/null || true)"
  if [[ "$EXISTING_COMPOSE_FILES" == *docker-compose.host-proxy.yml* ]]; then
    COMPOSE+=( -f docker-compose.host-proxy.yml )
    TARGET_SERVICES=(web scheduler)
    HOST_PROXY_MODE=1
    log "Detected host-proxy stack; keeping the host HTTPS proxy in place."
  fi
fi
if [ -n "$TURN_SECRET" ] && [ "$TURN_SECRET" != "change-me-long-random-string" ]; then
  COMPOSE+=(--profile turn)
fi

# Images we build ourselves (web, scheduler, caddy); databases are pinned images.
own_images() { "${COMPOSE[@]}" config --images | grep -vE '^(postgres|redis|coturn)' | sort -u; }

healthy() {
  local web status
  for _ in $(seq 1 40); do
    web="$("${COMPOSE[@]}" ps -q web)"
    status="$(docker inspect -f '{{.State.Health.Status}}' "$web" 2>/dev/null || echo starting)"
    if [ "$status" = "healthy" ]; then
      # And through Caddy, the way users reach it.
      if [ -z "$DOMAIN" ] || [ "$DOMAIN" = "localhost" ]; then
        curl -fsS http://localhost/api/health/ >/dev/null || { sleep 5; continue; }
      else
        curl -fsS --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/api/health/" >/dev/null || { sleep 5; continue; }
      fi
      if [ "$HOST_PROXY_MODE" -eq 1 ]; then
        if [ -z "$DOMAIN" ] || [ "$DOMAIN" = "localhost" ]; then
          curl -fsS http://localhost/ | grep -Eq 'assets/index-[A-Za-z0-9_-]+\.js' || { sleep 5; continue; }
        else
          curl -fsS --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/" \
            | grep -Eq 'assets/index-[A-Za-z0-9_-]+\.js' || { sleep 5; continue; }
        fi
      fi
      return 0
    fi
    sleep 5
  done
  return 1
}

PREVIOUS="$(git rev-parse HEAD)"
log "Current version: ${PREVIOUS:0:7}"

STATIC_DIR="frontend/dist"
STATIC_STAGE="frontend/dist.next"
STATIC_ROLLBACK="frontend/dist.rollback"
STATIC_HAD_PREVIOUS=0
STATIC_SWITCHED=0

restore_image_tags() {
  for image in $(own_images); do
    if docker image inspect "${image%%:*}:rollback" >/dev/null 2>&1; then
      docker tag "${image%%:*}:rollback" "$image"
    fi
  done
}

for image in $(own_images); do
  if docker image inspect "$image" >/dev/null 2>&1; then
    docker tag "$image" "${image%%:*}:rollback"
  fi
done

git fetch --quiet origin "$BRANCH"
git reset --quiet --hard "origin/$BRANCH"   # .env.prod is git-ignored, so it stays
CURRENT="$(git rev-parse HEAD)"
log "New version: ${CURRENT:0:7}"

if [ "$HOST_PROXY_MODE" -eq 1 ]; then
  log "Building frontend for the host Caddy..."
  rm -rf "$STATIC_STAGE"
  if ! (cd frontend && npm ci --no-audit --no-fund && npm run build -- --outDir dist.next --emptyOutDir); then
    rm -rf "$STATIC_STAGE"
    git reset --quiet --hard "$PREVIOUS"
    log "Frontend build failed; the running release was not changed."
    exit 1
  fi
fi

log "Building..."
if ! "${COMPOSE[@]}" build "${TARGET_SERVICES[@]}"; then
  rm -rf "$STATIC_STAGE"
  git reset --quiet --hard "$PREVIOUS"
  restore_image_tags
  log "Container build failed; the running release was not changed."
  exit 1
fi

if [ "$HOST_PROXY_MODE" -eq 1 ]; then
  rm -rf "$STATIC_ROLLBACK"
  if [ -d "$STATIC_DIR" ]; then
    mv "$STATIC_DIR" "$STATIC_ROLLBACK"
    STATIC_HAD_PREVIOUS=1
  fi
  if ! mv "$STATIC_STAGE" "$STATIC_DIR"; then
    if [ "$STATIC_HAD_PREVIOUS" -eq 1 ]; then mv "$STATIC_ROLLBACK" "$STATIC_DIR"; fi
    git reset --quiet --hard "$PREVIOUS"
    restore_image_tags
    log "Could not switch the frontend bundle; restored the prior release."
    exit 1
  fi
  STATIC_SWITCHED=1
fi

log "Starting..."
if ! "${COMPOSE[@]}" up -d --remove-orphans "${TARGET_SERVICES[@]}"; then
  log "Service restart failed. Rolling back to ${PREVIOUS:0:7}..."
  git reset --quiet --hard "$PREVIOUS"
  restore_image_tags
  if [ "$STATIC_SWITCHED" -eq 1 ]; then
    rm -rf "$STATIC_DIR"
    if [ "$STATIC_HAD_PREVIOUS" -eq 1 ]; then mv "$STATIC_ROLLBACK" "$STATIC_DIR"; fi
  fi
  "${COMPOSE[@]}" up -d --no-build --remove-orphans "${TARGET_SERVICES[@]}" || true
  exit 1
fi

if healthy; then
  log "Healthy. Deployed ${CURRENT:0:7}."
  if [ "$STATIC_HAD_PREVIOUS" -eq 1 ]; then rm -rf "$STATIC_ROLLBACK"; fi
  docker image prune -f >/dev/null || true
  exit 0
fi

log "Health check FAILED. Rolling back to ${PREVIOUS:0:7}..."
"${COMPOSE[@]}" logs --tail 80 web || true
git reset --quiet --hard "$PREVIOUS"
restore_image_tags
if [ "$STATIC_SWITCHED" -eq 1 ]; then
  rm -rf "$STATIC_DIR"
  if [ "$STATIC_HAD_PREVIOUS" -eq 1 ]; then mv "$STATIC_ROLLBACK" "$STATIC_DIR"; fi
fi
"${COMPOSE[@]}" up -d --no-build --remove-orphans "${TARGET_SERVICES[@]}"
if healthy; then
  log "Rolled back to ${PREVIOUS:0:7}; the site is up."
else
  log "Rollback is not healthy either. Check: docker compose -f docker-compose.prod.yml logs web"
fi
exit 1
}
