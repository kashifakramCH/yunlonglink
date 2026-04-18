"""
VPN Node Agent — runs on each VPC node alongside xray-core.

Responsibilities:
  1. Poll xray's stats API every 60s and report byte counts to the central server.
  2. Accept add_user / remove_user commands from the central server and
     hot-reload xray by editing config.json + sending SIGHUP.
"""
import os
import json
import subprocess
import threading
import time

import httpx
import schedule
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

# ─── Configuration ────────────────────────────────────────────────────────────

CENTRAL_API   = os.environ["CENTRAL_API_URL"]   # e.g. "https://api.yunlonglink.com"
NODE_ID       = os.environ["NODE_ID"]
NODE_SECRET   = os.environ["NODE_SECRET"]
XRAY_API_PORT = 62789                            # dokodemo-door on 127.0.0.1
CONFIG_PATH   = os.environ.get("XRAY_CONFIG_PATH", "/etc/xray/config.json")
XRAY_BIN      = os.environ.get("XRAY_BIN", "/usr/local/bin/xray")
AGENT_PORT    = int(os.environ.get("AGENT_PORT", "8080"))

app = FastAPI(title="VPN Node Agent")


# ─── Config helpers ───────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def reload_xray():
    """
    Gracefully reload xray config.
    Tries docker SIGHUP first (when docker socket is mounted), then falls
    back to signalling the local process directly.
    """
    try:
        result = subprocess.run(
            ["docker", "kill", "--signal=SIGHUP", "vpn-xray"],
            capture_output=True, timeout=5,
        )
        if result.returncode == 0:
            return
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: find xray PID and send SIGHUP
    try:
        result = subprocess.run(["pgrep", "-x", "xray"], capture_output=True, text=True)
        if result.returncode == 0:
            pid = int(result.stdout.strip().splitlines()[0])
            os.kill(pid, 1)  # SIGHUP
    except Exception as e:
        print(f"[agent] reload_xray failed: {e}")


# ─── Stats collection & usage reporting ──────────────────────────────────────

def get_xray_stats() -> list[dict]:
    """
    Query xray's built-in stats API and return per-user byte counts.
    Uses the xray CLI stats command against the management API port.
    -reset=true clears counters after reading so we report deltas.
    """
    try:
        result = subprocess.run(
            [
                XRAY_BIN, "api", "stats",
                f"-server=127.0.0.1:{XRAY_API_PORT}",
                "-pattern=user",
                "-reset=true",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"[agent] xray stats query failed: {e}")
        return []

    stats = []
    lines = result.stdout.strip().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "user>>>" in line and "name:" in line:
            # Format: name: user>>>email>>>traffic>>>uplink
            name_part = line.replace("name:", "").strip()
            parts = name_part.split(">>>")
            if len(parts) >= 4:
                email     = parts[1]
                direction = parts[3]  # "uplink" or "downlink"
                value_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
                try:
                    val = int(value_line.replace("value:", "").strip())
                except ValueError:
                    val = 0
                stats.append({"email": email, "direction": direction, "bytes": val})
                i += 2
                continue
        i += 1
    return stats


def report_usage_job():
    stats = get_xray_stats()
    by_email: dict[str, dict] = {}
    for s in stats:
        e = s["email"]
        if e not in by_email:
            by_email[e] = {"bytes_up": 0, "bytes_down": 0}
        if s["direction"] == "uplink":
            by_email[e]["bytes_up"] += s["bytes"]
        else:
            by_email[e]["bytes_down"] += s["bytes"]

    with httpx.Client(timeout=10) as client:
        for email, data in by_email.items():
            if data["bytes_up"] + data["bytes_down"] == 0:
                continue
            try:
                resp = client.post(
                    f"{CENTRAL_API}/node/usage",
                    json={**data, "user_email": email, "node_id": NODE_ID},
                    headers={"X-Secret": NODE_SECRET},
                )
                result = resp.json()
                # Central says this user is blocked — remove them immediately
                if result.get("status") in ("blocked", "suspended"):
                    print(f"[agent] Removing blocked user: {email}")
                    _remove_user_from_config(email)
            except Exception as e:
                print(f"[agent] Usage report failed for {email}: {e}")


# ─── Config mutation helpers ──────────────────────────────────────────────────

def _remove_user_from_config(email: str):
    cfg = load_config()
    clients = cfg["inbounds"][0]["settings"]["clients"]
    cfg["inbounds"][0]["settings"]["clients"] = [
        c for c in clients if c.get("email") != email
    ]
    save_config(cfg)
    reload_xray()


def _remove_user_from_config_by_uuid(user_uuid: str):
    cfg = load_config()
    clients = cfg["inbounds"][0]["settings"]["clients"]
    cfg["inbounds"][0]["settings"]["clients"] = [
        c for c in clients if c.get("id") != user_uuid
    ]
    save_config(cfg)
    reload_xray()


# ─── Agent API endpoints (called by central server) ──────────────────────────

def _check_secret(x_secret: str):
    if x_secret != NODE_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")


class AddUserReq(BaseModel):
    uuid: str
    email: str


class RemoveUserReq(BaseModel):
    uuid: str


@app.post("/add_user")
def add_user(req: AddUserReq, x_secret: str = Header(...)):
    _check_secret(x_secret)
    cfg = load_config()
    clients = cfg["inbounds"][0]["settings"]["clients"]
    if not any(c.get("id") == req.uuid for c in clients):
        clients.append({
            "id": req.uuid,
            "email": req.email,
            "flow": "xtls-rprx-vision",
        })
        save_config(cfg)
        reload_xray()
        print(f"[agent] Added user: {req.email}")
    return {"ok": True}


@app.post("/remove_user")
def remove_user(req: RemoveUserReq, x_secret: str = Header(...)):
    _check_secret(x_secret)
    _remove_user_from_config_by_uuid(req.uuid)
    print(f"[agent] Removed user UUID: {req.uuid}")
    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True, "node_id": NODE_ID}


# ─── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Start the scheduler in a background thread
    schedule.every(60).seconds.do(report_usage_job)

    def run_scheduler():
        while True:
            schedule.run_pending()
            time.sleep(1)

    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    print(f"[agent] Started. Reporting to {CENTRAL_API} every 60s.")

    # Start the agent HTTP API
    uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT)
