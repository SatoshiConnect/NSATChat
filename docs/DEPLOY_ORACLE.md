# Deploying SatoshiCore on Oracle Cloud (Always Free), step by step

At the end of this guide SatoshiCore runs on your own Linux server at
`https://chat.satoshicore.org`, with HTTPS, voice/video calls (TURN relay),
push notifications and automatic restarts. It costs nothing, as long as you stay
inside the Always Free limits.

What you will use (all free):

| Piece | Service |
|---|---|
| Server | Oracle Cloud Always Free, Ampere A1 VM (2 OCPU, 12 GB RAM, Ubuntu 24.04 Arm) |
| Domain | DuckDNS sub-domain (`yourname.duckdns.org`) |
| HTTPS | Caddy (inside the stack), automatic Let's Encrypt certificate |
| Code | GitHub repository |

> **Limits to respect.** The Always Free Ampere A1 allowance is **2 OCPU and 12 GB
> memory in total** (it was 4/24 before mid-2026). Never create A1 machines that
> add up to more than that. If you do, Oracle disables *all* A1 machines when the
> trial ends.

---

## Step 0. Put the code on GitHub

The server downloads the code from GitHub.

1. Install **GitHub Desktop** (https://desktop.github.com) and sign in.
2. *File → Add local repository →* `D:\Projects\Django\MHTalk`.
3. Check the list of changed files. **`.env`, `*.sqlite3`, `sqlite_backup.json`
   and `media/` must NOT appear** (they are git-ignored). If one does, stop and fix
   `.gitignore` first.
4. Write a summary such as "Production-ready SatoshiCore", then click **Commit**, then **Push origin**.

## Step 1. Create the Oracle Cloud account

1. Go to https://www.oracle.com/cloud/free/ and click **Start for free**.
2. **Home region:** pick one close to your users that has Arm capacity, for example
   *UAE East (Dubai)* or *India West (Mumbai)*. **It can never be changed later.**
3. Verify your phone number and add a card. Oracle uses the card to verify you
   and says it does not charge it for Always Free resources. Oracle places a
   small temporary hold (about $1) that the bank releases in a few days.
4. Wait for the "account is ready" email (it can take from minutes to a few hours).

## Step 2. Create the server (VM)

1. Console → ☰ → **Compute → Instances → Create instance**.
2. **Name:** `mhtalk`.
3. **Image:** *Change image →* **Canonical Ubuntu 24.04** (the *aarch64* build is chosen automatically for Arm).
4. **Shape:** *Change shape → Ampere →* **VM.Standard.A1.Flex**, **2 OCPU, 12 GB** memory.
5. **Networking:** keep "Create new virtual cloud network" and **Assign a public IPv4 address = Yes**.
6. **SSH keys:** *Generate a key pair for me →* **Save private key**. Keep the
   `.key` file safe; it is the only way into the server.
7. **Boot volume:** the default 50 GB is fine (Always Free includes 200 GB in total).
8. Click **Create**. If you see *"Out of capacity"*, try a different
   Availability Domain or try again later. Capacity frees up during the day.
9. When the state is **Running**, copy the **Public IP address**.

## Step 3. Open the firewall (two places)

**A. Oracle network (security list).** Instance page → *Primary VNIC → Subnet →
Security → Default Security List → Add Ingress Rules*. Use source `0.0.0.0/0` for each rule:

| Protocol | Destination port | Why |
|---|---|---|
| TCP | 80 | HTTP (certificate check + redirect) |
| TCP | 443 | HTTPS / WebSockets |
| UDP | 443 | HTTP/3 |
| TCP + UDP | 3478 | TURN (calls) |
| UDP | 49160-49200 | TURN relay ports |

**B. Ubuntu firewall.** Run these on the server (Step 5 shows how to connect):

```bash
sudo iptables -I INPUT 6 -p tcp -m multiport --dports 80,443,3478 -j ACCEPT
sudo iptables -I INPUT 6 -p udp -m multiport --dports 443,3478 -j ACCEPT
sudo iptables -I INPUT 6 -p udp --dport 49160:49200 -j ACCEPT
sudo netfilter-persistent save
```

## Step 4. Free domain (DuckDNS)

1. Go to https://www.duckdns.org and sign in (with Google or GitHub).
2. Add the domain you control, such as `chat.satoshicore.org`. In **current ip**, paste the server's public IP and click **update ip**.
3. Point the domain DNS to your server and configure HTTPS for `chat.satoshicore.org`.

## Step 5. Connect to the server

Windows Terminal / PowerShell, in the folder that holds the key:

```powershell
ssh -i .\ssh-key-mhtalk.key ubuntu@<PUBLIC_IP>
```

(If Windows complains about key permissions: right-click the key → Properties →
Security → Advanced → disable inheritance → leave only your user.)

## Step 6. Install Docker and get the code

```bash
sudo apt update && sudo apt -y upgrade
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu && newgrp docker
git clone https://github.com/<github-user>/<repository>.git mhtalk
cd mhtalk
```

## Step 7. Production settings

```bash
cp deploy/env.prod.example .env.prod
python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # use for SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # use for POSTGRES_PASSWORD
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # use for TURN_SECRET
nano .env.prod
```

Fill in your domain everywhere (`DOMAIN`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`,
`CORS_ALLOWED_ORIGINS`, `TURN_URLS`) and the generated secrets. Set
`TURN_EXTERNAL_IP=<public IP>/<private IP>` so calls work through Oracle's NAT
(the private IP is the first address printed by `hostname -I`). Optional:
`SATOSHICORE_AI_API_KEY` (free Gemini key), `GIPHY_API_KEY` (free key from
developers.giphy.com, turns on GIF search) and the push-notification keys
(Step 8). Save with **Ctrl+O**, **Enter**, **Ctrl+X**.

## Step 8. Start everything

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod --profile turn up -d --build
docker compose -f docker-compose.prod.yml --env-file .env.prod ps          # all "running"/"healthy"
docker compose -f docker-compose.prod.yml --env-file .env.prod exec web python manage.py createsuperuser
```

Push notifications (optional): generate keys once, put them in `.env.prod`,
then run the `up -d` command again:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec web python manage.py generate_vapid_keys
```

The first build takes a few minutes. Open `https://chat.satoshicore.org`
and the padlock should appear. Admin: `/admin/`, API docs: `/api/docs/`.

## Step 9. Check it works

- `https://<domain>/api/health/` returns `{"status": "ok", ...}`.
- Register two accounts (phone + laptop) and send messages, photos and voice notes.
- Make a voice call with one phone on **mobile data** (not Wi-Fi). This proves TURN works.
- On the phone: browser menu → **Add to Home screen / Install app**.

## Day-2 operations

| Task | Command (inside `~/mhtalk`) |
|---|---|
| Update to the latest code | `bash deploy/deploy.sh` (build, restart, health check, automatic rollback) |
| Logs | `docker compose -f docker-compose.prod.yml logs -f web` |
| Restart | `docker compose -f docker-compose.prod.yml --env-file .env.prod restart web` |
| Database backup | `docker compose -f docker-compose.prod.yml exec -T db pg_dump -U mhtalk mhtalk > ~/backup-$(date +%F).sql` |

### Encrypted backups

`deploy/backup.sh` targets the production Compose project explicitly
(`nsat-mhtalk-prod`, including `docker-compose.host-proxy.yml`). It writes
PostgreSQL custom-format dumps every run and a full media archive weekly. Both
streams are encrypted with `age` before they are written to the backup
directory. A public recipient is required; without it the script stops rather
than creating a new plaintext backup. Local database retention defaults to 14
days and media retention to 8 weeks. Files and directories are owner-only.

Before enabling a schedule:

1. Install `age` and `rclone` on the host that runs Docker. Generate an age
   identity on a trusted offline device with `age-keygen`; keep the private
   identity in a separate secure offline location. Put only its public
   `age1...` recipient in `BACKUP_AGE_RECIPIENT` in `.env.prod`.
2. Configure a private rclone remote (Google Drive is supported), then set
   `BACKUP_REMOTE=gdrive:nsat-messenger-backups`. Do not use a shared/public
   folder. The remote receives ciphertext and SHA-256 checksums only.
3. Run `BACKUP_MEDIA_NOW=1 bash deploy/backup.sh`. Confirm the resulting files
   end in `.age`, have mode `600`, and were copied to the remote. Do not put the
   private age identity or a plaintext dump in Drive.
4. Perform the restore drill in `docs/operations/SECURE-BACKUPS.md` to a
   separate staging database and temporary media directory before relying on
   these backups.

No schedule or offsite target is considered active until the recipient, remote,
and restore drill are verified. On macOS use the provided LaunchAgent installer
after configuration; it requires the user session and Docker Desktop to be
available. A Linux host can schedule `deploy/backup.sh` with cron or a systemd
timer after the same checks.


### Monitoring and keeping it free

**Uptime monitoring (free):** add `https://<domain>/api/health/` to
https://uptimerobot.com to get an email if the site goes down.

**Idle reclaim:** Oracle may stop an Always Free VM it considers idle: over 7
days, 95th-percentile CPU, network and (on A1) memory all below 20%. A small
app can look idle. Oracle emails first; a stopped VM keeps its disk and can be
started again (Console → Compute → Instances → **Start**). Docker restarts
every service on boot, the uptime monitor tells you when the site is down,
and the off-server backups protect the data either way.

**Keep it at $0:** never click *Upgrade* (to *Pay As You Go*). Without the
upgrade, Oracle can't bill you: when the 30-day trial ends, only Always Free
resources keep running. Create only the one A1 VM described here (2 OCPU, 12 GB,
default boot volume) and add a $1 budget alert (☰ → Billing & Cost Management →
Budgets) so you get an email if anything ever costs money.

**DuckDNS IP:** Oracle keeps the same public IP while the VM exists, so this is
a one-time setting. If you ever recreate the VM, update the IP on duckdns.org.

## Automatic deploys (CD)

After this, every push to `main` deploys itself: GitHub Actions runs the tests
(CI), then SSHes into the server and runs `deploy/deploy.sh`, which builds,
restarts, waits for the health check and **rolls back to the previous version
on its own** if the new one isn't healthy. Workflow: `.github/workflows/deploy.yml`.

1. In the GitHub repository: **Settings → Secrets and variables → Actions**.
2. **Secrets** tab → *New repository secret*, three times:
   - `DEPLOY_HOST`: the server's public IP
   - `DEPLOY_USER`: `ubuntu`
   - `DEPLOY_SSH_KEY`: a private key used only for deploys. Create it on the
     server, authorise it, print it, paste the whole text (from
     `-----BEGIN` to `-----END OPENSSH PRIVATE KEY-----`) into the secret,
     then delete the server copy:
     ```bash
     ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N "" -C github-deploy
     cat ~/.ssh/github_deploy.pub >> ~/.ssh/authorized_keys
     cat ~/.ssh/github_deploy        # copy this into the secret
     rm ~/.ssh/github_deploy
     ```
     The `ubuntu` user must be in the `docker` group (Step 6).
3. **Variables** tab → *New repository variable*, twice:
   - `DEPLOY_ENABLED`: `true`
   - `DEPLOY_URL`: `https://<your domain>`
4. Test it: **Actions → Deploy → Run workflow**. The log ends with
   "Healthy. Deployed …".

Until `DEPLOY_ENABLED` is `true` the Deploy workflow is skipped, so pushing
before the server exists is safe. If a run fails within seconds with
`ssh: no key found`, the key was pasted incompletely; paste it again.
