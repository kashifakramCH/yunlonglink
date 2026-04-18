from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from database import User, Package, UsageRecord, VPCNode, UserStatus
from passlib.context import CryptContext
import httpx
import asyncio

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ─── User management ────────────────────────────────────────────────────────

def _run_node_sync(coro, error_prefix: str):
    try:
        asyncio.run(coro)
    except Exception as e:
        print(f"{error_prefix}: {e}")


def create_user(db: Session, username: str, email: str, password: str) -> User:
    user = User(
        username=username,
        email=email,
        hashed_password=pwd_ctx.hash(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def assign_package(db: Session, user_id: str, package_id: str) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    pkg  = db.query(Package).filter(Package.id == package_id).first()
    if not user or not pkg:
        raise ValueError("User or package not found")

    now = datetime.utcnow()
    user.package_id          = pkg.id
    user.status              = UserStatus.ACTIVE
    user.current_period_start = now
    user.current_period_end   = now + timedelta(days=pkg.duration_days)
    user.bytes_used_current   = 0

    db.commit()
    db.refresh(user)

    _run_node_sync(_push_config_all_nodes(db, user), "[controller] Could not push config to nodes")

    return user


def renew_package(db: Session, user_id: str) -> User:
    """Admin renews after payment. Resets quota and period."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.package:
        raise ValueError("User has no package assigned")

    now = datetime.utcnow()
    user.status               = UserStatus.ACTIVE
    user.current_period_start = now
    user.current_period_end   = now + timedelta(days=user.package.duration_days)
    user.bytes_used_current   = 0

    db.commit()
    db.refresh(user)

    _run_node_sync(_push_config_all_nodes(db, user), "[controller] Could not push config to nodes")

    return user


def unblock_user(db: Session, user_id: str) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError("User not found")
    user.status = UserStatus.ACTIVE
    db.commit()
    _run_node_sync(
        _push_config_all_nodes(db, user),
        "[controller] Could not push config to nodes on unblock",
    )
    return user


def block_user(db: Session, user_id: str, reason: UserStatus = UserStatus.BLOCKED) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError("User not found")
    user.status = reason
    db.commit()

    _run_node_sync(_remove_user_all_nodes(db, user), "[controller] Could not remove user from nodes")

    return user


# ─── Quota enforcement ───────────────────────────────────────────────────────

def record_usage(db: Session, user_id: str, node_id: str, bytes_up: int, bytes_down: int):
    """Called by node agents via the API to report usage."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return

    total = bytes_up + bytes_down
    user.bytes_used_current = (user.bytes_used_current or 0) + total

    rec = UsageRecord(
        user_id=user_id,
        node_id=node_id,
        bytes_up=bytes_up,
        bytes_down=bytes_down,
    )
    db.add(rec)

    should_block = False

    if user.package and user.bytes_used_current >= user.package.data_limit_bytes:
        user.status = UserStatus.BLOCKED
        should_block = True

    if user.current_period_end and datetime.utcnow() > user.current_period_end:
        user.status = UserStatus.BLOCKED
        should_block = True

    db.commit()

    if should_block:
        _run_node_sync(
            _remove_user_all_nodes(db, user),
            "[controller] Could not remove user after quota exceeded",
        )


def check_all_expiries(db: Session):
    """Run periodically (every minute) to catch expired periods."""
    now = datetime.utcnow()
    expired = db.query(User).filter(
        User.status == UserStatus.ACTIVE,
        User.current_period_end < now,
    ).all()
    for user in expired:
        user.status = UserStatus.BLOCKED
    db.commit()
    if expired:
        _run_node_sync(
            _remove_users_all_nodes(db, expired),
            "[controller] Could not remove expired users from nodes",
        )
        print(f"[quota] Blocked {len(expired)} expired users")


# ─── Node communication ──────────────────────────────────────────────────────

async def _push_config_all_nodes(db: Session, user: User):
    nodes = db.query(VPCNode).filter(VPCNode.is_active == True).all()
    if not nodes:
        return
    async with httpx.AsyncClient(timeout=10) as client:
        for node in nodes:
            try:
                await client.post(
                    f"http://{node.host}:{node.api_port}/add_user",
                    json={"uuid": user.xray_uuid, "email": user.username},
                    headers={"X-Secret": node.api_secret},
                )
            except Exception as e:
                print(f"[node] Failed to push to {node.name}: {e}")


async def _remove_user_all_nodes(db: Session, user: User):
    await _remove_users_all_nodes(db, [user])


async def _remove_users_all_nodes(db: Session, users: list[User]):
    nodes = db.query(VPCNode).filter(VPCNode.is_active == True).all()
    if not nodes or not users:
        return
    async with httpx.AsyncClient(timeout=10) as client:
        for user in users:
            for node in nodes:
                try:
                    await client.post(
                        f"http://{node.host}:{node.api_port}/remove_user",
                        json={"uuid": user.xray_uuid},
                        headers={"X-Secret": node.api_secret},
                    )
                except Exception as e:
                    print(f"[node] Failed to remove {user.username} from {node.name}: {e}")
