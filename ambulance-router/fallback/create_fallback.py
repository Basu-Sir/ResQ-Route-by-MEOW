"""
Periodically snapshots the Redis `traffic:speeds` hash to
fallback/fallback_traffic.json so FastAPI can keep serving routes even
when Redis is completely unavailable.

Run as a standalone process with:  python -m fallback.create_fallback
Also importable: read_fallback_speeds() is used directly by backend/main.py.
"""
import json
import logging
import os
import tempfile
import time
from typing import Dict

from backend import config, redis_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("create_fallback")


def _atomic_write_json(path: str, data: dict) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp_path, path)  # atomic on both Windows and POSIX
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def save_fallback_snapshot() -> bool:
    client = redis_client.get_redis_client()
    if not redis_client.is_available(client):
        logger.warning("Redis unavailable, skipping fallback snapshot this cycle")
        return False

    speeds = redis_client.read_speeds(client)
    if not speeds:
        logger.info("No speeds currently in Redis; leaving existing fallback file untouched")
        return False

    _atomic_write_json(config.FALLBACK_FILE, speeds)
    logger.info("Saved fallback snapshot with %d edges", len(speeds))
    return True


def read_fallback_speeds() -> Dict[str, float]:
    if not os.path.exists(config.FALLBACK_FILE):
        return {}
    try:
        with open(config.FALLBACK_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return {k: float(v) for k, v in raw.items()}
    except (json.JSONDecodeError, OSError, ValueError):
        logger.warning("Fallback file is unreadable/corrupt, treating as empty")
        return {}


def main() -> None:
    logger.info("Starting fallback snapshot loop (every %ss)", config.FALLBACK_SAVE_INTERVAL_SECONDS)
    while True:
        try:
            save_fallback_snapshot()
        except Exception as exc:
            logger.exception("Unexpected error saving fallback snapshot: %s", exc)
        time.sleep(config.FALLBACK_SAVE_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()