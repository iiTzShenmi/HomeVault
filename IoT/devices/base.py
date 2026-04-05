from __future__ import annotations

import json
from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass
class CommandResult:
    changed: bool
    state: dict[str, Any]
    should_publish: bool
    note: str = ""


class BaseDevice(ABC):
    """Shared interface for simulated devices and future real device adapters."""

    def __init__(self, device_id: str, friendly_name: str) -> None:
        self.device_id = device_id
        self.friendly_name = friendly_name
        self._state = self.default_state()

    @classmethod
    @abstractmethod
    def default_state(cls) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def state(self) -> dict[str, Any]:
        return deepcopy(self._state)

    def handle_command(self, payload: str) -> CommandResult:
        command = self.parse_payload(payload)
        return self.apply_command(command)

    def parse_payload(self, payload: str) -> Any:
        text = payload.strip()
        if not text:
            return ""

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    @abstractmethod
    def apply_command(self, command: Any) -> CommandResult:
        raise NotImplementedError

    def result(
        self,
        changed: bool,
        should_publish: bool | None = None,
        note: str = "",
    ) -> CommandResult:
        if should_publish is None:
            should_publish = changed
        return CommandResult(
            changed=changed,
            should_publish=should_publish,
            state=self.state,
            note=note,
        )

    def update_state(self, **updates: Any) -> bool:
        changed = False
        for key, value in updates.items():
            if self._state.get(key) != value:
                self._state[key] = value
                changed = True
        return changed

    def normalize_power(self, value: Any) -> str:
        normalized = str(value).strip().upper()
        mapping = {
            "1": "ON",
            "0": "OFF",
            "TRUE": "ON",
            "FALSE": "OFF",
            "ON": "ON",
            "OFF": "OFF",
        }
        if normalized not in mapping:
            raise ValueError(f"Unsupported power value: {value!r}")
        return mapping[normalized]
