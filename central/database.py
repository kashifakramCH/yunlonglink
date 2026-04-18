from sqlalchemy import create_engine, Column, String, Integer, BigInteger, Boolean, DateTime, Enum, ForeignKey, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import uuid, enum, os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./yunlonglink.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class PackageType(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    BLOCKED = "blocked"      # quota exhausted
    SUSPENDED = "suspended"  # manually suspended by admin
    PENDING = "pending"      # awaiting first activation


class User(Base):
    __tablename__ = "users"
    id               = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username         = Column(String, unique=True, nullable=False)
    email            = Column(String, unique=True, nullable=False)
    hashed_password  = Column(String, nullable=False)
    xray_uuid        = Column(String, default=lambda: str(uuid.uuid4()))
    status           = Column(Enum(UserStatus), default=UserStatus.PENDING)
    created_at       = Column(DateTime, default=datetime.utcnow)
    notes            = Column(String, default="")

    package_id           = Column(String, ForeignKey("packages.id"), nullable=True)
    package              = relationship("Package", back_populates="users")
    usage_records        = relationship("UsageRecord", back_populates="user")
    current_period_start = Column(DateTime, nullable=True)
    current_period_end   = Column(DateTime, nullable=True)
    bytes_used_current   = Column(BigInteger, default=0)


class Package(Base):
    __tablename__ = "packages"
    id               = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name             = Column(String, nullable=False)
    package_type     = Column(Enum(PackageType), nullable=False)
    data_limit_bytes = Column(BigInteger, nullable=False)
    price            = Column(Float, default=0.0)
    duration_days    = Column(Integer, nullable=False)
    is_active        = Column(Boolean, default=True)
    users            = relationship("User", back_populates="package")


class UsageRecord(Base):
    __tablename__ = "usage_records"
    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id     = Column(String, ForeignKey("users.id"))
    node_id     = Column(String)
    bytes_up    = Column(BigInteger, default=0)
    bytes_down  = Column(BigInteger, default=0)
    recorded_at = Column(DateTime, default=datetime.utcnow)
    user        = relationship("User", back_populates="usage_records")


class VPCNode(Base):
    __tablename__ = "vpc_nodes"
    id                  = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name                = Column(String, nullable=False)
    host                = Column(String, nullable=False)
    port                = Column(Integer, default=443)
    api_port            = Column(Integer, default=8080)
    api_secret          = Column(String, nullable=False)
    is_active           = Column(Boolean, default=True)
    reality_public_key  = Column(String, nullable=True)
    reality_short_id    = Column(String, nullable=True)
    reality_server_name = Column(String, default="www.microsoft.com")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    print("Database initialized.")
