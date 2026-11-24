# NSAT Messenger encrypted backup runbook

## Security model and current status

- PostgreSQL and uploaded media are streamed through `age` encryption before a
  backup artifact is written. The host stores only `.age` artifacts plus
  checksums. Encryption uses a public recipient; the matching private identity
  must stay offline and must never be committed, added to `.env.prod`, or
  uploaded beside the backups.
- Configure a private Google Drive folder through `rclone`, then set
  `BACKUP_REMOTE=gdrive:nsat-messenger-backups`. Drive receives ciphertext only.
- The production `.env.prod` must contain `BACKUP_AGE_RECIPIENT=age1...`.
  This public value is not a secret. Keep the private identity on an offline
  recovery device and a second protected recovery copy.
- A remote is not active until an encrypted database and media pair is
  uploaded and decrypted/restored successfully in an isolated drill.
- Local scheduling depends on the logged-in macOS user session and Docker
  Desktop. It is not an independent offsite service and does not protect from
  loss of this iMac. Remote upload is required for offsite recovery.

## Configure encryption and Drive

1. Install dependencies: `brew install age rclone`.
2. On a trusted offline device, run `age-keygen -o nsat-backup-identity.txt`.
   Record the public `age1...` recipient shown by the command. Protect the
   identity with a strong device password and keep a second offline copy.
3. Add only the public recipient and private Drive remote path to `.env.prod`:

   ```dotenv
   BACKUP_AGE_RECIPIENT=age1...
   BACKUP_REMOTE=gdrive:nsat-messenger-backups
   ```

4. Run `rclone config` to authorize a private Drive remote and choose the
   narrowest Drive scope offered (prefer `drive.file` for a dedicated backup
   folder). Protect the rclone config file (`chmod 600
   ~/.config/rclone/rclone.conf`) and do not commit it. Encrypt the config with
   `rclone config password`, then use Keychain Access to create a generic
   password whose service is `org.satoshicore.nsat-backup-rclone` and whose
   password is the rclone config passphrase. Set
   `BACKUP_RCLONE_KEYCHAIN_SERVICE=org.satoshicore.nsat-backup-rclone` in
   `.env.prod`. The script retrieves it at runtime; the passphrase is not put
   in the LaunchAgent plist or repository.
5. Run `BACKUP_MEDIA_NOW=1 bash deploy/backup.sh`. Confirm that only encrypted
   `.age` files and `.sha256` files appear locally and in the private Drive
   folder. Check local file mode is `600` and parent directory mode is `700`.
6. Install the daily macOS user LaunchAgent only after step 5:

   ```bash
   bash deploy/install-backup-launch-agent.sh
   launchctl print "gui/$(id -u)/org.satoshicore.nsat-messenger-backup"
   ```

The job runs at 03:15 local time. It cannot run while the user is logged out or
Docker Desktop is unavailable. Review `~/backups/logs/backup-error.log` after
each run. Configure a separate alert for missing daily artifacts; local logs
alone do not alert on a failed host.

## Restore drill (never restore over production)

Use an isolated staging database and media directory on an encrypted volume.
This drill temporarily produces plaintext, so set restrictive permissions and
remove the staging database and temporary directory when done. SSD deletion is
not guaranteed to securely overwrite blocks.

1. Download the `.age` files and `.sha256` manifest from Drive. Verify the
   ciphertext checksums in the directory containing the files:

   ```bash
   shasum -a 256 -c nsat-messenger-<timestamp>.sha256
   ```

2. Check the encrypted database archive is readable by the private identity:

   ```bash
   age -d -i /offline/path/nsat-backup-identity.txt \
     nsat-messenger-db-<timestamp>.dump.age | pg_restore --list -
   ```

3. Restore into an isolated PostgreSQL staging database (substitute the
   staging Compose project and database; do not use `nsat-mhtalk-prod` here):

   ```bash
   age -d -i /offline/path/nsat-backup-identity.txt \
     nsat-messenger-db-<timestamp>.dump.age \
     | docker compose -p nsat-restore-drill exec -T db \
         pg_restore -U <staging-user> -d <empty-staging-db> --no-owner --exit-on-error
   ```

4. Inspect schema and expected core tables in that staging database. Decrypt
   media only into a temporary directory on an encrypted volume and verify
   archive extraction and representative file checksums:

   ```bash
   install -d -m 700 /Volumes/EncryptedScratch/nsat-media-restore
   age -d -i /offline/path/nsat-backup-identity.txt \
     nsat-messenger-media-<timestamp>.tar.gz.age \
     | tar xzf - -C /Volumes/EncryptedScratch/nsat-media-restore
   ```

5. Record restore time, database version/count checks, media checks and any
   missing keys/config. Remove the staging database and plaintext directory.
   Keep the private identity separate and test that the recovery copy works.

## Existing local backups

The previously created `.dump`, `.sql.gz`, and `.tar.gz` files are not age
encrypted. Their local permissions were tightened to owner-only and the parent
directory to `700`; FileVault is enabled on this iMac. They are not uploaded by
the new script. Delete them only after at least one encrypted offsite backup
and a successful restore drill are confirmed.
