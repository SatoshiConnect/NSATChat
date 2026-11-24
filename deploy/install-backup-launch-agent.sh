#!/usr/bin/env bash
# Install the per-user macOS schedule only after encryption and remote checks.
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.prod}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
RCLONE_CONFIG="${BACKUP_RCLONE_CONFIG:-${RCLONE_CONFIG:-$HOME/.config/rclone/rclone.conf}}"
[[ -r "$ENV_FILE" ]] || { echo "Cannot read $ENV_FILE" >&2; exit 1; }
env_value() {
  local value
  value="$(sed -n "/^$1=/s/^[^=]*=//p" "$ENV_FILE" | tail -n 1)"
  value="${value%$'\r'}"
  value="${value#\"}"; value="${value%\"}"
  value="${value#\'}"; value="${value%\'}"
  printf '%s' "$value"
}
RECIPIENT="$(env_value BACKUP_AGE_RECIPIENT)"
REMOTE="$(env_value BACKUP_REMOTE)"
KEYCHAIN_SERVICE="$(env_value BACKUP_RCLONE_KEYCHAIN_SERVICE)"
[[ "$RECIPIENT" =~ ^age1[0-9a-z]+$ ]] || { echo 'Set a valid public BACKUP_AGE_RECIPIENT first.' >&2; exit 1; }
[[ -n "$REMOTE" ]] || { echo 'Set BACKUP_REMOTE to the private offsite remote first.' >&2; exit 1; }
command -v age >/dev/null 2>&1 || { echo 'Install age first.' >&2; exit 1; }
printf '' | age -r "$RECIPIENT" >/dev/null 2>&1 || { echo 'The age recipient is not usable.' >&2; exit 1; }
command -v rclone >/dev/null 2>&1 || { echo 'Install and configure rclone first.' >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo 'Install Docker Desktop first.' >&2; exit 1; }
if [[ -n "$KEYCHAIN_SERVICE" ]]; then
  command -v security >/dev/null 2>&1 || { echo 'macOS Keychain is unavailable.' >&2; exit 1; }
  export RCLONE_CONFIG_PASS="$(security find-generic-password -s "$KEYCHAIN_SERVICE" -w 2>/dev/null)" \
    || { echo 'Could not retrieve rclone config passphrase from Keychain.' >&2; exit 1; }
fi
rclone --config "$RCLONE_CONFIG" lsd "$REMOTE" >/dev/null

mkdir -p "$BACKUP_DIR" "$HOME/Library/LaunchAgents"
chmod 700 "$BACKUP_DIR"
AGENT_ID="org.satoshicore.nsat-messenger-backup"
PLIST="$HOME/Library/LaunchAgents/$AGENT_ID.plist"
LOG_DIR="$BACKUP_DIR/logs"
mkdir -p "$LOG_DIR"
chmod 700 "$LOG_DIR"
export ROOT_DIR BACKUP_DIR LOG_DIR PLIST RCLONE_CONFIG KEYCHAIN_SERVICE
python3 - <<'PY'
import os
import plistlib

root = os.environ["ROOT_DIR"]
backup = os.environ["BACKUP_DIR"]
logs = os.environ["LOG_DIR"]
plist = {
    "Label": "org.satoshicore.nsat-messenger-backup",
    "ProgramArguments": ["/bin/bash", f"{root}/deploy/backup.sh"],
    "WorkingDirectory": root,
    "StartCalendarInterval": {"Hour": 3, "Minute": 15},
    "RunAtLoad": False,
    "EnvironmentVariables": {
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/Applications/Docker.app/Contents/Resources/bin",
        "BACKUP_DIR": backup,
        "BACKUP_RCLONE_CONFIG": os.environ["RCLONE_CONFIG"],
        "BACKUP_RCLONE_KEYCHAIN_SERVICE": os.environ["KEYCHAIN_SERVICE"],
    },
    "StandardOutPath": f"{logs}/backup.log",
    "StandardErrorPath": f"{logs}/backup-error.log",
}
with open(os.environ["PLIST"], "wb") as target:
    plistlib.dump(plist, target)
os.chmod(os.environ["PLIST"], 0o600)
PY
launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed $PLIST (daily 03:15 local time). It runs only while this user session and Docker Desktop are available."
