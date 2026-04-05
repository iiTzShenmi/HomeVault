from __future__ import annotations

from typing import Any

from .base import BaseDevice, CommandResult

VALID_MODES = {"cool", "fan", "dry", "auto"}


class AirConditionerDevice(BaseDevice):
    @classmethod
    def default_state(cls) -> dict[str, Any]:
        return {
            "power": "OFF",
            "mode": "cool",
            "target_temp": 24,
        }

    def apply_command(self, command: Any) -> CommandResult:
        if isinstance(command, dict):
            updates: dict[str, Any] = {}

            if "power" in command:
                updates["power"] = self.normalize_power(command["power"])

            if "mode" in command:
                mode = str(command["mode"]).strip().lower()
                if mode not in VALID_MODES:
                    raise ValueError(f"Unsupported AC mode: {command['mode']!r}")
                updates["mode"] = mode

            if "target_temp" in command:
                target_temp = int(command["target_temp"])
                if not 16 <= target_temp <= 30:
                    raise ValueError("AC target_temp must stay between 16 and 30.")
                updates["target_temp"] = target_temp

            if not updates:
                raise ValueError("AC command must include power, mode, or target_temp.")

            changed = self.update_state(**updates)
            return self.result(changed)

        normalized = str(command).strip().upper()
        if normalized == "STATUS":
            return self.result(False, should_publish=True, note="AC status requested.")

        changed = self.update_state(power=self.normalize_power(normalized))
        return self.result(changed)
