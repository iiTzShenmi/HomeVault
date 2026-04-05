from __future__ import annotations

import logging
from pathlib import Path

try:
    import paho.mqtt.client as mqtt
except ModuleNotFoundError:
    mqtt = None

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"

MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_KEEPALIVE = 60

SUPPORTED_MODES = ("normal", "study", "sleep", "away")
MAIN_LIGHT_ID = "main_light"
DESK_LAMP_IDS = ("desk_lamp_left", "desk_lamp_right")

DEFAULT_SENSOR_STATE = {
    "room_presence": 0,
    "desk_presence": 0,
}

BRAIN_CLIENT_ID = "smart-room-brain"
SIMULATOR_CLIENT_ID = "smart-room-simulator"


def ensure_runtime_dirs() -> None:
    LOG_DIR.mkdir(exist_ok=True)


def configure_logging(service_name: str) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )
    return logging.getLogger(f"iot.{service_name}")


def create_mqtt_client(client_id: str):
    """Create a client that works with both paho-mqtt 1.x and 2.x."""
    if mqtt is None:
        raise RuntimeError(
            "paho-mqtt is not installed for the current interpreter. "
            "Activate your IoT venv or install it with 'pip install paho-mqtt'."
        )

    if hasattr(mqtt, "CallbackAPIVersion"):
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
    else:
        client = mqtt.Client(client_id=client_id)

    client.reconnect_delay_set(min_delay=1, max_delay=10)
    return client
