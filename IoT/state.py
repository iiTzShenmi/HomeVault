from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from config import DEFAULT_SENSOR_STATE, SUPPORTED_MODES


class RoomState:
    """In-memory state store for sensors, modes, events, and device state."""

    def __init__(self, device_ids: Iterable[str]) -> None:
        self.sensors: dict[str, Any] = deepcopy(DEFAULT_SENSOR_STATE)
        self.system: dict[str, Any] = {
            "mode": "normal",
            "sleep_mode": False,
            "away_mode": False,
        }
        self.events: dict[str, Any] = {
            "last_rule": None,
            "last_source": None,
            "last_mode_payload": None,
        }
        self.devices: dict[str, dict[str, Any]] = {
            device_id: {} for device_id in device_ids
        }
        self.desired_devices: dict[str, dict[str, Any]] = {
            device_id: {} for device_id in device_ids
        }

    def update_sensor(self, sensor_name: str, value: Any) -> bool:
        previous = self.sensors.get(sensor_name)
        self.sensors[sensor_name] = value
        return previous != value

    def set_mode(self, mode_name: str) -> bool:
        normalized = mode_name.strip().lower()
        if normalized not in SUPPORTED_MODES:
            raise ValueError(
                f"Unsupported mode {mode_name!r}. Supported: {', '.join(SUPPORTED_MODES)}"
            )

        changed = self.system["mode"] != normalized
        self.system["mode"] = normalized
        self.system["sleep_mode"] = normalized == "sleep"
        self.system["away_mode"] = normalized == "away"
        return changed

    def update_device_state(self, device_id: str, updates: dict[str, Any]) -> bool:
        current = self.devices.setdefault(device_id, {})
        changed = False

        for key, value in updates.items():
            if current.get(key) != value:
                current[key] = value
                changed = True

        self._reconcile_desired_state(device_id)
        return changed

    def device_matches(self, device_id: str, expected: dict[str, Any]) -> bool:
        current = self.devices.get(device_id, {})
        if not current:
            return False
        return all(current.get(key) == value for key, value in expected.items())

    def desired_matches(self, device_id: str, expected: dict[str, Any]) -> bool:
        desired = self.desired_devices.get(device_id, {})
        if not desired:
            return False
        return all(desired.get(key) == value for key, value in expected.items())

    def remember_desired(self, device_id: str, expected: dict[str, Any]) -> None:
        self.desired_devices[device_id] = deepcopy(expected)

    def clear_desired(self, device_id: str) -> None:
        self.desired_devices[device_id] = {}

    def set_event(self, name: str, value: Any) -> None:
        self.events[name] = value

    def mode_snapshot(self) -> dict[str, Any]:
        return deepcopy(self.system)

    def snapshot(self) -> dict[str, Any]:
        return {
            "sensors": deepcopy(self.sensors),
            "system": deepcopy(self.system),
            "events": deepcopy(self.events),
            "devices": deepcopy(self.devices),
        }

    def _reconcile_desired_state(self, device_id: str) -> None:
        desired = self.desired_devices.get(device_id, {})
        if not desired:
            return

        current = self.devices.get(device_id, {})
        if all(current.get(key) == value for key, value in desired.items()):
            self.clear_desired(device_id)
            return

        if any(
            key in current and current.get(key) != value
            for key, value in desired.items()
        ):
            self.clear_desired(device_id)
