# System Log Analytics & Anomaly Detection (Backend)

FastAPI + Pandas/NumPy + scikit-learn + SQL (SQLAlchemy) + MongoDB.

## Setup (Python 3.9+ chahiye)
Project folder ke andar jao (jahan `app/` folder dikhta hai), phir:

**Windows (PowerShell / CMD)**
```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m app.sample_data --hours 6 --out data/sample.log
python -m uvicorn app.main:app --reload
```
**Mac / Linux**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m app.sample_data --hours 6 --out data/sample.log
python -m uvicorn app.main:app --reload
```
(Optional: `.env.example` ko `.env` naam se copy karke settings badlo. Bina .env ke SQLite + local MongoDB defaults chalte hain.)

Swagger UI: http://127.0.0.1:8000/docs

Demo:
```bash
curl -F "file=@data/sample.log" http://127.0.0.1:8000/logs/upload
curl http://127.0.0.1:8000/alerts
curl "http://127.0.0.1:8000/logs/search?level=error&q=timeout&limit=5"
# chart: browser mein http://127.0.0.1:8000/charts/error-trend.png
```

## MongoDB / MySQL
- MongoDB: `MONGO_URI` set karo. Na mile to app **in-memory store** par chalta hai (`/health` mein `log_store` dikhta hai).
  In-memory mein restart par raw logs jaate hain, SQL data (alerts, minute stats) rehta hai.
- MySQL: `SQL_URL=mysql+pymysql://user:pass@localhost:3306/log_analytics` (database pehle bana lo).

## Endpoints
| Method | Path | Kaam |
|---|---|---|
| POST | `/logs/upload` | log file upload -> parse, clean, store, detect (same file dobara = duplicate) |
| POST | `/uploads/{id}/analyze` | naye thresholds se re-detect (`z_threshold`, `window`, `min_errors`, `freq`, `bruteforce_threshold`) |
| GET | `/uploads`, DELETE `/uploads/{id}` | uploads list / delete |
| GET | `/logs/search` | filters: level, service, ip, q, start, end, limit, skip |
| GET | `/alerts` | filters: status, severity, alert_type, since, upload_id |
| PATCH | `/alerts/{id}` | status: open / acknowledged / resolved |
| GET | `/stats/summary` `/stats/error-trend` `/stats/top-errors` | dashboard data |
| GET | `/charts/error-trend.png` | error trend + anomaly windows chart |

## Detection kaise kaam karti hai
1. **Rolling z-score**: har minute ke errors (aur traffic) ko pichle 60 minutes ke baseline se compare karta hai.
   `min_errors` guard ki wajah se 2 -> 6 jaise chhote bumps alert nahi bante.
2. **IsolationForest**: errors, total, error_ratio, unique IPs/services ko saath dekhta hai (30+ minute data chahiye).
3. **Brute-force**: ek IP se sliding window mein >= 20 failed auth (401/403 ya "failed login").
4. Lagatar anomalous minutes ek incident/alert mein merge hote hain; alert mein top service + top messages
   hote hain taaki bug / overload / deployment / attack ka farq samajh aaye.

## Design notes
- Duplicate lines **drop nahi hoti**: same second mein identical errors hi spike ka signal hain. Double upload ko file hash rokta hai.
- Log format: `YYYY-MM-DD HH:MM:SS [LEVEL] service: message ip=... status=...` (parser.py mein regex badal sakte ho).
- Limitation: rolling baseline lamba spike hone par thoda adapt ho jaata hai; bahut lambi outage ke liye fixed baseline ya
  rolling median add karna better rahega.

## Tests
```bash
python tests/test_core.py   # parser/cleaning/detector/in-memory store (sirf pandas, numpy, scikit-learn chahiye)
pytest -q                   # + API end-to-end test
```
