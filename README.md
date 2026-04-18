# YunLongLink

High-performance, censorship-resistant VPN service powered by **Xray-core** with **VLESS + Reality** protocol. Built for commercial deployment with multi-region node management, automated data quota enforcement, and a web-based admin panel.

---
 
## Feature Set

- **VLESS + Reality protocol** — currently the hardest traffic type for censors to detect and block; camouflages as legitimate TLS to any major website
- **Multi-region nodes** — deploy VPC nodes in any region; clients get links for all active nodes automatically
- **Web admin panel** — manage users, packages, and nodes from a browser at `/ui`
- **Flexible packages** — daily, weekly, monthly, or custom data plans with configurable limits and pricing
- **Automatic quota enforcement** — accounts are blocked when data or time runs out; node access is removed within 60 seconds
- **Admin renewal workflow** — only admins can renew after payment is confirmed
- **Client-ready links** — generates `vless://` deep-links importable into any Xray-compatible client app
- **Fully Dockerized** — spin up a central server and add nodes with `docker compose up`

---

## How It Works

```
Client App  ──VLESS+Reality──►  VPC Node (xray-core)
                                      │
                              Node Agent (reports usage)
                                      │
                              Central Server (FastAPI)
                                      │
                              SQLite Database
                                      │
                              Admin Panel (/ui)
```

1. Admin creates a user and assigns a package via the web panel
2. User gets a `vless://` link from the API and imports it into their client app
3. The node agent reports byte usage to the central server every 60 seconds
4. When quota or period expires, the account is blocked and the user is removed from all nodes
5. Admin renews the account after receiving payment

---

## Tech Stack

| Component | Technology |
|---|---|
| VPN Protocol | Xray-core — VLESS + Reality |
| Backend | Python, FastAPI, SQLAlchemy |
| Database | SQLite |
| Admin UI | Jinja2 templates + Bootstrap 5 |
| Node Agent | FastAPI + httpx + schedule |
| Deployment | Docker, Docker Compose, nginx, Let's Encrypt |

---

## Project Structure

```
yunlonglink/
├── central/                    # Runs once on the control plane server
│   ├── api.py                  # REST API + UI mount point
│   ├── ui_routes.py            # Web admin panel routes
│   ├── controller.py           # Business logic (users, quotas, nodes)
│   ├── database.py             # SQLAlchemy models
│   ├── xray_config.py          # Xray config generator + vless:// link builder
│   ├── admin_cli.py            # CLI tool (alternative to web UI)
│   ├── templates/              # Jinja2 HTML templates
│   │   ├── base.html           # Sidebar layout, dark theme
│   │   ├── login.html          # Admin login page
│   │   ├── dashboard.html      # Stats overview
│   │   ├── users.html          # User management
│   │   ├── packages.html       # Package management
│   │   └── nodes.html          # Node management
│   ├── nginx/default.conf      # nginx with HTTPS + rate limiting
│   ├── scripts/
│   │   ├── setup-ssl.sh        # One-shot Let's Encrypt setup
│   │   └── add-node-full.sh    # Node registration helper
│   ├── Dockerfile
│   ├── docker-compose.yml      # api + nginx + certbot + quota-cron
│   └── requirements.txt
│
└── node/                       # Copied to each VPC node server
    ├── node_agent.py           # Usage reporting + user sync agent
    ├── Dockerfile              # Installs xray-core binary + agent
    ├── docker-compose.yml      # xray + agent (network_mode: host)
    ├── config/                 # config.json lives here (gitignored)
    └── requirements-node.txt
```

---

## Quick Start

See [DEPLOY.md](DEPLOY.md) for the full step-by-step deployment guide.

**Short version:**

```bash
# Central server
git clone https://github.com/kashifakramCH/yunlonglink.git
cd yunlonglink/central
cp .env.example .env && nano .env        # set ADMIN_SECRET, NODE_API_SECRET, SECRET_KEY
./scripts/setup-ssl.sh api.yunlonglink.com admin@yunlonglink.com
docker compose up -d
docker compose exec api python admin_cli.py init

# Admin panel
open https://api.yunlonglink.com/ui
```

---

## Admin Panel

| Page | URL | What you can do |
|---|---|---|
| Dashboard | `/ui/dashboard` | Stats overview, recent users |
| Users | `/ui/users` | Create users, assign packages, renew, suspend |
| Packages | `/ui/packages` | Define data plans with limits and pricing |
| Nodes | `/ui/nodes` | Register VPC nodes, enable/disable |

Login with the `ADMIN_SECRET` value from your `.env` file.

---

## Client Apps

Users import their `vless://` connection link into any Xray-compatible client:

| Platform | App |
|---|---|
| Android | v2rayNG |
| iOS | Shadowrocket |
| Windows / Linux / macOS | Nekoray, Hiddify |

Connection links are served from:
```
GET https://api.yunlonglink.com/client/{user_id}/links
```

---

## REST API

The full API reference is available at:
```
https://api.yunlonglink.com/docs
```

Key endpoints:

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/admin/users` | Create user |
| `POST` | `/admin/users/{id}/assign` | Assign package |
| `POST` | `/admin/users/{id}/renew` | Renew after payment |
| `POST` | `/admin/users/{id}/block` | Suspend user |
| `GET` | `/admin/users` | List all users |
| `POST` | `/admin/packages` | Create package |
| `POST` | `/admin/nodes` | Register node |
| `GET` | `/client/{id}/links` | Get user's vless:// links |
| `GET` | `/client/{id}/status` | Get quota/usage status |
| `POST` | `/node/usage` | Node usage report (internal) |

All `/admin/*` endpoints require the `X-Admin-Secret` header.

---

## License

MIT
