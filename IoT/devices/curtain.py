from __future__ import annotations

from typing import Any

from .base import BaseDevice, CommandResult


class CurtainDevice(BaseDevice):
    @classmethod
    def default_state(cls) -> dict[str, Any]:
        return {
            "state": "closed",
            "position": 0,
        }

    def apply_command(self, command: Any) -> CommandResult:
        if isinstance(command, dict):
            if "position" in command:
                position = int(command["position"])
                if not 0 <= position <= 100:
                    raise ValueError("Curtain position must stay between 0 and 100.")
                changed = self.update_state(
                    position=position,
                    state=self.position_to_state(position),
                )
                return self.result(changed)

            if "state" in command:
                return self.apply_command(command["state"])

            raise ValueError("Curtain command must include position or state.")

        normalized = str(command).strip().lower()
        if normalized == "status":
            return self.result(False, should_publish=True, note="Curtain status requested.")

        if normalized == "open":
            changed = self.update_state(state="open", position=100)
            return self.result(changed)

        if normalized == "close":
            changed = self.update_state(state="closed", position=0)
            return self.result(changed)

        if normalized == "stop":
            changed = self.update_state(state="stopped")
            return self.result(changed)

        raise ValueError(f"Unsupported curtain command: {command!r}")

    @staticmethod
    def position_to_state(position: int) -> str:
        if position == 0:
            return "closed"
        if position == 100:
            return "open"
        return "partial"
