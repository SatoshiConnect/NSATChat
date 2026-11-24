#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
MOCK_BIN="$TMP/bin"
mkdir -p "$MOCK_BIN"

cat > "$MOCK_BIN/docker" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MOCK_LOG/docker.log"
case "$*" in
  *"exec -T db"*)
    if [[ "${MOCK_DB_FAIL:-0}" == 1 ]]; then printf 'partial-dump'; exit 47; fi
    printf 'synthetic-database-dump' ;;
  *"exec -T web"*) printf 'synthetic-media-archive' ;;
  *) exit 42 ;;
esac
MOCK
cat > "$MOCK_BIN/rclone" <<'MOCK'
#!/usr/bin/env bash
if [[ "$3" == copyto ]]; then
  [[ "$4" == *.age || "$4" == *.sha256 ]] || exit 51
  [[ "$5" == *.age || "$5" == *.sha256 ]] || exit 52
fi
printf '%s\n' "$*" >> "$MOCK_LOG/rclone.log"
MOCK
cat > "$MOCK_BIN/security" <<'MOCK'
#!/usr/bin/env bash
[[ "$1" == find-generic-password ]] || exit 1
printf 'test-only-config-passphrase'
MOCK
cat > "$MOCK_BIN/launchctl" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MOCK_LOG/launchctl.log"
MOCK
chmod 700 "$MOCK_BIN"/*

export PATH="$MOCK_BIN:$PATH"
export MOCK_LOG="$TMP"
export BACKUP_DIR="$TMP/backups"
export BACKUP_MEDIA_NOW=1
export BACKUP_REMOTE=gdrive:test-backups
export BACKUP_RCLONE_CONFIG="$TMP/rclone.conf"
ENV_FILE="$TMP/.env.prod"
touch "$ENV_FILE"

# Exercise real age encryption with an ephemeral test-only identity.
age-keygen -o "$TMP/test-identity.txt" >"$TMP/age-keygen.log" 2>&1
chmod 600 "$TMP/test-identity.txt"
export BACKUP_AGE_RECIPIENT="$(sed -n 's/^# public key: //p' "$TMP/test-identity.txt")"

bash "$ROOT_DIR/deploy/backup.sh" >/dev/null

[[ "$(stat -f '%Lp' "$BACKUP_DIR")" == 700 ]]
[[ "$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'nsat-messenger-db-*.dump.age' | wc -l | tr -d ' ')" == 1 ]]
[[ "$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'nsat-messenger-media-*.tar.gz.age' | wc -l | tr -d ' ')" == 1 ]]
[[ "$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'nsat-messenger-*.sha256' | wc -l | tr -d ' ')" == 1 ]]
while IFS= read -r file; do [[ "$(stat -f '%Lp' "$file")" == 600 ]]; done < <(find "$BACKUP_DIR" -maxdepth 1 -type f)
rg -q -- '-p nsat-mhtalk-prod' "$TMP/docker.log"
rg -q -- 'docker-compose.host-proxy.yml' "$TMP/docker.log"
[[ "$(wc -l < "$TMP/rclone.log" | tr -d ' ')" == 5 ]]
[[ ! -e "$BACKUP_DIR/.nsat-messenger-backup.lock" ]]
DB_ARTIFACT="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'nsat-messenger-db-*.dump.age' -print -quit)"
MEDIA_ARTIFACT="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'nsat-messenger-media-*.tar.gz.age' -print -quit)"
[[ "$(age -d -i "$TMP/test-identity.txt" "$DB_ARTIFACT")" == 'synthetic-database-dump' ]]
[[ "$(age -d -i "$TMP/test-identity.txt" "$MEDIA_ARTIFACT")" == 'synthetic-media-archive' ]]
(cd "$BACKUP_DIR" && shasum -a 256 -c "$(basename "$(find "$BACKUP_DIR" -maxdepth 1 -name 'nsat-messenger-*.sha256' -print -quit)")" >/dev/null)

# The launch-agent installer writes a user-only plist and never embeds the Keychain secret.
printf 'BACKUP_AGE_RECIPIENT=%s\nBACKUP_REMOTE=gdrive:test-backups\nBACKUP_RCLONE_KEYCHAIN_SERVICE=org.satoshicore.nsat-backup-rclone\n' \
  "$BACKUP_AGE_RECIPIENT" > "$ENV_FILE"
FAKE_HOME="$TMP/fakehome"
ENV_FILE="$ENV_FILE" HOME="$FAKE_HOME" BACKUP_DIR="$BACKUP_DIR" \
  bash "$ROOT_DIR/deploy/install-backup-launch-agent.sh" >/dev/null
PLIST="$FAKE_HOME/Library/LaunchAgents/org.satoshicore.nsat-messenger-backup.plist"
[[ "$(stat -f '%Lp' "$PLIST")" == 600 ]]
python3 - "$PLIST" <<'PY'
import plistlib, sys
with open(sys.argv[1], "rb") as stream:
    value = plistlib.load(stream)
assert value["StartCalendarInterval"] == {"Hour": 3, "Minute": 15}
assert value["EnvironmentVariables"]["BACKUP_RCLONE_KEYCHAIN_SERVICE"] == "org.satoshicore.nsat-backup-rclone"
assert "test-only-config-passphrase" not in str(value)
PY
rg -q 'bootstrap gui/' "$TMP/launchctl.log"

# A failed pg_dump pipeline must not promote a partial ciphertext artifact.
rm -rf "$BACKUP_DIR"
export MOCK_DB_FAIL=1
if bash "$ROOT_DIR/deploy/backup.sh" >"$TMP/partial-dump.out" 2>&1; then
  echo 'Backup unexpectedly succeeded after pg_dump failed.' >&2
  exit 1
fi
[[ ! -e "$BACKUP_DIR/.nsat-messenger-backup.lock" ]]
[[ -z "$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'nsat-messenger-db-*.dump.age' -print -quit)" ]]
unset MOCK_DB_FAIL

# Missing encryption configuration must fail closed before Docker is called.
rm -rf "$BACKUP_DIR"
unset BACKUP_AGE_RECIPIENT
printf 'BACKUP_REMOTE=\n' > "$ENV_FILE"
if bash "$ROOT_DIR/deploy/backup.sh" >"$TMP/no-recipient.out" 2>&1; then
  echo 'Backup unexpectedly succeeded without encryption recipient.' >&2
  exit 1
fi
rg -q 'Refusing to create plaintext backups' "$TMP/no-recipient.out"
[[ ! -e "$BACKUP_DIR" ]]

echo 'backup security smoke tests passed'
