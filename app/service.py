"""Pipeline: upload -> parse -> clean -> store -> detect -> alerts."""
import hashlib
from typing import Dict, Optional

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .cleaning import clean_logs, to_records
from .db_sql import Alert, MinuteStat, Upload
from .detector import DetectionConfig, build_frame, run_all
from .parser import parse_lines


class IngestError(ValueError):
    pass


def _save_alerts(db: Session, upload_id: int, df: pd.DataFrame, cfg: DetectionConfig):
    rows = [Alert(upload_id=upload_id, **a) for a in run_all(df, cfg)]
    db.add_all(rows)
    return rows


def ingest_upload(db: Session, store, filename: str, raw: bytes,
                  cfg: Optional[DetectionConfig] = None, analyze: bool = True) -> Dict:
    cfg = cfg or DetectionConfig()
    sha = hashlib.sha256(raw).hexdigest()
    existing = db.scalar(select(Upload).where(Upload.sha256 == sha))
    if existing:  # same file dobara upload -> nayi entries nahi banti
        return {"upload": existing, "duplicate": True, "alerts": [], "cleaning": {}}

    df, unparsed = parse_lines(raw.decode("utf-8", errors="replace").splitlines())
    if df.empty:
        raise IngestError("Koi bhi line parse nahi hui. Format: 'YYYY-MM-DD HH:MM:SS [LEVEL] service: message'")
    df, report = clean_logs(df)
    if df.empty:
        raise IngestError("Cleaning ke baad koi valid row nahi bachi (timestamps invalid?)")

    upload = Upload(
        filename=filename, sha256=sha, lines_parsed=len(df), lines_unparsed=unparsed,
        first_ts=df["ts"].min().to_pydatetime(), last_ts=df["ts"].max().to_pydatetime(),
    )
    db.add(upload)
    db.flush()  # id mil jaaye

    store.insert_many(upload.id, to_records(df))

    frame = build_frame(df, "1min")
    db.add_all(
        MinuteStat(upload_id=upload.id, minute=ts.to_pydatetime(), total=int(r.total), errors=int(r.errors),
                   warnings=int(r.warnings), unique_ips=int(r.unique_ips))
        for ts, r in frame.iterrows()
    )
    alerts = _save_alerts(db, upload.id, df, cfg) if analyze else []
    db.commit()
    return {"upload": upload, "duplicate": False, "alerts": alerts, "cleaning": report}


def reanalyze(db: Session, store, upload_id: int, cfg: DetectionConfig):
    """Naye thresholds ke saath detection dobara. Sirf 'open' alerts replace hote hain;
    acknowledged/resolved history safe rehti hai."""
    df = store.fetch_frame(upload_id)
    if df.empty:
        raise IngestError("Is upload ka data store mein nahi mila (in-memory store restart hua?)")
    db.execute(delete(Alert).where(Alert.upload_id == upload_id, Alert.status == "open"))
    rows = _save_alerts(db, upload_id, df, cfg)
    db.commit()
    return rows
