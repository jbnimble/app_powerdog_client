# Ideas for future

- add availability in MQTT discovery payload for "RELAY ON" button so it can only be pressed during certain error conditions
- change to single topic for sending data to Home Assistant and send JSON object
- create an event workflow diagram
- emulator for testing error codes/status
- errors last X hours (most useful for web interface)
- HTTP client interface, socketIO or similar for streaming data to browser
- add `line1_topic_prefix` and `line2_topic_prefix` config
- add bluetooth adapter name to config, in case multiple BT adapters on system
- change logging level to `key = level` so log levels can be modified per logger
- fix `pylock.toml` to have the correct dependencies, move away from `requirements.txt`
- make it stable over long time periods
- pip installable package
- Home Assistant native plugin
- switch to https://github.com/empicano/aiomqtt
