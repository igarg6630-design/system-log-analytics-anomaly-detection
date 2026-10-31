import os

try:  # .env file load karo (agar python-dotenv installed hai)
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

SQL_URL = os.getenv("SQL_URL", "sqlite:///./logs.db")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "log_analytics")
MONGO_TIMEOUT_MS = int(os.getenv("MONGO_TIMEOUT_MS", "2000"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
