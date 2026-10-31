# System Log Analytics & Anomaly Detection

A Python-based backend application for analyzing system logs, detecting unusual activity, and generating alerts using statistical techniques and machine learning.

## Overview

System Log Analytics & Anomaly Detection helps identify abnormal system behavior by processing log files, analyzing error patterns, detecting anomalies, and generating actionable alerts.

The application provides REST APIs for log uploads, searching, alert management, statistics, and visualization.

## Key Features

- **Log Upload & Processing:** Upload, parse, clean, and store system log files.
- **Anomaly Detection:** Identify unusual error rates and traffic patterns.
- **Machine Learning:** Use Isolation Forest to detect abnormal behavior.
- **Brute-Force Detection:** Identify repeated failed authentication attempts from individual IP addresses.
- **Alert Management:** Generate, acknowledge, and resolve alerts.
- **Log Search:** Filter logs by severity, service, IP address, message, and time range.
- **Data Visualization:** Generate error-trend charts and anomaly-window visualizations.
- **Duplicate Upload Prevention:** Prevent repeated processing of the same uploaded file using file hashing.

## Tech Stack

| Technology | Purpose |
|---|---|
| Python | Backend development |
| FastAPI | REST API development |
| Pandas & NumPy | Data processing and analysis |
| Scikit-learn | Machine learning and anomaly detection |
| SQLAlchemy | SQL database management |
| SQLite / MySQL | Structured data storage |
| MongoDB | Log storage |
| Matplotlib | Data visualization |
| Pytest | Testing |

## Project Structure

```text
system-log-analytics-anomaly-detection/
│
├── app/
│   ├── __init__.py
│   ├── cleaning.py
│   ├── config.py
│   ├── db_sql.py
│   ├── detector.py
│   ├── main.py
│   ├── parser.py
│   ├── sample_data.py
│   ├── schemas.py
│   ├── service.py
│   └── store.py
│
├── data/
│   └── sample.log
│
├── tests/
│   ├── __init__.py
│   ├── test_api.py
│   └── test_core.py
│
├── .env.example
├── .gitignore
├── README.md
└── requirements.txt
```

## Installation & Setup

**Prerequisites:** Python 3.9 or later.

### 1. Clone the Repository

```bash
git clone https://github.com/igarg6630-design/system-log-analytics-anomaly-detection.git

cd system-log-analytics-anomaly-detection
```

### 2. Create a Virtual Environment

**Windows (PowerShell):**

```powershell
python -m venv .venv
.venv\Scripts\activate
```

**Mac / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Generate Sample Logs

```bash
python -m app.sample_data --hours 6 --out data/sample.log
```

### 5. Start the Application

```bash
python -m uvicorn app.main:app --reload
```

The backend server will start at:

`http://127.0.0.1:8000`

### 6. Explore API Documentation

Open the following URL in your browser:

`http://127.0.0.1:8000/docs`

FastAPI Swagger UI provides interactive API documentation.

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/logs/upload` | Upload and analyze log files |
| POST | `/uploads/{id}/analyze` | Re-analyze uploaded logs using updated thresholds |
| GET | `/uploads` | Retrieve uploaded files |
| DELETE | `/uploads/{id}` | Delete an uploaded file |
| GET | `/logs/search` | Search and filter system logs |
| GET | `/alerts` | Retrieve generated alerts |
| PATCH | `/alerts/{id}` | Update alert status |
| GET | `/stats/summary` | Retrieve summary statistics |
| GET | `/stats/error-trend` | Retrieve error-trend data |
| GET | `/stats/top-errors` | Retrieve frequently occurring errors |
| GET | `/charts/error-trend.png` | Generate an error-trend chart |

## Anomaly Detection Techniques

The application uses multiple detection techniques to identify abnormal system activity.

### 1. Rolling Z-Score

- Analyzes errors and traffic on a minute-by-minute basis.
- Compares current activity against the previous 60 minutes.
- Uses a minimum-error threshold to reduce false alerts from small changes.

### 2. Isolation Forest

- Uses Scikit-learn's Isolation Forest algorithm.
- Analyzes multiple features, including error count, total requests, error ratio, unique IP addresses, and services.
- Requires at least 30 minutes of data.

### 3. Brute-Force Detection

- Monitors repeated failed authentication attempts.
- Detects 401/403 responses or failed-login messages.
- Generates detection when an IP address produces at least 20 failed authentication attempts within the configured sliding window.

### 4. Alert Generation

- Combines consecutive anomalous minutes into a single incident.
- Includes the top affected service and frequently occurring messages.
- Helps investigate possible application bugs, traffic overload, deployment issues, or security attacks.

## Database Configuration

The application supports SQL databases and MongoDB for data storage.

### MongoDB

Configure the MongoDB connection using the `MONGO_URI` environment variable.

If MongoDB is unavailable, the application falls back to an in-memory log store.

**Note:** Raw logs stored in memory are lost when the application restarts. SQL data, including alerts and minute statistics, remains stored in the SQL database.

### SQLite

SQLite is used by default for structured data storage.

### MySQL (Optional)

To use MySQL, configure the `SQL_URL` environment variable:

```env
SQL_URL=mysql+pymysql://user:pass@localhost:3306/log_analytics
```

Create the database before starting the application.

For additional configuration, refer to `.env.example`.

## API Usage Examples

### Upload a Log File

```bash
curl -F "file=@data/sample.log" http://127.0.0.1:8000/logs/upload
```

### Retrieve Alerts

```bash
curl http://127.0.0.1:8000/alerts
```

### Search Error Logs

```bash
curl "http://127.0.0.1:8000/logs/search?level=error&q=timeout&limit=5"
```

### View Error Trend Chart

Open this URL in your browser:

`http://127.0.0.1:8000/charts/error-trend.png`

## Testing

Run core tests:

```bash
python tests/test_core.py
```

Run API and end-to-end tests:

```bash
pytest -q
```

The core tests cover parsing, cleaning, detection, and the in-memory store. The API test suite additionally covers API-level behavior.

## Design Considerations & Limitations

- Duplicate log lines are preserved because repeated errors can indicate unusual system activity.
- Duplicate file uploads are prevented using file hashing.
- The expected log format is:

```text
YYYY-MM-DD HH:MM:SS [LEVEL] service: message ip=... status=...
```

- The parser uses regular expressions that can be modified in `app/parser.py`.
- A rolling baseline may gradually adapt during prolonged anomalies. A fixed baseline or rolling median could improve detection of extended outages.

## Future Improvements

- Real-time log monitoring.
- Interactive monitoring dashboard.
- Advanced anomaly detection techniques.
- Improved alert notifications.
- More configurable detection thresholds.

## Author

**Ishan Garg**

GitHub: [@igarg6630-design](https://github.com/igarg6630-design)

---

If you find this project useful, consider giving the repository a ⭐ on GitHub.