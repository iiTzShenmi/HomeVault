from __future__ import annotations

from typing import Any

from .base import BaseDevice, CommandResult


class SpeakerDevice(BaseDevice):
    @classmethod
    def default_state(cls) -> dict[str, Any]:
        return {
            "power": "OFF",
            "state": "idle",
            "volume": 30,
        }

    def apply_command(self, command: Any) -> CommandResult:
        if isinstance(command, dict):
            updates: dict[str, Any] = {}

            if "power" in command:
                updates["power"] = self.normalize_power(command["power"])

            if "state" in command:
                speaker_state = str(command["state"]).strip().lower()
                if speaker_state not in {"idle", "playing", "paused", "stopped"}:
                    raise ValueError(f"Unsupported speaker state: {command['state']!r}")
                updates["state"] = speaker_state

            if "volume" in command:
                volume = int(command["volume"])
                if not 0 <= volume <= 100:
                    raise ValueError("Speaker volume must stay between 0 and 100.")
                updates["volume"] = volume

            if not updates:
                raise ValueError("Speaker command must include power, state, or volume.")

            changed = self.update_state(**updates)
            return self.result(changed)

        normalized = str(command).strip().upper()
        if normalized == "STATUS":
            return self.result(False, should_publish=True, note="Speaker status requested.")

        if normalized == "PLAY":
            changed = self.update_state(power="ON", state="playing")
            return self.result(changed)

        if normalized == "PAUSE":
            changed = self.update_state(power="ON", state="paused")
            return self.result(changed)

        if normalized == "STOP":
            changed = self.update_state(power="ON", state="stopped")
            return self.result(changed)

        changed = self.update_state(power=self.normalize_power(normalized))
        return self.result(changed)
