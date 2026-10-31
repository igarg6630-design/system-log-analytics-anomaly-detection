"""SQL layer (SQLAlchemy 2.x). Default SQLite, MySQL ke liye SQL_URL badlo."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import SQL_URL


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Upload(Base):
    __tablename__ = "uploads"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    lines_parsed: Mapped[int] = mapped_column(Integer)
    lines_unparsed: Mapped[int] = mapped_column(Integer, default=0)
    first_ts: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_ts: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MinuteStat(Base):
    """Event history: har minute ke counts (trend/charts yahin se)."""
    __tablename__ = "minute_stats"
    id: Mapped[int] = mapped_column(primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"))
    minute: Mapped[datetime] = mapped_column(DateTime)
    total: Mapped[int] = mapped_column(Integer)
    errors: Mapped[int] = mapped_column(Integer)
    warnings: Mapped[int] = mapped_column(Integer)
    unique_ips: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (Index("ix_minute_upload_minute", "upload_id", "minute"),)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), index=True)
    alert_type: Mapped[str] = mapped_column(String(32))          # spike | brute_force
    metric: Mapped[str] = mapped_column(String(32))              # errors | traffic | failed_auth
    window_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    window_end: Mapped[datetime] = mapped_column(DateTime)
    observed: Mapped[float] = mapped_column(Float)
    baseline: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    method: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open|acknowledged|resolved
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


engine = create_engine(
    SQL_URL,
    connect_args={"check_same_thread": False} if SQL_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
