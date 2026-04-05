from __future__ import annotations

ROOT = "room"
EVENTS_PREFIX = f"{ROOT}/events"
SENSORS_PREFIX = f"{ROOT}/sensors"
COMMANDS_PREFIX = f"{ROOT}/commands"
DEVICES_PREFIX = f"{ROOT}/devices"
SYSTEM_PREFIX = f"{ROOT}/system"

ROOM_PRESENCE = f"{SENSORS_PREFIX}/room_presence"
DESK_PRESENCE = f"{SENSORS_PREFIX}/desk_presence"
MODE_SET = f"{COMMANDS_PREFIX}/mode/set"
MODE_STATE = f"{SYSTEM_PREFIX}/mode/state"
RULE_FIRED = f"{EVENTS_PREFIX}/rule_fired"
BRAIN_STATUS = f"{SYSTEM_PREFIX}/brain/status"
SIMULATOR_STATUS = f"{SYSTEM_PREFIX}/simulator/status"

LEGACY_ROOM_PRESENCE = "room/presence"
LEGACY_DESK_PRESENCE = "desk/presence"
LEGACY_MAIN_LAMP = "lamp/main"
LEGACY_DESK_LAMP = "lamp/desk"

DEVICE_SET_WILDCARD = f"{DEVICES_PREFIX}/+/set"
DEVICE_STATE_WILDCARD = f"{DEVICES_PREFIX}/+/state"

BRAIN_SUBSCRIPTIONS = (
    ROOM_PRESENCE,
    DESK_PRESENCE,
    LEGACY_ROOM_PRESENCE,
    LEGACY_DESK_PRESENCE,
    MODE_SET,
    DEVICE_STATE_WILDCARD,
)

SIMULATOR_SUBSCRIPTIONS = (
    DEVICE_SET_WILDCARD,
    LEGACY_MAIN_LAMP,
    LEGACY_DESK_LAMP,
)


def device_set(device_id: str) -> str:
    return f"{DEVICES_PREFIX}/{device_id}/set"


def device_state(device_id: str) -> str:
    return f"{DEVICES_PREFIX}/{device_id}/state"


def normalize_topic(topic_name: str) -> str:
    return {
        LEGACY_ROOM_PRESENCE: ROOM_PRESENCE,
        LEGACY_DESK_PRESENCE: DESK_PRESENCE,
    }.get(topic_name, topic_name)


def is_device_state_topic(topic_name: str) -> bool:
    parts = topic_name.split("/")
    return len(parts) == 4 and parts[:2] == [ROOT, "devices"] and parts[3] == "state"


def is_device_set_topic(topic_name: str) -> bool:
    parts = topic_name.split("/")
    return len(parts) == 4 and parts[:2] == [ROOT, "devices"] and parts[3] == "set"


def device_id_from_topic(topic_name: str) -> str | None:
    parts = topic_name.split("/")
    if len(parts) != 4 or parts[:2] != [ROOT, "devices"]:
        return None
    if parts[3] not in {"set", "state"}:
        return None
    return parts[2]
