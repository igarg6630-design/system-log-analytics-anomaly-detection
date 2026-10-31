"""FastAPI backend - System Log Analytics & Anomaly Detection.

Run:  uvicorn app.main:app --reload     ->  http://127.0.0.1:8000/docs
"""
import io
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config
from .db_sql import Alert, MinuteStat, Upload, get_db, init_db
from .detector import DetectionConfig
from .schemas import AlertOut, AlertStatusUpdate, IngestOut, UploadOut
from .service import IngestError, ingest_upload, reanalyze
from .store import create_store

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    app.state.store = create_store(config.MONGO_URI, config.MONGO_DB, config.MONGO_TIMEOUT_MS)
    yield


app = FastAPI(title="System Log Analytics & Anomaly Detection", version="1.0.0", lifespan=lifespan)


def get_store(request: Request):
    return request.app.state.store


def _get_upload_or_404(db: Session, upload_id: int) -> Upload:
    up = db.get(Upload, upload_id)
    if not up:
        raise HTTPException(404, f"upload {upload_id} nahi mila")
    return up


def _latest_upload_id(db: Session, upload_id: Optional[int]) -> int:
    if upload_id is not None:
        _get_upload_or_404(db, upload_id)
        return upload_id
    last = db.scalar(select(func.max(Upload.id)))
    if last is None:
        raise HTTPException(404, "Abhi koi log upload nahi hua")
    return last


# ---------------- health ----------------
@app.get("/health")
def health(store=Depends(get_store)):
    return {"status": "ok", "log_store": store.kind}


# ---------------- upload & analysis ----------------
@app.post("/logs/upload", response_model=IngestOut)
async def upload_logs(
    file: UploadFile = File(...),
    analyze: bool = True,
    db: Session = Depends(get_db),
    store=Depends(get_store),
):
    raw = await file.read()
    if len(raw) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File {config.MAX_UPLOAD_MB}MB se badi hai")
    if not raw:
        raise HTTPException(400, "File khaali hai")
    try:
        return ingest_upload(db, store, file.filename or "upload.log", raw, analyze=analyze)
    except IngestError as e:
        raise HTTPException(422, str(e))


@app.post("/uploads/{upload_id}/analyze", response_model=list[AlertOut])
def analyze_again(
    upload_id: int,
    z_threshold: float = Query(3.5, gt=0),
    window: int = Query(60, ge=5, le=1440),
    min_errors: int = Query(10, ge=1),
    freq: str = Query("1min", pattern=r"^\d+min$"),
    use_isolation_forest: bool = True,
    bruteforce_threshold: int = Query(20, ge=2),
    db: Session = Depends(get_db),
    store=Depends(get_store),
):
    _get_upload_or_404(db, upload_id)
    cfg = DetectionConfig(freq=freq, window=window, z_threshold=z_threshold, min_errors=min_errors,
                          use_isolation_forest=use_isolation_forest, bruteforce_threshold=bruteforce_threshold)
    try:
        return reanalyze(db, store, upload_id, cfg)
    except IngestError as e:
        raise HTTPException(409, str(e))


@app.get("/uploads", response_model=list[UploadOut])
def list_uploads(db: Session = Depends(get_db)):
    return db.scalars(select(Upload).order_by(Upload.id.desc())).all()


@app.delete("/uploads/{upload_id}", status_code=204)
def delete_upload(upload_id: int, db: Session = Depends(get_db), store=Depends(get_store)):
    up = _get_upload_or_404(db, upload_id)
    # explicit delete (SQLite mein FK cascade default off hota hai)
    db.query(Alert).filter(Alert.upload_id == upload_id).delete()
    db.query(MinuteStat).filter(MinuteStat.upload_id == upload_id).delete()
    db.delete(up)
    db.commit()
    store.delete_upload(upload_id)


# ---------------- search ----------------
@app.get("/logs/search")
def search_logs(
    upload_id: Optional[int] = None,
    level: Optional[str] = None,
    service: Optional[str] = None,
    ip: Optional[str] = None,
    q: Optional[str] = Query(None, description="message mein text search"),
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    limit: int = Query(100, ge=1, le=1000),
    skip: int = Query(0, ge=0),
    store=Depends(get_store),
):
    f = {"upload_id": upload_id, "level": level.upper() if level else None, "service": service,
         "ip": ip, "q": q, "start": start, "end": end}
    total, items = store.search(f, limit=limit, skip=skip)
    return {"total": total, "limit": limit, "skip": skip, "items": items}


