from __future__ import annotations

from .air_conditioner import AirConditionerDevice
from .curtain import CurtainDevice
from .fan import FanDevice
from .lamp import LampDevice
from .speaker import SpeakerDevice
from .vacuum import VacuumDevice

DEVICE_BLUEPRINTS = (
    ("main_light", LampDevice, "Main Light"),
    ("desk_lamp_left", LampDevice, "Desk Lamp Left"),
    ("desk_lamp_right", LampDevice, "Desk Lamp Right"),
    ("air_conditioner", AirConditionerDevice, "Air Conditioner"),
    ("fan", FanDevice, "Fan"),
    ("curtain", CurtainDevice, "Curtain"),
    ("speaker", SpeakerDevice, "Speaker"),
    ("vacuum", VacuumDevice, "Vacuum"),
)

DEVICE_IDS = tuple(device_id for device_id, _, _ in DEVICE_BLUEPRINTS)


def build_simulated_devices():
    return {
        device_id: device_class(device_id, friendly_name)
        for device_id, device_class, friendly_name in DEVICE_BLUEPRINTS
    }
