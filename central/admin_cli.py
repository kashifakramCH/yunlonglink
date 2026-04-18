"""
Admin CLI — run on the server where yunlonglink.db lives.
Usage: python admin_cli.py [command] [args]
       docker compose exec api python admin_cli.py [command] [args]
"""
import typer
import secrets as secrets_module
from rich.table import Table
from rich.console import Console
from database import SessionLocal, init_db, User, Package, VPCNode, PackageType, UserStatus
import controller

app = typer.Typer(help="Yunlong Link Admin CLI")
con = Console()


def get_db():
    return SessionLocal()


@app.command()
def init():
    """Initialize the database tables."""
    init_db()
    con.print("[green]Database initialized.[/green]")


# ─── Packages ────────────────────────────────────────────────────────────────

@app.command("add-package")
def add_package(
    name: str       = typer.Argument(..., help="Package name, e.g. '5GB Daily'"),
    data_gb: float  = typer.Argument(..., help="Data limit in GB"),
    days: int       = typer.Argument(..., help="Duration in days (1=daily, 7=weekly, 30=monthly)"),
    price: float    = typer.Option(0.0, help="Price in USD"),
    pkg_type: str   = typer.Option("custom", help="Type: daily, weekly, monthly, custom"),
):
    """Create a data package."""
    db = get_db()
    try:
        pkg = Package(
            name=name,
            package_type=PackageType(pkg_type),
            data_limit_bytes=int(data_gb * 1024 ** 3),
            duration_days=days,
            price=price,
        )
        db.add(pkg)
        db.commit()
        con.print(f"[green]Package created:[/green] {pkg.id}")
        con.print(f"  Name:     {pkg.name}")
        con.print(f"  Limit:    {data_gb} GB")
        con.print(f"  Duration: {days} days")
        con.print(f"  Price:    ${price:.2f}")
    except Exception as e:
        con.print(f"[red]Error:[/red] {e}")
    finally:
        db.close()


@app.command("list-packages")
def list_packages():
    """List all packages."""
    db = get_db()
    pkgs = db.query(Package).all()
    t = Table("ID (short)", "Name", "Type", "Limit", "Days", "Price", "Active")
    for p in pkgs:
        t.add_row(
            p.id[:8],
            p.name,
            p.package_type,
            f"{p.data_limit_bytes / 1024 ** 3:.1f} GB",
            str(p.duration_days),
            f"${p.price:.2f}",
            "[green]yes[/green]" if p.is_active else "[red]no[/red]",
        )
    con.print(t)
    db.close()


# ─── Users ───────────────────────────────────────────────────────────────────

@app.command("add-user")
def add_user(
    username: str = typer.Argument(...),
    email: str    = typer.Argument(...),
    password: str = typer.Argument(...),
):
    """Create a new user account (status: pending until package assigned)."""
    db = get_db()
    try:
        u = controller.create_user(db, username, email, password)
        con.print(f"[green]User created:[/green] {u.id}")
        con.print(f"  Username: {u.username}")
        con.print(f"  Email:    {u.email}")
        con.print(f"  Status:   {u.status}")
    except Exception as e:
        con.print(f"[red]Error:[/red] {e}")
    finally:
        db.close()


@app.command()
def assign(
    user_id: str    = typer.Argument(..., help="User ID (full or first 8 chars)"),
    package_id: str = typer.Argument(..., help="Package ID (full or first 8 chars)"),
):
    """Assign a package to a user — activates their account."""
    db = get_db()
    try:
        # Support short IDs
        if len(user_id) < 36:
            user = db.query(User).filter(User.id.startswith(user_id)).first()
            if not user:
                con.print(f"[red]User not found:[/red] {user_id}")
                return
            user_id = user.id

        if len(package_id) < 36:
            pkg = db.query(Package).filter(Package.id.startswith(package_id)).first()
            if not pkg:
                con.print(f"[red]Package not found:[/red] {package_id}")
                return
            package_id = pkg.id

        u = controller.assign_package(db, user_id, package_id)
        con.print(f"[green]{u.username} activated with package:[/green] {u.package.name}")
        con.print(f"  Period ends: {u.current_period_end}")
    except Exception as e:
        con.print(f"[red]Error:[/red] {e}")
    finally:
        db.close()


@app.command()
def renew(
    user_id: str = typer.Argument(..., help="User ID (full or first 8 chars)"),
):
    """Renew a user's package after payment."""
    db = get_db()
    try:
        if len(user_id) < 36:
            user = db.query(User).filter(User.id.startswith(user_id)).first()
            if not user:
                con.print(f"[red]User not found:[/red] {user_id}")
                return
            user_id = user.id

        u = controller.renew_package(db, user_id)
        con.print(f"[green]{u.username} renewed.[/green] New period ends: {u.current_period_end}")
    except Exception as e:
        con.print(f"[red]Error:[/red] {e}")
    finally:
        db.close()


