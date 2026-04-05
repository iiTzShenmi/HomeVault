from __future__ import annotations

import json

from config import (
    DESK_LAMP_IDS,
    MQTT_HOST,
    MQTT_KEEPALIVE,
    MQTT_PORT,
    SIMULATOR_CLIENT_ID,
    configure_logging,
    create_mqtt_client,
    ensure_runtime_dirs,
)
from devices import build_simulated_devices
from devices.base import CommandResult
import topics


class MqttDeviceSimulator:
    """Runs the simulated room devices behind the MQTT command topics."""

    def __init__(self) -> None:
        ensure_runtime_dirs()
        self.log = configure_logging("simulator")
        self.devices = build_simulated_devices()
        self.client = create_mqtt_client(SIMULATOR_CLIENT_ID)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.will_set(topics.SIMULATOR_STATUS, "offline", retain=True)

    def start(self) -> None:
        self.log.info("Starting device simulator on %s:%s", MQTT_HOST, MQTT_PORT)
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

        for topic_name in topics.SIMULATOR_SUBSCRIPTIONS:
            client.subscribe(topic_name)
            self.log.info("Subscribed to %s", topic_name)

        self.client.publish(topics.SIMULATOR_STATUS, "online", retain=True)
        self.publish_all_states()

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

        topic_name = msg.topic
        payload = msg.payload.decode(errors="replace").strip()
        self.log.info("MQTT received topic=%s payload=%s", topic_name, payload)

        try:
            if topics.is_device_set_topic(topic_name):
                device_id = topics.device_id_from_topic(topic_name)
                if device_id is None:
                    self.log.warning("Could not resolve device command topic: %s", topic_name)
                    return
                self.handle_device_command(device_id, payload)
                return

            if topic_name == topics.LEGACY_MAIN_LAMP:
                self.handle_device_command("main_light", payload)
                return

            if topic_name == topics.LEGACY_DESK_LAMP:
                for device_id in DESK_LAMP_IDS:
                    self.handle_device_command(device_id, payload)
                return

            self.log.warning("Ignoring unsupported simulator topic: %s", topic_name)
        except ValueError as exc:
            self.log.warning("Rejected device command on topic=%s: %s", topic_name, exc)
        except Exception:
            self.log.exception("Unexpected simulator error on topic=%s", topic_name)

    def handle_device_command(self, device_id: str, payload: str) -> None:
        device = self.devices.get(device_id)
        if device is None:
            self.log.warning("Unknown device id=%s", device_id)
            return

        result = device.handle_command(payload)
        self.log_command_result(device_id, result)
        if result.should_publish:
            self.publish_state(device_id, result.state)

    def log_command_result(self, device_id: str, result: CommandResult) -> None:
        if result.note:
            self.log.info("%s: %s", device_id, result.note)

        if result.changed:
            self.log.info("Device %s changed state to %s", device_id, result.state)
            return

        self.log.info("Device %s state unchanged at %s", device_id, result.state)

    def publish_all_states(self) -> None:
        for device_id, device in self.devices.items():
            self.publish_state(device_id, device.state)

    def publish_state(self, device_id: str, state: dict[str, object]) -> None:
        payload = json.dumps(state, sort_keys=True)
        topic_name = topics.device_state(device_id)
        self.log.info("Publishing state topic=%s payload=%s", topic_name, payload)
        self.client.publish(topic_name, payload, retain=True)


def main() -> None:
    MqttDeviceSimulator().start()


if __name__ == "__main__":
    main()
