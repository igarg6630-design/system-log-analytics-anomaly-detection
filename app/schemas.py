from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict


class UploadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    filename: str
    lines_parsed: int
    lines_unparsed: int
    first_ts: Optional[datetime]
    last_ts: Optional[datetime]
    created_at: datetime


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    upload_id: int
    alert_type: str
    metric: str
    window_start: datetime
    window_end: datetime
    observed: float
    baseline: Optional[float]
    score: Optional[float]
    severity: str
    method: str
    summary: str
    details: Dict[str, Any]
    status: str
    created_at: datetime


class AlertStatusUpdate(BaseModel):
    status: Literal["open", "acknowledged", "resolved"]


class IngestOut(BaseModel):
    duplicate: bool
    upload: UploadOut
    cleaning: Dict[str, Any]
    alerts: list[AlertOut]
