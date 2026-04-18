from fastapi import FastAPI, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import get_db, User, Package, VPCNode, UserStatus, PackageType, init_db
import controller
import xray_config
import os
import secrets as secrets_module

app = FastAPI(title="Yunlong Link API", version="1.0.0")

ADMIN_SECRET    = os.environ.get("ADMIN_SECRET", "change-me-in-production")
NODE_API_SECRET = os.environ.get("NODE_API_SECRET", "node-secret-change-me")


@app.on_event("startup")
def startup():
    init_db()


# ─── Auth helpers ────────────────────────────────────────────────────────────

def require_admin(x_admin_secret: str = Header(...)):
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid admin secret")


def require_node(x_secret: str = Header(...)):
    if x_secret != NODE_API_SECRET:
        raise HTTPException(status_code=403, detail="Invalid node secret")


# ─── Admin: User management ──────────────────────────────────────────────────

class CreateUserReq(BaseModel):
    username: str
    email: str
    password: str


@app.post("/admin/users", dependencies=[Depends(require_admin)])
def create_user(req: CreateUserReq, db: Session = Depends(get_db)):
    try:
        user = controller.create_user(db, req.username, req.email, req.password)
        return {"id": user.id, "username": user.username, "email": user.email, "status": user.status}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class AssignPackageReq(BaseModel):
    package_id: str


@app.post("/admin/users/{user_id}/assign", dependencies=[Depends(require_admin)])
def assign_package(user_id: str, req: AssignPackageReq, db: Session = Depends(get_db)):
    try:
        user = controller.assign_package(db, user_id, req.package_id)
        return {
            "id": user.id,
            "username": user.username,
            "status": user.status,
            "package": user.package.name if user.package else None,
            "period_end": user.current_period_end,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/admin/users/{user_id}/renew", dependencies=[Depends(require_admin)])
def renew_user(user_id: str, db: Session = Depends(get_db)):
    try:
        user = controller.renew_package(db, user_id)
        return {
            "id": user.id,
            "username": user.username,
            "status": user.status,
            "period_end": user.current_period_end,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/admin/users/{user_id}/block", dependencies=[Depends(require_admin)])
def block_user(user_id: str, db: Session = Depends(get_db)):
    try:
        user = controller.block_user(db, user_id, UserStatus.SUSPENDED)
        return {"id": user.id, "status": user.status}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/admin/users", dependencies=[Depends(require_admin)])
def list_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "status": u.status,
            "package": u.package.name if u.package else None,
            "bytes_used": u.bytes_used_current,
            "quota": u.package.data_limit_bytes if u.package else None,
            "period_end": u.current_period_end,
        }
        for u in users
    ]


@app.get("/admin/users/{user_id}", dependencies=[Depends(require_admin)])
def get_user(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "status": user.status,
        "xray_uuid": user.xray_uuid,
        "package": user.package.name if user.package else None,
        "bytes_used": user.bytes_used_current,
        "quota": user.package.data_limit_bytes if user.package else None,
        "period_start": user.current_period_start,
        "period_end": user.current_period_end,
        "notes": user.notes,
        "created_at": user.created_at,
    }


# ─── Admin: Packages ─────────────────────────────────────────────────────────

class CreatePackageReq(BaseModel):
    name: str
    package_type: PackageType
    data_limit_gb: float
    duration_days: int
    price: float = 0.0


@app.post("/admin/packages", dependencies=[Depends(require_admin)])
def create_package(req: CreatePackageReq, db: Session = Depends(get_db)):
    pkg = Package(
        name=req.name,
        package_type=req.package_type,
        data_limit_bytes=int(req.data_limit_gb * 1024 ** 3),
        duration_days=req.duration_days,
        price=req.price,
    )
    db.add(pkg)
    db.commit()
    db.refresh(pkg)
    return {
        "id": pkg.id,
        "name": pkg.name,
        "type": pkg.package_type,
        "data_limit_gb": req.data_limit_gb,
        "duration_days": pkg.duration_days,
        "price": pkg.price,
    }


