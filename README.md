# Autonomous Excavator

Turning a Trasped 1:64 RC excavator (HG4-301/413 family, "2.4G remote + app" dual control) into an autonomous robot.

## Phases

1. **Reverse engineer the app protocol** and control the excavator from an ESP32. Plan: [docs/01-reverse-engineering-plan.md](docs/01-reverse-engineering-plan.md)
2. **Control API** on the ESP32 (serial / Wi-Fi): `drive`, `swing`, `boom`, `arm`, `bucket`, `lights`.
3. **Perception**: camera feed (phone or ESP32-CAM) to a GPU machine over Tailscale.
4. **Autonomy stack**: localization, task planning (dig, dump), closed-loop control.

## Repo layout

```
docs/      write-ups per phase
tools/     parse_btsnoop.py (HCI log parser), esp32_ble_scanner (discovery sketch)
captures/  raw logs + session notes (what was pressed when)
```

## Status

- [ ] Identify app + BLE mode (GATT vs advertising broadcast)
- [ ] First HCI snoop capture with scripted session
- [ ] Frame format decoded (channels, neutral values, checksum)
- [ ] APK decompiled, encoder confirmed
- [ ] ESP32 replay: forward/stop
- [ ] Full channel control from ESP32
