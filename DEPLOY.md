# Yunlong Link — Deployment Guide

## Architecture

```
Clients (v2rayNG / Shadowrocket / Nekoray)
    │
    ├─ HTTPS ──► Central Server (api.yunlonglink.com)
    │               ├─ FastAPI + SQLite
    │               ├─ nginx (TLS termination)
    │               └─ quota-cron (hourly expiry check)
    │
    └─ VLESS+Reality ──► VPC Nodes (any region)
                            ├─ xray-core (port 443)
                            └─ node_agent (port 8080, central-only)
```

---

## Step 1 — Central Server

Pick any Ubuntu 22.04 VPS (Hetzner CX22 ~$4/mo is fine).

```bash
# Install Docker
curl -fsSL https://get.docker.com | bash

# Clone project
git clone https://github.com/yourname/yunlonglink.git
cd yunlonglink/central

# Set secrets
cp .env.example .env
nano .env          # fill in ADMIN_SECRET and NODE_API_SECRET

# Point api.yunlonglink.com DNS A record to this server's IP first, then:
./scripts/setup-ssl.sh api.yunlonglink.com admin@yunlonglink.com

# Start all services
docker compose up -d

# Initialize database and create packages
docker compose exec api python admin_cli.py init
docker compose exec api python admin_cli.py add-package "5GB Daily"    5  1  2.99 daily
docker compose exec api python admin_cli.py add-package "15GB Monthly" 15 30 9.99 monthly
```

---

## Step 2 — VPC Node (repeat for each server)

Pick a server in the desired region. Vultr, Hetzner, DigitalOcean all work.

```bash
# On the NODE server:

# Install Docker
curl -fsSL https://get.docker.com | bash

# Clone project
git clone https://github.com/yourname/yunlonglink.git
cd yunlonglink/node

# Generate Reality key pair
docker run --rm teddysun/xray xray x25519
# → Private key: <SAVE THIS — goes in config.json only, never share>
# → Public key:  <give this to the central server admin>

# Generate a short ID
openssl rand -hex 8
# → e.g. a1b2c3d4
```

Back on the **central server**:

```bash
cd yunlonglink/central

# Register the node — prints NODE_ID and NODE_SECRET
docker compose exec api python admin_cli.py add-node \
  "US East" \
  "NODE_PUBLIC_IP" \
  "PUBLIC_KEY_FROM_ABOVE" \
  "SHORT_ID_FROM_ABOVE"

# Generate xray config.json for the node
docker compose exec api python admin_cli.py gen-xray-config NODE_ID_SHORT
# Copy the JSON output → save as node/config/config.json on the node server
# Replace REPLACE_WITH_PRIVATE_KEY with the actual private key
```

Back on the **node server**:

```bash
# Fill in the .env
cp .env.example .env
nano .env
# Set:
#   CENTRAL_API_URL=https://api.yunlonglink.com
#   NODE_ID=<from add-node output>
#   NODE_SECRET=<from add-node output>

# Paste the generated config.json
nano config/config.json   # replace REPLACE_WITH_PRIVATE_KEY

# Start xray + agent
docker compose up -d

# Firewall — CRITICAL
ufw allow 22/tcp
ufw allow 443/tcp
ufw allow from CENTRAL_SERVER_IP to any port 8080
ufw enable
```

---

## Step 3 — Add users and assign packages

All commands run on the central server:

```bash
alias adm="docker compose -f ~/yunlonglink/central/docker-compose.yml exec api python admin_cli.py"

# Create a user
adm add-user johndoe john@example.com secretpassword

# List packages to get package ID
adm list-packages

# Activate user after payment
adm assign USER_ID_SHORT PACKAGE_ID_SHORT

# Check all users
adm users

# Renew after next payment
adm renew USER_ID_SHORT

# Manually suspend
adm block USER_ID_SHORT
```

---

## Step 4 — Client connection

Clients call this endpoint to get their connection links:

```
GET https://api.yunlonglink.com/client/{user_id}/links
```

Returns `vless://` links for every active node. The user imports these into:
- **Android**: v2rayNG
- **iOS**: Shadowrocket
- **Desktop**: Nekoray or Hiddify

---

## Adding more nodes later

Just repeat Step 2 on a new server. No changes to the central server needed — the new node appears automatically in client link responses.

---

## Monitoring

```bash
# Central server logs
docker compose logs -f api
docker compose logs -f quota-cron

# Node logs
docker compose logs -f xray
docker compose logs -f agent
```
