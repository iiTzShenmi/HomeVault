from __future__ import annotations

import json
from typing import Any

from config import (
    BRAIN_CLIENT_ID,
    MQTT_HOST,
    MQTT_KEEPALIVE,
    MQTT_PORT,
    configure_logging,
    create_mqtt_client,
    ensure_runtime_dirs,
)
from devices import DEVICE_IDS
from rules import DeviceIntent, RulesEngine
from state import RoomState
import topics


def parse_presence_payload(payload: str) -> int:
    normalized = payload.strip().lower()
    if normalized in {"1", "on", "true", "yes", "occupied"}:
        return 1
    if normalized in {"0", "off", "false", "no", "empty"}:
        return 0
    raise ValueError(f"Unsupported presence payload: {payload!r}")


def parse_state_payload(payload: str) -> dict[str, Any]:
    text = payload.strip()
    if not text:
        return {}

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"value": text}

    if isinstance(parsed, dict):
        return parsed

    return {"value": parsed}


class SmartRoomBrain:
    """Main orchestration process for the room automation backend."""

    def __init__(self) -> None:
        ensure_runtime_dirs()
        self.log = configure_logging("brain")
        self.state = RoomState(DEVICE_IDS)
        self.rules = RulesEngine()
        self.client = create_mqtt_client(BRAIN_CLIENT_ID)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.will_set(topics.BRAIN_STATUS, "offline", retain=True)

    def start(self) -> None:
        self.log.info("Starting smart room brain on %s:%s", MQTT_HOST, MQTT_PORT)
        self.client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)
        self.client.loop_forever()

    def on_connect(
        self,
        client,
        userdata,
        flags,
        reason_code,
        properties=None,
    ) -> None:
        del userdata, flags, properties

        if int(reason_code) != 0:
            self.log.error("MQTT connection failed with reason_code=%s", reason_code)
            return

        for topic_name in topics.BRAIN_SUBSCRIPTIONS:
            client.subscribe(topic_name)
            self.log.info("Subscribed to %s", topic_name)

        self.publish_system_status("online")
        self.publish_mode_state(force=True)
        self.apply_rules(source="startup")

    def on_disconnect(
        self,
        client,
        userdata,
        reason_code,
        properties=None,
    ) -> None:
        del client, userdata, properties
        self.log.warning("MQTT disconnected with reason_code=%s", reason_code)

    def on_message(self, client, userdata, msg) -> None:
        del client, userdata

        topic_name = topics.normalize_topic(msg.topic)
        payload = msg.payload.decode(errors="replace").strip()
        self.log.info("MQTT received topic=%s payload=%s", msg.topic, payload)

        try:
            if topic_name == topics.ROOM_PRESENCE:
                self.handle_sensor_update("room_presence", payload)
                return

            if topic_name == topics.DESK_PRESENCE:
                self.handle_sensor_update("desk_presence", payload)
                return

            if topic_name == topics.MODE_SET:
                self.handle_mode_update(payload)
                return

            if topics.is_device_state_topic(topic_name):
                device_id = topics.device_id_from_topic(topic_name)
                if device_id is None:
                    self.log.warning("Could not resolve device state topic: %s", topic_name)
                    return
                self.handle_device_state(device_id, payload)
                return

            self.log.warning("Ignoring unsupported topic: %s", msg.topic)
        except ValueError as exc:
            self.log.warning("Rejected payload on topic=%s: %s", msg.topic, exc)
        except Exception:
            self.log.exception("Unexpected error while handling topic=%s", msg.topic)

    def handle_sensor_update(self, sensor_name: str, payload: str) -> None:
        presence = parse_presence_payload(payload)
        changed = self.state.update_sensor(sensor_name, presence)
        if not changed:
            self.log.info("Sensor %s unchanged at %s", sensor_name, presence)
            return

        self.log.info("Sensor %s updated to %s", sensor_name, presence)
        self.apply_rules(source=f"sensor:{sensor_name}")

    def handle_mode_update(self, payload: str) -> None:
        changed = self.state.set_mode(payload)
        self.publish_mode_state(force=changed)

        if not changed:
            self.log.info("Mode already set to %s", self.state.system["mode"])
            return

        self.log.info("Mode changed to %s", self.state.system["mode"])
        self.apply_rules(source="mode_change")

    def handle_device_state(self, device_id: str, payload: str) -> None:
        state_update = parse_state_payload(payload)
        changed = self.state.update_device_state(device_id, state_update)
        if changed:
            self.log.info("Device %s state updated to %s", device_id, state_update)
        else:
            self.log.info("Device %s reported unchanged state %s", device_id, state_update)

    def apply_rules(self, source: str) -> None:
        intents, notes = self.rules.evaluate(self.state)
        self.state.set_event("last_source", source)

        for note in notes:
            self.log.info(note)

        published_reasons: list[str] = []
        for intent in intents:
            if self.publish_intent(intent):
                published_reasons.append(intent.reason)

        if published_reasons:
            unique_reasons = sorted(set(published_reasons))
            event_payload = json.dumps(
                {
                    "source": source,
                    "rules": unique_reasons,
                },
                sort_keys=True,
            )
            self.client.publish(topics.RULE_FIRED, event_payload)
            self.state.set_event("last_rule", ",".join(unique_reasons))

    def publish_intent(self, intent: DeviceIntent) -> bool:
        if self.state.device_matches(intent.device_id, intent.desired_state):
            self.log.info(
                "Skipping command for %s because actual state already matches %s",
                intent.device_id,
                intent.desired_state,
            )
            self.state.clear_desired(intent.device_id)
            return False

        if self.state.desired_matches(intent.device_id, intent.desired_state):
            self.log.info(
                "Skipping duplicate command for %s while waiting for state sync",
                intent.device_id,
            )
            return False

        payload = json.dumps(intent.desired_state, sort_keys=True)
        topic_name = topics.device_set(intent.device_id)
        self.log.info(
            "Rule trigger=%s -> publish %s payload=%s",
            intent.reason,
            topic_name,
            payload,
        )
        self.client.publish(topic_name, payload)
        self.state.remember_desired(intent.device_id, intent.desired_state)
        return True

    def publish_system_status(self, status: str) -> None:
        self.client.publish(topics.BRAIN_STATUS, status, retain=True)
        self.log.info("Brain status=%s", status)

    def publish_mode_state(self, force: bool = False) -> None:
        payload = json.dumps(self.state.mode_snapshot(), sort_keys=True)
        if not force and self.state.events.get("last_mode_payload") == payload:
            return

        self.client.publish(topics.MODE_STATE, payload, retain=True)
        self.state.set_event("last_mode_payload", payload)
        self.log.info("Published mode state %s", payload)


def main() -> None:
    SmartRoomBrain().start()


if __name__ == "__main__":
    main()
