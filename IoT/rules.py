from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import DESK_LAMP_IDS, MAIN_LIGHT_ID
from state import RoomState


@dataclass(frozen=True)
class DeviceIntent:
    device_id: str
    desired_state: dict[str, Any]
    reason: str


class RulesEngine:
    """Small rules layer for deterministic room automations."""

    def evaluate(self, state: RoomState) -> tuple[list[DeviceIntent], list[str]]:
        mode = state.system["mode"]
        room_presence = int(state.sensors.get("room_presence", 0))
        desk_presence = int(state.sensors.get("desk_presence", 0))

        if mode == "away":
            notes = [
                "Mode away active: keeping lights off and reserving space for future vacuum automation.",
                "TODO: wire away mode into the vacuum and speaker flows when real devices are added.",
            ]
            return self._lamp_intents("OFF", "OFF", "mode_away"), notes

        if mode == "sleep":
            notes = [
                "Mode sleep active: lamps stay off.",
                "TODO: sleep mode can later tune AC, fan, curtain, and speaker scenes.",
            ]
            return self._lamp_intents("OFF", "OFF", "mode_sleep"), notes

        if desk_presence == 1:
            notes = []
            if mode == "study":
                notes.append(
                    "Mode study active: placeholder for future AC, fan, and speaker focus settings."
                )
            return self._lamp_intents("OFF", "ON", "desk_presence_focus"), notes

        if room_presence == 1 and desk_presence == 0:
            return self._lamp_intents("ON", "OFF", "room_presence_general"), []

        if room_presence == 0 and desk_presence == 0:
            return self._lamp_intents("OFF", "OFF", "room_empty"), []

        return [], [
            "Presence data is transitional; no automation change was emitted.",
            "TODO: extend rules for AC, fan, curtain, speaker, and vacuum based on more sensors.",
        ]

    def _lamp_intents(
        self,
        main_light_power: str,
        desk_light_power: str,
        reason: str,
    ) -> list[DeviceIntent]:
        intents = [
            DeviceIntent(MAIN_LIGHT_ID, {"power": main_light_power}, reason),
        ]
        intents.extend(
            DeviceIntent(device_id, {"power": desk_light_power}, reason)
            for device_id in DESK_LAMP_IDS
        )
        return intents
