# Smart Room Backend System

Small local-first MQTT backend for a privacy-first room setup. The code is organized so simulated devices can later be replaced by real hardware adapters with minimal changes.

## Files

- `brain.py`: main orchestration process
- `device_sim.py`: simulator entrypoint for all room devices
- `config.py`: runtime configuration and MQTT client helpers
- `state.py`: in-memory state store
- `topics.py`: shared MQTT topic schema
- `rules.py`: automation rules
- `devices/`: device abstractions and per-device command/state logic
- `simulators/`: MQTT simulator runtime

## Run

Start the backend brain:

```bash
python3 brain.py
```

Start the simulator in another terminal:

```bash
python3 device_sim.py
```

Both default to `localhost:1883`.

## MQTT Topic Design

- Sensors: `room/sensors/...`
- Commands: `room/commands/...`
- Device commands: `room/devices/<device_id>/set`
- Device state reports: `room/devices/<device_id>/state`
- System topics: `room/system/...`
- Rule events: `room/events/rule_fired`

Supported sensor and mode topics:

- `room/sensors/room_presence`
- `room/sensors/desk_presence`
- `room/commands/mode/set`
- `room/system/mode/state`

Supported legacy topics kept for easy manual testing:

- `room/presence`
- `desk/presence`
- `lamp/main`
- `lamp/desk`

## Manual MQTT Tests

Presence simulation:

```bash
mosquitto_pub -h localhost -t room/sensors/room_presence -m 1
mosquitto_pub -h localhost -t room/sensors/desk_presence -m 1
mosquitto_pub -h localhost -t room/sensors/room_presence -m 0
mosquitto_pub -h localhost -t room/sensors/desk_presence -m 0
```

Legacy presence simulation:

```bash
mosquitto_pub -h localhost -t room/presence -m 1
mosquitto_pub -h localhost -t desk/presence -m 1
```

Mode switching:

```bash
mosquitto_pub -h localhost -t room/commands/mode/set -m study
mosquitto_pub -h localhost -t room/commands/mode/set -m sleep
mosquitto_pub -h localhost -t room/commands/mode/set -m away
mosquitto_pub -h localhost -t room/commands/mode/set -m normal
```

Manual device commands:

```bash
mosquitto_pub -h localhost -t room/devices/main_light/set -m ON
mosquitto_pub -h localhost -t room/devices/fan/set -m '{"power":"ON","speed":2}'
mosquitto_pub -h localhost -t room/devices/air_conditioner/set -m '{"power":"ON","mode":"cool","target_temp":23}'
mosquitto_pub -h localhost -t room/devices/curtain/set -m '{"position":50}'
mosquitto_pub -h localhost -t room/devices/speaker/set -m PLAY
mosquitto_pub -h localhost -t room/devices/vacuum/set -m start_clean
mosquitto_pub -h localhost -t room/devices/vacuum/set -m dock
mosquitto_pub -h localhost -t room/devices/vacuum/set -m status
```

Legacy lamp commands:

```bash
mosquitto_pub -h localhost -t lamp/main -m ON
mosquitto_pub -h localhost -t lamp/desk -m OFF
```

Watch device states:

```bash
mosquitto_sub -h localhost -t 'room/devices/+/state'
mosquitto_sub -h localhost -t 'room/system/#'
mosquitto_sub -h localhost -t 'room/events/#'
```

## Notes

- The brain only publishes automation commands when the desired state differs from the current or pending state.
- The simulator publishes retained state messages so new subscribers can inspect the latest device state.
- `devices/vacuum.py` is intentionally isolated so a future Xiaomi local implementation can replace the simulated logic cleanly.
