"""
simulation_daemon.py

Runs completely independently from FastAPI.

Starts SUMO through TraCI, advances the simulation every second, reads
traci.edge.getLastStepMeanSpeed(edge_id) for every edge, and batch-writes
all speeds to the Redis hash `traffic:speeds`.

If SUMO/TraCI crashes for any reason, this daemon automatically closes
the connection and restarts SUMO after a short backoff, forever.

Run with:  python -m simulation.simulation_daemon
"""
import logging
import time

from backend import config, redis_client

config.ensure_sumo_tools_on_path()
import traci  # noqa: E402
import sumolib  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("simulation_daemon")


def build_sumo_cmd() -> list:
    binary = sumolib.checkBinary(config.SUMO_BINARY_NAME)
    return [binary, "-c", config.SUMO_CONFIG_FILE, "--step-length", "1"]


def collect_edge_speeds() -> dict:
    speeds = {}
    for edge_id in traci.edge.getIDList():
        if edge_id.startswith(":"):
            continue
        try:
            speeds[edge_id] = float(traci.edge.getLastStepMeanSpeed(edge_id))
        except traci.exceptions.TraCIException:
            continue
    return speeds


def run_simulation_loop() -> None:
    cmd = build_sumo_cmd()
    logger.info("Starting SUMO: %s", " ".join(cmd))
    traci.start(cmd)

    try:
        while True:
            traci.simulationStep()
            speeds = collect_edge_speeds()
            ok = redis_client.write_speeds(speeds)
            if not ok:
                logger.warning("Could not write speeds to Redis this step")

            if traci.simulation.getMinExpectedNumber() <= 0:
                logger.info("No more vehicles expected; restarting simulation cycle")
                break

            time.sleep(config.SIMULATION_STEP_SLEEP_SECONDS)
    finally:
        try:
            traci.close()
        except traci.exceptions.TraCIException:
            pass


def main() -> None:
    backoff = config.REDIS_RECONNECT_BACKOFF_SECONDS
    while True:
        try:
            run_simulation_loop()
        except (traci.exceptions.FatalTraCIError, traci.exceptions.TraCIException) as exc:
            logger.error("SUMO/TraCI crashed: %s. Restarting in %ss", exc, backoff)
            try:
                traci.close()
            except Exception:
                pass
            time.sleep(backoff)
        except KeyboardInterrupt:
            logger.info("Shutdown requested, stopping daemon")
            try:
                traci.close()
            except Exception:
                pass
            break
        except Exception as exc:  # unexpected error - restart rather than die
            logger.exception("Unexpected error in simulation daemon: %s", exc)
            time.sleep(backoff)


if __name__ == "__main__":
    main()