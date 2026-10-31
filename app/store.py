"""Raw/parsed log storage: MongoDB (primary) + in-memory fallback.

Dono ka interface same hai. MongoDB na mile to app band nahi hota,
in-memory store use hota hai (restart par data jaata hai).
"""
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

log = logging.getLogger("store")


def _match(doc: Dict, f: Dict) -> bool:
    if f.get("upload_id") is not None and doc["upload_id"] != f["upload_id"]:
        return False
    if f.get("level") and doc["level"] != f["level"]:
        return False
    if f.get("service") and doc["service"] != f["service"]:
        return False
    if f.get("ip") and doc.get("ip") != f["ip"]:
        return False
    if f.get("start") and doc["ts"] < f["start"]:
        return False
    if f.get("end") and doc["ts"] >= f["end"]:
        return False
    if f.get("q") and f["q"].lower() not in doc["message"].lower():
        return False
    return True


class InMemoryLogStore:
    kind = "memory"

    def __init__(self):
        self.docs: List[Dict] = []

    def insert_many(self, upload_id: int, records: List[Dict]) -> int:
        self.docs.extend({**r, "upload_id": upload_id} for r in records)
        return len(records)

    def search(self, f: Dict, limit: int = 100, skip: int = 0):
        hits = [d for d in self.docs if _match(d, f)]
        hits.sort(key=lambda d: d["ts"])
        return len(hits), hits[skip: skip + limit]

    def level_counts(self, upload_id: int) -> Dict[str, int]:
        return dict(Counter(d["level"] for d in self.docs if d["upload_id"] == upload_id))

    def top_messages(self, upload_id: int, limit: int = 10, levels=("ERROR", "CRITICAL")):
        agg, ex, svc = Counter(), {}, defaultdict(set)
        for d in self.docs:
            if d["upload_id"] == upload_id and d["level"] in levels:
                agg[d["message_key"]] += 1
                ex.setdefault(d["message_key"], d["message"])
                svc[d["message_key"]].add(d["service"])
        return [
            {"message_key": k, "count": n, "example": ex[k], "services": sorted(svc[k])}
            for k, n in agg.most_common(limit)
        ]

    def fetch_frame(self, upload_id: int) -> pd.DataFrame:
        return pd.DataFrame([d for d in self.docs if d["upload_id"] == upload_id])

    def delete_upload(self, upload_id: int) -> None:
        self.docs = [d for d in self.docs if d["upload_id"] != upload_id]


class MongoLogStore:
    kind = "mongodb"

    def __init__(self, uri: str, db: str, timeout_ms: int = 2000):
        from pymongo import ASCENDING, MongoClient

        self.client = MongoClient(uri, serverSelectionTimeoutMS=timeout_ms)
        self.client.admin.command("ping")  # connect nahi hua to yahin exception
        self.col = self.client[db]["logs"]
        self.col.create_index([("upload_id", ASCENDING), ("ts", ASCENDING)])
        self.col.create_index([("upload_id", ASCENDING), ("level", ASCENDING)])
        self.col.create_index([("upload_id", ASCENDING), ("service", ASCENDING)])

    def insert_many(self, upload_id: int, records: List[Dict]) -> int:
        n = 0
        for i in range(0, len(records), 5000):
            batch = [{**r, "upload_id": upload_id} for r in records[i: i + 5000]]
            self.col.insert_many(batch, ordered=False)
            n += len(batch)
        return n

    @staticmethod
    def _query(f: Dict) -> Dict:
        q: Dict = {}
        if f.get("upload_id") is not None:
            q["upload_id"] = f["upload_id"]
        for k in ("level", "service", "ip"):
            if f.get(k):
                q[k] = f[k]
        if f.get("start") or f.get("end"):
            q["ts"] = {}
            if f.get("start"):
                q["ts"]["$gte"] = f["start"]
            if f.get("end"):
                q["ts"]["$lt"] = f["end"]
        if f.get("q"):
            q["message"] = {"$regex": re.escape(f["q"]), "$options": "i"}
        return q

    def search(self, f: Dict, limit: int = 100, skip: int = 0):
        q = self._query(f)
        total = self.col.count_documents(q)
        items = list(self.col.find(q, {"_id": 0}).sort("ts", 1).skip(skip).limit(limit))
        return total, items

    def level_counts(self, upload_id: int) -> Dict[str, int]:
        rows = self.col.aggregate(
            [{"$match": {"upload_id": upload_id}}, {"$group": {"_id": "$level", "n": {"$sum": 1}}}]
        )
        return {r["_id"]: r["n"] for r in rows}

    def top_messages(self, upload_id: int, limit: int = 10, levels=("ERROR", "CRITICAL")):
        rows = self.col.aggregate(
            [
                {"$match": {"upload_id": upload_id, "level": {"$in": list(levels)}}},
                {
                    "$group": {
                        "_id": "$message_key",
                        "count": {"$sum": 1},
                        "example": {"$first": "$message"},
                        "services": {"$addToSet": "$service"},
                    }
                },
                {"$sort": {"count": -1}},
                {"$limit": limit},
            ]
        )
        return [
            {"message_key": r["_id"], "count": r["count"], "example": r["example"], "services": sorted(r["services"])}
            for r in rows
        ]

    def fetch_frame(self, upload_id: int) -> pd.DataFrame:
        return pd.DataFrame(list(self.col.find({"upload_id": upload_id}, {"_id": 0})))

    def delete_upload(self, upload_id: int) -> None:
        self.col.delete_many({"upload_id": upload_id})


def create_store(uri: str, db: str, timeout_ms: int):
    try:
        store = MongoLogStore(uri, db, timeout_ms)
        log.info("MongoDB connected")
        return store
    except Exception as exc:  # noqa: BLE001
        log.warning("MongoDB unavailable (%s) - in-memory store use ho raha hai", exc)
        return InMemoryLogStore()
