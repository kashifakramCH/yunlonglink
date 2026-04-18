import json


def generate_node_config(
    node_host: str,
    node_port: int,
    private_key: str,
    short_id: str,
    server_name: str = "www.microsoft.com",
    users: list = None,
) -> dict:
    """
    Generate a complete xray-core config.json for a VPC node.
    Uses VLESS inbound + Reality (camouflages as TLS to server_name).
    """
    return {
        "log": {"loglevel": "warning"},
        "api": {
            "tag": "api",
            "services": ["HandlerService", "StatsService", "LoggerService"],
        },
        "stats": {},
        "policy": {
            "levels": {
                "0": {"statsUserUplink": True, "statsUserDownlink": True}
            },
            "system": {
                "statsInboundUplink": True,
                "statsInboundDownlink": True,
            },
        },
        "inbounds": [
            {
                "tag": "vless-in",
                "listen": "0.0.0.0",
                "port": node_port,
                "protocol": "vless",
                "settings": {
                    "clients": users or [],
                    "decryption": "none",
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "realitySettings": {
                        "show": False,
                        "dest": f"{server_name}:443",
                        "xver": 0,
                        "serverNames": [server_name],
                        "privateKey": private_key,
                        "shortIds": [short_id],
                    },
                },
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls"],
                },
            },
            {
                "tag": "api-in",
                "listen": "127.0.0.1",
                "port": 62789,
                "protocol": "dokodemo-door",
                "settings": {"address": "127.0.0.1"},
                "streamSettings": {"network": "tcp"},
            },
        ],
        "outbounds": [
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "blocked", "protocol": "blackhole"},
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [
                {
                    "type": "field",
                    "inboundTag": ["api-in"],
                    "outboundTag": "api",
                },
                {
                    "type": "field",
                    "ip": ["geoip:private"],
                    "outboundTag": "blocked",
                },
            ],
        },
    }


def user_vless_link(
    server: str,
    port: int,
    user_uuid: str,
    public_key: str,
    short_id: str,
    server_name: str = "www.microsoft.com",
    remark: str = "VPN",
) -> str:
    """
    Generates a vless:// deep-link the client app imports directly.
    Compatible with v2rayNG, Shadowrocket, Nekoray, etc.
    """
    params = (
        f"encryption=none"
        f"&security=reality"
        f"&sni={server_name}"
        f"&fp=chrome"
        f"&pbk={public_key}"
        f"&sid={short_id}"
        f"&type=tcp"
        f"&flow=xtls-rprx-vision"
    )
    return f"vless://{user_uuid}@{server}:{port}?{params}#{remark}"


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 5:
        print("Usage: python xray_config.py <host> <port> <private_key> <short_id> [server_name]")
        sys.exit(1)

    host       = sys.argv[1]
    port       = int(sys.argv[2])
    priv_key   = sys.argv[3]
    sid        = sys.argv[4]
    sni        = sys.argv[5] if len(sys.argv) > 5 else "www.microsoft.com"

    cfg = generate_node_config(host, port, priv_key, sid, sni)
    print(json.dumps(cfg, indent=2))
