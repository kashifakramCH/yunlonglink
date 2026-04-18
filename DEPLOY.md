# YunLongLink — Deployment Guide

## Architecture

```
Clients (v2rayNG / Shadowrocket / Nekoray)
    │
    ├─ HTTPS ──► Central Server (api.yunlonglink.com)
    │               ├─ FastAPI + SQLite
    │               ├─ Admin UI  (/ui)
    │               ├─ REST API  (/admin/*, /client/*, /node/*)
    │               ├─ nginx (TLS termination + rate limiting)
    │               └─ quota-cron (60-second expiry check)
    │
    └─ VLESS+Reality ──► VPC Nodes (any region)
                            ├─ xray-core (port 443)
                            └─ node_agent (port 8080, central-only)
```

---

## Step 1 — Central Server

Pick any Ubuntu 22.04 VPS (Hetzner CX22 ~$4/mo is fine for the control plane).

### 1.1 Install Docker

```bash
curl -fsSL https://get.docker.com | bash
```

### 1.2 Clone and configure

```bash
git clone https://github.com/kashifakramCH/yunlonglink.git
cd yunlonglink/central

cp .env.example .env
nano .env
```

Fill in all three secrets in `.env`:

```env
ADMIN_SECRET=<long random string>       # protects /admin/* REST endpoints and admin UI login
NODE_API_SECRET=<long random string>    # optional shared fallback for node usage reports
SECRET_KEY=<long random string>         # signs the admin UI browser session cookie
```

Generate random values with: `openssl rand -hex 32`

### 1.3 Update nginx config

Edit `nginx/default.conf` and replace `api.yunlonglink.com` with your actual domain if different.

### 1.4 Get TLS certificate

Point your domain's DNS A record to this server's IP **first**, then:

```bash
./scripts/setup-ssl.sh api.yunlonglink.com admin@yunlonglink.com
```

On a fresh install, the script boots nginx in temporary HTTP-only mode for the ACME challenge, then restarts it with the full HTTPS config after the certificate is issued.

### 1.5 Start all services

```bash
docker compose up -d
```

Verify everything is running:

```bash
docker compose ps
# api, nginx, certbot, quota-cron should all show "Up"
```

### 1.6 Initialize the database

```bash
docker compose exec api python admin_cli.py init
```

---

## Step 2 — Admin Panel

The web admin panel is available at:

```
https://api.yunlonglink.com/ui
```

Log in with the `ADMIN_SECRET` value from your `.env` file.

### Create packages via the UI

Go to **Packages → New Package** and create your plans, for example:

| Name | Data | Duration | Price |
|---|---|---|---|
| 5GB Daily | 5 GB | 1 day | $2.99 |
| 15GB Monthly | 15 GB | 30 days | $9.99 |
| 50GB Monthly | 50 GB | 30 days | $24.99 |

---

## Step 3 — VPC Nodes (repeat for each server)

Pick a server in the target region. Vultr High Frequency, Hetzner, and DigitalOcean all work well. **Check that the IP is not already blocked** in your target country before buying.

### 3.1 On the node server — generate Reality keys

```bash
# Install Docker
curl -fsSL https://get.docker.com | bash

# Clone project
git clone https://github.com/kashifakramCH/yunlonglink.git
cd yunlonglink/node

# Generate Reality key pair (run once per node)
docker run --rm teddysun/xray xray x25519
# → Private key: <SAVE THIS — goes in config.json only, NEVER share>
# → Public key:  <give this to the admin UI when registering the node>

# Generate a short ID
openssl rand -hex 8
# → e.g. a1b2c3d4
```

### 3.2 Register the node in the admin UI

Go to **Nodes → Add Node** in the admin panel and fill in:

- **Name**: e.g. `US East`
- **Host / IP**: the node's public IP
- **Port**: `443`
- **Agent Port**: `8080`
- **Reality Public Key**: from the `xray x25519` output above
- **Short ID**: from `openssl rand -hex 8`
- **SNI**: leave as `www.microsoft.com` (or any popular HTTPS site)

After saving, a flash message shows the `NODE_ID` and `NODE_SECRET` — **copy these immediately**.
That per-node `NODE_SECRET` is used both for central callbacks to the node and for the node's `/node/usage` reports back to central.

### 3.3 Generate the xray config

On the **central server**, run:

```bash
cd yunlonglink/central
docker compose exec api python admin_cli.py gen-xray-config <NODE_ID_SHORT>
```

Copy the JSON output. On the **node server**, save it:

```bash
nano config/config.json
# Paste the JSON, then replace REPLACE_WITH_PRIVATE_KEY with the actual private key
```

### 3.4 Configure and start the node

```bash
cp .env.example .env
nano .env
```

Set:

```env
CENTRAL_API_URL=https://api.yunlonglink.com
NODE_ID=<from admin UI flash message>
NODE_SECRET=<from admin UI flash message>
```

Start the node:

```bash
docker compose up -d
```

### 3.5 Firewall — critical

```bash
ufw allow 22/tcp                                      # SSH
ufw allow 443/tcp                                     # Xray — public
ufw allow from <CENTRAL_SERVER_IP> to any port 8080   # Agent API — central only
ufw enable
```

The node will now appear as **Online** in the admin panel.

---

## Step 4 — Managing Users

Everything is done through the admin panel at `https://api.yunlonglink.com/ui`.

| Action | Where |
|---|---|
| Create a user | Users → New User |
| Assign package after payment | Users → Actions → Assign Package |
| Renew after next payment | Users → Actions → Renew |
| Suspend a user | Users → Actions → Suspend |
| Reactivate a user | Users → Actions → Unblock |

Quotas are enforced automatically — when a user exhausts their data or their period expires, their account is blocked and access is removed from all nodes within 60 seconds.

---

## Step 5 — Client Connection

When a user's account is active, they get their connection links from:

```
GET https://api.yunlonglink.com/client/{user_id}/links
```

This returns a `vless://` link for every active node. Users import the link into:

- **Android**: v2rayNG
- **iOS**: Shadowrocket
- **Desktop (Windows/Linux/Mac)**: Nekoray or Hiddify

Check connection status and remaining quota:

```
GET https://api.yunlonglink.com/client/{user_id}/status
```

---

## Adding More Nodes Later

Repeat Step 3 on a new server. No changes to the central server are needed — the new node appears automatically in all client link responses as soon as it is registered and enabled.

---

## Monitoring

```bash
# Central server
docker compose logs -f api          # API + UI logs
docker compose logs -f quota-cron   # 60-second expiry checks
docker compose logs -f nginx        # Nginx access/error logs

# Node server
docker compose logs -f xray         # Xray-core logs
docker compose logs -f agent        # Usage reporting + user sync logs
```

---

## Updating

```bash
# Pull latest code and rebuild
git pull
docker compose build --no-cache
docker compose up -d
```

---

## Recommended VPS Providers

| Role | Provider | Notes |
|---|---|---|
| Central server | Hetzner CX22 (~$4/mo) | Low traffic, any region |
| US nodes | Vultr High Frequency (NY/LA) | Clean IPs, low latency |
| EU nodes | Hetzner FSN / HEL | Fast, cheap bandwidth |
| Asia nodes | Vultr Tokyo / Singapore | Good regional connectivity |
| Censored-region nodes | Any unblocked provider | Always test IP before selling access |
