# Autonomous Excavator

Turning a Trasped 1:64 RC excavator (HG4-301/413 family, "2.4G remote + app" dual control) into an autonomous robot.

## Autonomy

```bash
python3 dashboard/server.py --sim      # try it with the simulator
python3 dashboard/server.py --cam 1    # real excavator + iPhone camera
```

iPhone on the table at an angle, robot on any plain surface (e.g. a blanket), no markers or tape. Click to place targets or to drive, or type commands in plain language (vision-language planner). The excavator calibrates itself by wiggling, then goes A → dig → B → dump. Guide: [docs/05-autonomy-guide.md](docs/05-autonomy-guide.md).

![Dashboard](docs/img/dashboard.png)

## Drive it manually

```bash
python3 ui/server.py
```

Open http://localhost:8000. Full step-by-step guide: [docs/03-control-panel-guide.md](docs/03-control-panel-guide.md).

![Control panel](docs/img/ui-desktop.png)

## Phases

1. **Reverse engineer the app protocol** and control the excavator from an ESP32. Plan: [docs/01-reverse-engineering-plan.md](docs/01-reverse-engineering-plan.md)
2. **Control API** on the ESP32 (serial / Wi-Fi): `drive`, `swing`, `boom`, `arm`, `bucket`, `lights`.
3. **Autonomy stack**: iPhone overhead camera + ArUco markers, pose, go-to-point, dig/dump. Plan: [docs/04-autonomy-plan.md](docs/04-autonomy-plan.md)

## Repo layout

```
docs/      write-ups per phase
autonomy/  vision, brain (calibration, navigation, mission), simulator, config
dashboard/ server.py + index.html (autonomy dashboard)
excavator/ protocol.py (frame builder), mac_ble.py (CoreBluetooth broadcaster)
ui/        server.py + index.html (control panel)
tools/     ble_sniff.py (laptop advert sniffer), parse_btsnoop.py (Android HCI log parser), esp32_ble_scanner
captures/  raw logs + session notes (what was pressed when)
```

## Status

- [x] Identify app + BLE mode (GATT vs advertising broadcast)
- [x] First capture (iPhone + Mac sniffer, no Android needed)
- [x] Frame format decoded (channels, neutral values, checksum)
- [ ] ~~APK decompiled~~ (not needed)
- [x] **Mac drives the excavator** (`tools/mac_rccar_tx.py`, worked first try, 2026-10-31)
- [ ] Confirm bucket down = 0x20
- [x] Python control API + web control panel (keyboard, touch, gamepad)
- [x] Throttle floor 15, throttle applies to turns, trim
- [x] Markerless perception: pink square homography, green targets, yellow blob
- [x] Self-calibration by active perception, move-stop-look go-to, A→B mission (11/11 in sim)
- [x] Autonomy dashboard (camera views, map click-to-drive, mission, tuning)
- [x] Surface-agnostic work area (auto region / clicked corners / tape), click-placed targets
- [x] Plain-language commands via vision-language planner
- [ ] Run on the real floor
