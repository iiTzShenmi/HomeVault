from __future__ import annotations

from typing import Any

from .base import BaseDevice, CommandResult


class VacuumDevice(BaseDevice):
    @classmethod
    def default_state(cls) -> dict[str, Any]:
        return {
            "status": "docked",
            "simulated": True,
        }

    def apply_command(self, command: Any) -> CommandResult:
        if isinstance(command, dict):
            raw_action = command.get("command") or command.get("action")
            if raw_action is None:
                raise ValueError("Vacuum command requires 'command' or 'action'.")
            return self.apply_command(raw_action)

        action = str(command).strip().lower()
        if action == "status":
            return self.result(
                False,
                should_publish=True,
                note="Vacuum status requested.",
            )

        if action == "start_clean":
            changed = self.update_state(status="cleaning", simulated=True)
            return self.result(
                changed,
                note="Vacuum running in simulated mode. Replace this class for Xiaomi local control later.",
            )

        if action == "stop_clean":
            changed = self.update_state(status="idle", simulated=True)
            return self.result(changed)

        if action == "dock":
            changed = self.update_state(status="docked", simulated=True)
            return self.result(changed)

        raise ValueError(
            "Unsupported vacuum command. Use start_clean, stop_clean, dock, or status."
        )
