from __future__ import annotations

from typing import Any

from .base import BaseDevice, CommandResult

SPEED_ALIASES = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
}


class FanDevice(BaseDevice):
    @classmethod
    def default_state(cls) -> dict[str, Any]:
        return {
            "power": "OFF",
            "speed": 1,
        }

    def apply_command(self, command: Any) -> CommandResult:
        if isinstance(command, dict):
            updates: dict[str, Any] = {}

            if "power" in command:
                updates["power"] = self.normalize_power(command["power"])

            if "speed" in command:
                speed = int(command["speed"])
                if not 1 <= speed <= 3:
                    raise ValueError("Fan speed must stay between 1 and 3.")
                updates["speed"] = speed

            if not updates:
                raise ValueError("Fan command must include power or speed.")

            changed = self.update_state(**updates)
            return self.result(changed)

        normalized = str(command).strip().upper()
        if normalized == "STATUS":
            return self.result(False, should_publish=True, note="Fan status requested.")

        if normalized in SPEED_ALIASES:
            changed = self.update_state(power="ON", speed=SPEED_ALIASES[normalized])
            return self.result(changed)

        changed = self.update_state(power=self.normalize_power(normalized))
        return self.result(changed)
