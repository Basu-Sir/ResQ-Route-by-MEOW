"""
All Redis I/O for live traffic speeds lives here.
FastAPI and the fallback writer both go through this module — nothing
else is allowed to talk to Redis directly, and nothing here ever talks
to TraCI.
"""
import logging
from typing import Dict, Optional

import redis

from backend import config

logger = logging.getLogger("redis_client")

_client: Optional[redis.Redis] = None


def get_redis_client() -> redis.Redis:
    """Lazily create a singleton redis-py client (decode_responses=True)."""
    global _client
    if _client is None:
        _client = redis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            db=config.REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _client


def is_available(client: Optional[redis.Redis] = None) -> bool:
    client = client or get_redis_client()
    try:
        return bool(client.ping())
    except redis.RedisError:
        return False


def write_speeds(speeds: Dict[str, float], client: Optional[redis.Redis] = None) -> bool:
    """
    Batch-write edge_id -> speed into the traffic:speeds hash using a pipeline.
    Returns True on success, False if Redis is unreachable.
    """
    if not speeds:
        return True
    client = client or get_redis_client()
    try:
        pipe = client.pipeline()
        mapping = {edge_id: str(speed) for edge_id, speed in speeds.items()}
        pipe.hset(config.REDIS_SPEED_KEY, mapping=mapping)
        pipe.execute()
        return True
    except redis.RedisError as exc:
        logger.warning("Redis write failed: %s", exc)
        return False


def read_speeds(client: Optional[redis.Redis] = None) -> Dict[str, float]:
    """
    Read the full traffic:speeds hash. Returns {} (never raises) if Redis
    is unreachable or the hash does not exist yet.
    """
    client = client or get_redis_client()
    try:
        raw = client.hgetall(config.REDIS_SPEED_KEY)
        result = {}
        for edge_id, value in raw.items():
            try:
                result[edge_id] = float(value)
            except (TypeError, ValueError):
                continue
        return result
    except redis.RedisError as exc:
        logger.warning("Redis read failed: %s", exc)
        return {}