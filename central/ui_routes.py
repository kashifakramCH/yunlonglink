import os
import secrets as secrets_module
from datetime import datetime

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db, User, Package, VPCNode, UserStatus, PackageType
import controller

router = APIRouter(prefix="/ui", tags=["admin-ui"])
templates = Jinja2Templates(directory="templates")

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "change-me-in-production")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(url=path, status_code=303)


def require_login(request: Request):
    if not request.session.get("admin_logged_in"):
        return redirect("/ui/login")
    return None


def set_flash(request: Request, message: str, category: str = "success"):
    request.session["flash"] = {"message": message, "category": category}


def get_flash(request: Request) -> dict | None:
    flash = request.session.pop("flash", None)
    return flash


def bytes_to_gb(b: int) -> str:
    if b is None:
        return "0.00"
    return f"{b / 1024 ** 3:.2f}"


def pct(used: int, quota: int) -> int:
    if not quota or not used:
        return 0
    return min(int(used / quota * 100), 100)


# ─── Auth ────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get("admin_logged_in"):
        return redirect("/ui/dashboard")
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
def login_submit(request: Request, password: str = Form(...)):
    if password == ADMIN_SECRET:
        request.session["admin_logged_in"] = True
        return redirect("/ui/dashboard")
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Invalid password."},
        status_code=401,
    )


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return redirect("/ui/login")


# ─── Dashboard ───────────────────────────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    guard = require_login(request)
    if guard:
        return guard

    total_users   = db.query(User).count()
    active_users  = db.query(User).filter(User.status == UserStatus.ACTIVE).count()
    blocked_users = db.query(User).filter(
        User.status.in_([UserStatus.BLOCKED, UserStatus.SUSPENDED])
    ).count()
    pending_users = db.query(User).filter(User.status == UserStatus.PENDING).count()
    total_nodes   = db.query(VPCNode).count()
    active_nodes  = db.query(VPCNode).filter(VPCNode.is_active == True).count()
    total_bytes   = db.query(func.sum(User.bytes_used_current)).scalar() or 0

    recent_users = (
        db.query(User)
        .order_by(User.created_at.desc())
        .limit(5)
        .all()
    )

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "flash": get_flash(request),
        "stats": {
            "total_users":   total_users,
            "active_users":  active_users,
            "blocked_users": blocked_users,
            "pending_users": pending_users,
            "total_nodes":   total_nodes,
            "active_nodes":  active_nodes,
            "total_gb":      bytes_to_gb(total_bytes),
        },
        "recent_users": recent_users,
    })


# ─── Users ───────────────────────────────────────────────────────────────────

@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request, db: Session = Depends(get_db)):
    guard = require_login(request)
    if guard:
        return guard

    all_users = db.query(User).order_by(User.created_at.desc()).all()
    packages  = db.query(Package).filter(Package.is_active == True).all()

    user_rows = []
    for u in all_users:
        quota = u.package.data_limit_bytes if u.package else 0
        used  = u.bytes_used_current or 0
        user_rows.append({
            "id":          u.id,
            "username":    u.username,
            "email":       u.email,
            "status":      u.status,
            "package":     u.package.name if u.package else "—",
            "package_id":  u.package_id,
            "used_gb":     bytes_to_gb(used),
            "quota_gb":    bytes_to_gb(quota),
            "pct":         pct(used, quota),
            "period_end":  u.current_period_end.strftime("%Y-%m-%d") if u.current_period_end else "—",
            "created_at":  u.created_at.strftime("%Y-%m-%d") if u.created_at else "—",
        })

    return templates.TemplateResponse("users.html", {
        "request":  request,
        "flash":    get_flash(request),
        "users":    user_rows,
        "packages": packages,
    })


@router.post("/users/create")
def create_user(
    request: Request,
    username: str = Form(...),
    email: str    = Form(...),
    password: str = Form(...),
    db: Session   = Depends(get_db),
):
    guard = require_login(request)
    if guard:
        return guard
    try:
        controller.create_user(db, username, email, password)
        set_flash(request, f"User '{username}' created successfully.")
    except Exception as e:
        set_flash(request, f"Error: {e}", "danger")
    return redirect("/ui/users")


@router.post("/users/{user_id}/assign")
def assign_pkg(
    user_id: str,
    request: Request,
    package_id: str = Form(...),
    db: Session     = Depends(get_db),
):
    guard = require_login(request)
    if guard:
        return guard
    try:
        u = controller.assign_package(db, user_id, package_id)
        set_flash(request, f"Package assigned to {u.username}.")
    except Exception as e:
        set_flash(request, f"Error: {e}", "danger")
    return redirect("/ui/users")


@router.post("/users/{user_id}/renew")
def renew_user(user_id: str, request: Request, db: Session = Depends(get_db)):
    guard = require_login(request)
    if guard:
        return guard
    try:
        u = controller.renew_package(db, user_id)
        set_flash(request, f"{u.username}'s package renewed.")
    except Exception as e:
        set_flash(request, f"Error: {e}", "danger")
    return redirect("/ui/users")