# ---------------- alerts ----------------
@app.get("/alerts", response_model=list[AlertOut])
def get_alerts(
    upload_id: Optional[int] = None,
    status: Optional[str] = Query(None, pattern="^(open|acknowledged|resolved)$"),
    severity: Optional[str] = Query(None, pattern="^(low|medium|high|critical)$"),
    alert_type: Optional[str] = Query(None, pattern="^(spike|brute_force)$"),
    since: Optional[datetime] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Alert)
    if upload_id is not None:
        stmt = stmt.where(Alert.upload_id == upload_id)
    if status:
        stmt = stmt.where(Alert.status == status)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    if alert_type:
        stmt = stmt.where(Alert.alert_type == alert_type)
    if since:
        stmt = stmt.where(Alert.window_start >= since)
    return db.scalars(stmt.order_by(Alert.window_start.desc()).limit(limit).offset(offset)).all()


@app.patch("/alerts/{alert_id}", response_model=AlertOut)
def update_alert(alert_id: int, body: AlertStatusUpdate, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "alert nahi mila")
    alert.status = body.status
    db.commit()
    return alert


# ---------------- stats ----------------
def _trend_frame(db: Session, upload_id: int, freq: str) -> pd.DataFrame:
    rows = db.execute(
        select(MinuteStat.minute, MinuteStat.total, MinuteStat.errors, MinuteStat.warnings)
        .where(MinuteStat.upload_id == upload_id).order_by(MinuteStat.minute)
    ).all()
    df = pd.DataFrame(rows, columns=["minute", "total", "errors", "warnings"]).set_index("minute")
    return df if freq == "1min" else df.resample(freq).sum()


@app.get("/stats/error-trend")
def error_trend(
    upload_id: Optional[int] = None,
    freq: str = Query("1min", pattern=r"^\d+(min|h)$"),
    db: Session = Depends(get_db),
):
    uid = _latest_upload_id(db, upload_id)
    df = _trend_frame(db, uid, freq)
    return {
        "upload_id": uid, "freq": freq,
        "points": [{"time": ts.to_pydatetime(), "total": int(r.total), "errors": int(r.errors),
                    "warnings": int(r.warnings)} for ts, r in df.iterrows()],
    }


@app.get("/stats/summary")
def summary(upload_id: Optional[int] = None, db: Session = Depends(get_db), store=Depends(get_store)):
    uid = _latest_upload_id(db, upload_id)
    up = db.get(Upload, uid)
    by_sev = dict(db.execute(select(Alert.severity, func.count()).where(Alert.upload_id == uid)
                             .group_by(Alert.severity)).all())
    by_status = dict(db.execute(select(Alert.status, func.count()).where(Alert.upload_id == uid)
                                .group_by(Alert.status)).all())
    levels = store.level_counts(uid)
    mins = _trend_frame(db, uid, "1min")
    return {
        "upload": UploadOut.model_validate(up),
        "level_counts": levels,
        "error_rate": round((levels.get("ERROR", 0) + levels.get("CRITICAL", 0)) / max(sum(levels.values()), 1), 4),
        "errors_per_min": {"mean": round(float(mins["errors"].mean()), 2), "max": int(mins["errors"].max()),
                           "p95": float(mins["errors"].quantile(0.95))} if len(mins) else {},
        "alerts_by_severity": by_sev,
        "alerts_by_status": by_status,
    }


@app.get("/stats/top-errors")
def top_errors(upload_id: Optional[int] = None, limit: int = Query(10, ge=1, le=100),
               db: Session = Depends(get_db), store=Depends(get_store)):
    uid = _latest_upload_id(db, upload_id)
    return {"upload_id": uid, "items": store.top_messages(uid, limit)}


# ---------------- chart ----------------
@app.get("/charts/error-trend.png")
def chart_error_trend(upload_id: Optional[int] = None, db: Session = Depends(get_db)):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    uid = _latest_upload_id(db, upload_id)
    df = _trend_frame(db, uid, "1min")
    alerts = db.scalars(select(Alert).where(Alert.upload_id == uid)).all()

    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(df.index, df["errors"], lw=1, label="errors/min")
    for i, a in enumerate(alerts):
        ax.axvspan(a.window_start, a.window_end, color="red" if a.alert_type == "spike" else "orange",
                   alpha=0.3, label=a.alert_type if i == 0 or alerts[i - 1].alert_type != a.alert_type else None)
    ax.set_title(f"Error trend (upload {uid})")
    ax.set_ylabel("errors / minute")
    ax.legend(loc="upper left")
    fig.autofmt_xdate()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return Response(buf.getvalue(), media_type="image/png")
