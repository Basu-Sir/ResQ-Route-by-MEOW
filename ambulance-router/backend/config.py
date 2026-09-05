"""
Centralized, environment-driven configuration.
All paths are handled with pathlib so they work on Windows and Linux alike.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------- Redis ----------------
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_SPEED_KEY = os.getenv("REDIS_SPEED_KEY", "traffic:speeds")

# ---------------- SUMO ----------------
SUMO_HOME = os.getenv("SUMO_HOME", "")
SUMO_NET_FILE = str((BASE_DIR / os.getenv("SUMO_NET_FILE", "net.net.xml")).resolve())
SUMO_CONFIG_FILE = str((BASE_DIR / os.getenv("SUMO_CONFIG_FILE", "simulation/city.sumocfg")).resolve())
SUMO_BINARY_NAME = os.getenv("SUMO_BINARY_NAME", "sumo")

# ---------------- Data ----------------
HOSPITALS_FILE = str((BASE_DIR / os.getenv("HOSPITALS_FILE", "data/hospitals.json")).resolve())
FALLBACK_FILE = str((BASE_DIR / os.getenv("FALLBACK_FILE", "fallback/fallback_traffic.json")).resolve())

# ---------------- Routing ----------------
ALPHA_EMERGENCY_DEFAULT = float(os.getenv("ALPHA_EMERGENCY_DEFAULT", "1.0"))

# ---------------- Daemons ----------------
SIMULATION_STEP_SLEEP_SECONDS = float(os.getenv("SIMULATION_STEP_SLEEP_SECONDS", "1.0"))
FALLBACK_SAVE_INTERVAL_SECONDS = float(os.getenv("FALLBACK_SAVE_INTERVAL_SECONDS", "5"))
REDIS_RECONNECT_BACKOFF_SECONDS = float(os.getenv("REDIS_RECONNECT_BACKOFF_SECONDS", "2"))


def ensure_sumo_tools_on_path() -> None:
    """
    Makes 'traci' and 'sumolib' importable when only SUMO_HOME is set
    (standard SUMO installation layout), on both Windows and Linux.
    """
    import sys

    if SUMO_HOME:
        tools = str(Path(SUMO_HOME) / "tools")
        if tools not in sys.path:
            sys.path.append(tools)