@router.post("/users/{user_id}/block")
def block_user_action(user_id: str, request: Request, db: Session = Depends(get_db)):
    guard = require_login(request)
    if guard:
        return guard
    try:
        u = controller.block_user(db, user_id, UserStatus.SUSPENDED)
        set_flash(request, f"{u.username} has been suspended.", "warning")
    except Exception as e:
        set_flash(request, f"Error: {e}", "danger")
    return redirect("/ui/users")


@router.post("/users/{user_id}/unblock")
def unblock_user(user_id: str, request: Request, db: Session = Depends(get_db)):
    guard = require_login(request)
    if guard:
        return guard
    try:
        u = controller.unblock_user(db, user_id)
        set_flash(request, f"{u.username} has been reactivated.")
    except Exception as e:
        set_flash(request, f"Error: {e}", "danger")
    return redirect("/ui/users")


# ─── Packages ────────────────────────────────────────────────────────────────

@router.get("/packages", response_class=HTMLResponse)
def packages_page(request: Request, db: Session = Depends(get_db)):
    guard = require_login(request)
    if guard:
        return guard

    pkgs = db.query(Package).order_by(Package.name).all()
    pkg_rows = [
        {
            "id":           p.id,
            "name":         p.name,
            "package_type": p.package_type,
            "data_gb":      bytes_to_gb(p.data_limit_bytes),
            "duration":     p.duration_days,
            "price":        f"{p.price:.2f}",
            "is_active":    p.is_active,
            "user_count":   len(p.users),
        }
        for p in pkgs
    ]

    return templates.TemplateResponse("packages.html", {
        "request":  request,
        "flash":    get_flash(request),
        "packages": pkg_rows,
        "pkg_types": [t.value for t in PackageType],
    })


@router.post("/packages/create")
def create_package(
    request: Request,
    name: str          = Form(...),
    package_type: str  = Form(...),
    data_limit_gb: float = Form(...),
    duration_days: int = Form(...),
    price: float       = Form(0.0),
    db: Session        = Depends(get_db),
):
    guard = require_login(request)
    if guard:
        return guard
    try:
        pkg = Package(
            name=name,
            package_type=PackageType(package_type),
            data_limit_bytes=int(data_limit_gb * 1024 ** 3),
            duration_days=duration_days,
            price=price,
        )
        db.add(pkg)
        db.commit()
        set_flash(request, f"Package '{name}' created.")
    except Exception as e:
        set_flash(request, f"Error: {e}", "danger")
    return redirect("/ui/packages")


@router.post("/packages/{pkg_id}/toggle")
def toggle_package(pkg_id: str, request: Request, db: Session = Depends(get_db)):
    guard = require_login(request)
    if guard:
        return guard
    pkg = db.query(Package).filter(Package.id == pkg_id).first()
    if pkg:
        pkg.is_active = not pkg.is_active
        db.commit()
        state = "activated" if pkg.is_active else "deactivated"
        set_flash(request, f"Package '{pkg.name}' {state}.")
    return redirect("/ui/packages")


# ─── Nodes ───────────────────────────────────────────────────────────────────

@router.get("/nodes", response_class=HTMLResponse)
def nodes_page(request: Request, db: Session = Depends(get_db)):
    guard = require_login(request)
    if guard:
        return guard

    nodes = db.query(VPCNode).order_by(VPCNode.name).all()
    node_rows = [
        {
            "id":          n.id,
            "name":        n.name,
            "host":        n.host,
            "port":        n.port,
            "api_port":    n.api_port,
            "is_active":   n.is_active,
            "server_name": n.reality_server_name,
            "short_id":    n.reality_short_id,
        }
        for n in nodes
    ]

    return templates.TemplateResponse("nodes.html", {
        "request": request,
        "flash":   get_flash(request),
        "nodes":   node_rows,
    })


@router.post("/nodes/create")
def create_node(
    request: Request,
    name: str               = Form(...),
    host: str               = Form(...),
    port: int               = Form(443),
    api_port: int           = Form(8080),
    reality_public_key: str = Form(...),
    reality_short_id: str   = Form(...),
    reality_server_name: str = Form("www.microsoft.com"),
    db: Session             = Depends(get_db),
):
    guard = require_login(request)
    if guard:
        return guard
    try:
        node = VPCNode(
            name=name,
            host=host,
            port=port,
            api_port=api_port,
            api_secret=secrets_module.token_hex(32),
            reality_public_key=reality_public_key,
            reality_short_id=reality_short_id,
            reality_server_name=reality_server_name,
        )
        db.add(node)
        db.commit()
        set_flash(
            request,
            f"Node '{name}' added. NODE_ID={node.id} | NODE_SECRET={node.api_secret}",
        )
    except Exception as e:
        set_flash(request, f"Error: {e}", "danger")
    return redirect("/ui/nodes")


@router.post("/nodes/{node_id}/toggle")
def toggle_node(node_id: str, request: Request, db: Session = Depends(get_db)):
    guard = require_login(request)
    if guard:
        return guard
    node = db.query(VPCNode).filter(VPCNode.id == node_id).first()
    if node:
        node.is_active = not node.is_active
        db.commit()
        state = "enabled" if node.is_active else "disabled"
        set_flash(request, f"Node '{node.name}' {state}.")
    return redirect("/ui/nodes")


# ─── Root redirect ────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def ui_root(request: Request):
    return redirect("/ui/dashboard")