@app.command()
def block(
    user_id: str = typer.Argument(..., help="User ID (full or first 8 chars)"),
):
    """Manually suspend a user."""
    db = get_db()
    try:
        if len(user_id) < 36:
            user = db.query(User).filter(User.id.startswith(user_id)).first()
            if not user:
                con.print(f"[red]User not found:[/red] {user_id}")
                return
            user_id = user.id

        controller.block_user(db, user_id, UserStatus.SUSPENDED)
        con.print(f"[red]User {user_id[:8]} suspended.[/red]")
    except Exception as e:
        con.print(f"[red]Error:[/red] {e}")
    finally:
        db.close()


@app.command()
def users():
    """List all users with usage stats."""
    db = get_db()
    all_users = db.query(User).all()
    t = Table("ID", "Username", "Status", "Package", "Used", "Quota", "Expires")
    for u in all_users:
        used  = f"{(u.bytes_used_current or 0) / 1024 ** 3:.2f} GB"
        quota = f"{u.package.data_limit_bytes / 1024 ** 3:.1f} GB" if u.package else "-"
        exp   = u.current_period_end.strftime("%Y-%m-%d %H:%M") if u.current_period_end else "-"
        color = "green" if u.status == UserStatus.ACTIVE else "red"
        t.add_row(
            u.id[:8],
            u.username,
            f"[{color}]{u.status}[/{color}]",
            u.package.name if u.package else "-",
            used,
            quota,
            exp,
        )
    con.print(t)
    db.close()


# ─── Nodes ───────────────────────────────────────────────────────────────────

@app.command("add-node")
def add_node(
    name: str       = typer.Argument(..., help="Node display name, e.g. 'US East'"),
    host: str       = typer.Argument(..., help="Public IP or domain of the node"),
    public_key: str = typer.Argument(..., help="Reality public key from xray x25519"),
    short_id: str   = typer.Argument(..., help="Reality short ID from openssl rand -hex 8"),
    port: int       = typer.Option(443, help="Xray listening port"),
    api_port: int   = typer.Option(8080, help="Node agent API port"),
):
    """Register a VPC node with the central server."""
    db = get_db()
    try:
        node = VPCNode(
            name=name,
            host=host,
            port=port,
            api_port=api_port,
            api_secret=secrets_module.token_hex(32),
            reality_public_key=public_key,
            reality_short_id=short_id,
        )
        db.add(node)
        db.commit()
        con.print(f"[green]Node added:[/green] {node.id}")
        con.print(f"  Name:       {node.name}")
        con.print(f"  Host:       {node.host}:{node.port}")
        con.print(f"  Agent port: {node.api_port}")
        con.print(f"\n[bold yellow]Copy these to the node's .env file:[/bold yellow]")
        con.print(f"  NODE_ID={node.id}")
        con.print(f"  NODE_SECRET={node.api_secret}")
    except Exception as e:
        con.print(f"[red]Error:[/red] {e}")
    finally:
        db.close()


@app.command("list-nodes")
def list_nodes():
    """List all registered VPC nodes."""
    db = get_db()
    nodes = db.query(VPCNode).all()
    t = Table("ID", "Name", "Host", "Port", "Agent Port", "Active")
    for n in nodes:
        t.add_row(
            n.id[:8],
            n.name,
            n.host,
            str(n.port),
            str(n.api_port),
            "[green]yes[/green]" if n.is_active else "[red]no[/red]",
        )
    con.print(t)
    db.close()


@app.command("gen-xray-config")
def gen_xray_config(
    node_id: str = typer.Argument(..., help="Node ID (full or first 8 chars)"),
):
    """Print the xray config.json for a registered node (copy to the node server)."""
    import json
    from xray_config import generate_node_config

    db = get_db()
    try:
        if len(node_id) < 36:
            node = db.query(VPCNode).filter(VPCNode.id.startswith(node_id)).first()
        else:
            node = db.query(VPCNode).filter(VPCNode.id == node_id).first()

        if not node:
            con.print(f"[red]Node not found:[/red] {node_id}")
            return

        # Get all active users to pre-populate the config
        active_users = db.query(User).filter(User.status == UserStatus.ACTIVE).all()
        users_list = [
            {"id": u.xray_uuid, "email": u.username, "flow": "xtls-rprx-vision"}
            for u in active_users
        ]

        cfg = generate_node_config(
            node_host=node.host,
            node_port=node.port,
            private_key="REPLACE_WITH_PRIVATE_KEY",
            short_id=node.reality_short_id,
            server_name=node.reality_server_name,
            users=users_list,
        )
        con.print("[yellow]Paste the private key from xray x25519 to replace REPLACE_WITH_PRIVATE_KEY[/yellow]")
        con.print(json.dumps(cfg, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    app()