@app.get("/admin/packages", dependencies=[Depends(require_admin)])
def list_packages(db: Session = Depends(get_db)):
    pkgs = db.query(Package).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "type": p.package_type,
            "data_limit_gb": round(p.data_limit_bytes / 1024 ** 3, 2),
            "duration_days": p.duration_days,
            "price": p.price,
            "is_active": p.is_active,
        }
        for p in pkgs
    ]


# ─── Admin: VPC nodes ────────────────────────────────────────────────────────

class CreateNodeReq(BaseModel):
    name: str
    host: str
    port: int = 443
    api_port: int = 8080
    reality_public_key: str
    reality_short_id: str
    reality_server_name: str = "www.microsoft.com"


@app.post("/admin/nodes", dependencies=[Depends(require_admin)])
def create_node(req: CreateNodeReq, db: Session = Depends(get_db)):
    node = VPCNode(
        name=req.name,
        host=req.host,
        port=req.port,
        api_port=req.api_port,
        api_secret=secrets_module.token_hex(32),
        reality_public_key=req.reality_public_key,
        reality_short_id=req.reality_short_id,
        reality_server_name=req.reality_server_name,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return {
        "id": node.id,
        "name": node.name,
        "host": node.host,
        "port": node.port,
        "api_port": node.api_port,
        "api_secret": node.api_secret,
        "reality_public_key": node.reality_public_key,
        "reality_short_id": node.reality_short_id,
    }


@app.get("/admin/nodes", dependencies=[Depends(require_admin)])
def list_nodes(db: Session = Depends(get_db)):
    nodes = db.query(VPCNode).all()
    return [
        {
            "id": n.id,
            "name": n.name,
            "host": n.host,
            "port": n.port,
            "is_active": n.is_active,
            "reality_server_name": n.reality_server_name,
        }
        for n in nodes
    ]


@app.patch("/admin/nodes/{node_id}/toggle", dependencies=[Depends(require_admin)])
def toggle_node(node_id: str, db: Session = Depends(get_db)):
    node = db.query(VPCNode).filter(VPCNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    node.is_active = not node.is_active
    db.commit()
    return {"id": node.id, "name": node.name, "is_active": node.is_active}


# ─── Client: get connection links ────────────────────────────────────────────

@app.get("/client/{user_id}/links")
def get_client_links(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=403,
            detail=f"Account is {user.status.value}. Please contact support.",
        )

    nodes = db.query(VPCNode).filter(VPCNode.is_active == True).all()
    links = []
    for node in nodes:
        link = xray_config.user_vless_link(
            server=node.host,
            port=node.port,
            user_uuid=user.xray_uuid,
            public_key=node.reality_public_key,
            short_id=node.reality_short_id,
            server_name=node.reality_server_name,
            remark=f"Yunlong Link-{node.name}",
        )
        links.append({"node": node.name, "link": link})
    return {
        "username": user.username,
        "bytes_used": user.bytes_used_current,
        "quota": user.package.data_limit_bytes if user.package else None,
        "period_end": user.current_period_end,
        "links": links,
    }


@app.get("/client/{user_id}/status")
def get_client_status(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    quota = user.package.data_limit_bytes if user.package else None
    used  = user.bytes_used_current or 0
    return {
        "username": user.username,
        "status": user.status,
        "package": user.package.name if user.package else None,
        "bytes_used": used,
        "bytes_used_gb": round(used / 1024 ** 3, 3),
        "quota_bytes": quota,
        "quota_gb": round(quota / 1024 ** 3, 2) if quota else None,
        "percent_used": round(used / quota * 100, 1) if quota else None,
        "period_end": user.current_period_end,
    }


# ─── Node agent callback: usage reporting ───────────────────────────────────

class UsageReport(BaseModel):
    user_email: str
    bytes_up: int
    bytes_down: int
    node_id: str


@app.post("/node/usage", dependencies=[Depends(require_node)])
def report_usage(report: UsageReport, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == report.user_email).first()
    if not user:
        return {"ok": False, "reason": "user_not_found"}
    controller.record_usage(db, user.id, report.node_id, report.bytes_up, report.bytes_down)
    db.refresh(user)
    return {"ok": True, "status": user.status}


# ─── Health check ────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}
