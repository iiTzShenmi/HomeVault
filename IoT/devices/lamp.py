from __future__ import annotations

from typing import Any

from .base import BaseDevice, CommandResult


class LampDevice(BaseDevice):
    @classmethod
    def default_state(cls) -> dict[str, Any]:
        return {"power": "OFF"}

    def apply_command(self, command: Any) -> CommandResult:
        if isinstance(command, dict):
            raw_value = command.get("power")
            if raw_value is None:
                raise ValueError("Lamp command requires a 'power' field.")
        else:
            raw_value = command

        normalized = str(raw_value).strip().upper()
        if normalized == "TOGGLE":
            target = "OFF" if self._state["power"] == "ON" else "ON"
        else:
            target = self.normalize_power(raw_value)

        changed = self.update_state(power=target)
        return self.result(changed)
