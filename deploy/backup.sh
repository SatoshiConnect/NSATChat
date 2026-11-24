#!/usr/bin/env bash
# Encrypted backups for the NSAT Messenger production Compose stack.
# The database and media streams are encrypted by age before they touch disk.
# Only ciphertext is retained or copied to BACKUP_REMOTE.
set -Eeuo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.prod}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
MEDIA_KEEP="${BACKUP_MEDIA_KEEP:-8}"
PROJECT="${COMPOSE_PROJECT_NAME:-nsat-mhtalk-prod}"
RCLONE_CONFIG="${BACKUP_RCLONE_CONFIG:-${RCLONE_CONFIG:-$HOME/.config/rclone/rclone.conf}}"

env_value() {
  local key="$1" value
  [[ -r "$ENV_FILE" ]] || return 0
  value="$(sed -n "/^${key}=/s/^[^=]*=//p" "$ENV_FILE" | tail -n 1)"
  value="${value%$'\r'}"
  if [[ "$value" == \"*\" ]]; then value="${value#\"}"; value="${value%\"}"; fi
  if [[ "$value" == \'*\' ]]; then value="${value#\'}"; value="${value%\'}"; fi
  printf '%s' "$value"
}

RECIPIENT="${BACKUP_AGE_RECIPIENT:-$(env_value BACKUP_AGE_RECIPIENT)}"
REMOTE="${BACKUP_REMOTE:-$(env_value BACKUP_REMOTE)}"
KEYCHAIN_SERVICE="${BACKUP_RCLONE_KEYCHAIN_SERVICE:-$(env_value BACKUP_RCLONE_KEYCHAIN_SERVICE)}"

fail() { printf '[backup] ERROR: %s\n' "$1" >&2; exit 1; }
log() { printf '[backup %s] %s\n' "$(date '+%F %T %Z')" "$1"; }
sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1";
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1";
  else fail 'Install sha256sum or shasum to create integrity checksums.'; fi
}

[[ "$KEEP_DAYS" =~ ^[1-9][0-9]*$ ]] || fail 'BACKUP_KEEP_DAYS must be a positive integer.'
[[ "$MEDIA_KEEP" =~ ^[1-9][0-9]*$ ]] || fail 'BACKUP_MEDIA_KEEP must be a positive integer.'
[[ -n "$RECIPIENT" ]] || fail 'Set BACKUP_AGE_RECIPIENT to an age public recipient. Refusing to create plaintext backups.'
[[ "$RECIPIENT" =~ ^age1[0-9a-z]+$ ]] || fail 'BACKUP_AGE_RECIPIENT is not a valid age public recipient.'
command -v age >/dev/null 2>&1 || fail 'Install age before running encrypted backups.'
command -v docker >/dev/null 2>&1 || fail 'Docker CLI is required.'
[[ -r "$ENV_FILE" ]] || fail "Cannot read Compose env file: $ENV_FILE"
if [[ -n "$REMOTE" ]]; then command -v rclone >/dev/null 2>&1 || fail 'BACKUP_REMOTE is set but rclone is not installed.'; fi
if [[ -n "$REMOTE" && -z "${RCLONE_CONFIG_PASS:-}" && -n "$KEYCHAIN_SERVICE" ]]; then
  command -v security >/dev/null 2>&1 || fail 'macOS Keychain lookup requested but the security command is unavailable.'
  RCLONE_CONFIG_PASS="$(security find-generic-password -s "$KEYCHAIN_SERVICE" -w 2>/dev/null)" \
    || fail 'Could not retrieve the rclone config passphrase from macOS Keychain.'
  [[ -n "$RCLONE_CONFIG_PASS" ]] || fail 'The Keychain entry for the rclone config is empty.'
  export RCLONE_CONFIG_PASS
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
LOCK_DIR="$BACKUP_DIR/.nsat-messenger-backup.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then fail "Another backup may be running (lock: $LOCK_DIR)."; fi
TMP_DIR=""
cleanup() { [[ -z "$TMP_DIR" ]] || rm -rf "$TMP_DIR"; rm -rf "$LOCK_DIR"; }
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
TMP_DIR="$(mktemp -d "$BACKUP_DIR/.nsat-backup.XXXXXX")"
chmod 700 "$TMP_DIR"

COMPOSE=(docker compose -p "$PROJECT" -f docker-compose.prod.yml -f docker-compose.host-proxy.yml --env-file "$ENV_FILE")
STAMP="$(date +%F-%H%M%S)"
DB_FILE="$BACKUP_DIR/nsat-messenger-db-${STAMP}.dump.age"
DB_PART="$TMP_DIR/$(basename "$DB_FILE").part"

# -Fc is self-describing and supports selective restore. age reads directly
# from the pipe so no unencrypted dump file is written to the backup volume.
"${COMPOSE[@]}" exec -T db sh -c 'pg_dump -Fc --no-owner -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  | age -r "$RECIPIENT" -o "$DB_PART"
[[ -s "$DB_PART" ]] || fail 'Database dump produced an empty encrypted artifact.'
chmod 600 "$DB_PART"
mv "$DB_PART" "$DB_FILE"
log "created encrypted database artifact $(basename "$DB_FILE") ($(du -h "$DB_FILE" | awk '{print $1}'))"

FILES=("$DB_FILE")
if [[ "$(date +%u)" == 7 || "${BACKUP_MEDIA_NOW:-0}" == 1 ]]; then
  MEDIA_FILE="$BACKUP_DIR/nsat-messenger-media-${STAMP}.tar.gz.age"
  MEDIA_PART="$TMP_DIR/$(basename "$MEDIA_FILE").part"
  "${COMPOSE[@]}" exec -T web tar czf - -C /app/media . \
    | age -r "$RECIPIENT" -o "$MEDIA_PART"
  [[ -s "$MEDIA_PART" ]] || fail 'Media archive produced an empty encrypted artifact.'
  chmod 600 "$MEDIA_PART"
  mv "$MEDIA_PART" "$MEDIA_FILE"
  log "created encrypted media artifact $(basename "$MEDIA_FILE") ($(du -h "$MEDIA_FILE" | awk '{print $1}'))"
  FILES+=("$MEDIA_FILE")
fi

# Sidecar contains ciphertext checksums only and can be stored beside the files.
for file in "${FILES[@]}"; do
  digest="$(sha256_file "$file" | awk '{print $1}')"
  printf '%s  %s\n' "$digest" "$(basename "$file")" >> "$TMP_DIR/SHA256SUMS"
done
CHECKSUM_FILE="$BACKUP_DIR/nsat-messenger-${STAMP}.sha256"
mv "$TMP_DIR/SHA256SUMS" "$CHECKSUM_FILE"
chmod 600 "$CHECKSUM_FILE"
FILES+=("$CHECKSUM_FILE")

if [[ -n "$REMOTE" ]]; then
  for file in "${FILES[@]}"; do
    rclone --config "$RCLONE_CONFIG" copyto "$file" "${REMOTE%/}/$(basename "$file")"
  done
  rclone --config "$RCLONE_CONFIG" delete --min-age "${KEEP_DAYS}d" \
    --include 'nsat-messenger-db-*.dump.age' "${REMOTE%/}" \
    >/dev/null
  rclone --config "$RCLONE_CONFIG" delete --min-age "$((MEDIA_KEEP * 7))d" \
    --include 'nsat-messenger-media-*.tar.gz.age' --include 'nsat-messenger-*.sha256' \
    "${REMOTE%/}" >/dev/null
  log 'copied encrypted artifacts to configured remote.'
fi

# Keep the configured number of database artifacts and media snapshots locally.
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'nsat-messenger-db-*.dump.age' -mtime "+$KEEP_DAYS" -delete
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'nsat-messenger-media-*.tar.gz.age' -mtime "+$((MEDIA_KEEP * 7))" -delete
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'nsat-messenger-*.sha256' -mtime "+$((MEDIA_KEEP * 7))" -delete

log 'backup run completed.'
