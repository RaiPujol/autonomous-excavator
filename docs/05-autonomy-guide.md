# Autonomy: setup and run

The excavator finds itself with the iPhone camera, learns how it moves, drives to square A, digs, drives to square B, dumps. No markers, phone placed anywhere.

## How it works (short)

1. **Scene.** The pink tape square has a known size, so its 4 corners give the perspective correction (homography) from the angled camera image to a top-down map in cm. The two green squares inside become targets A and B.
2. **Robot.** The biggest yellow blob inside the pink square. Its centre and long axis are measured in the top-down map.
3. **Calibration by active perception.** Drives forward 0.6 s, back, spins left, spins right, watching itself. Learns: which way it faces, cm/s, deg/s, and which spin direction is which.
4. **Move, stop, look.** Short turn or drive pulses, then a fresh camera measurement, repeat until the bucket is over the target.
5. **Mission.** Go to A, dig (boom down, creep forward, boom up), go to B, dump (turret 90°, boom down/up, turret back), repeat.

Tested in the simulator: 11/11 missions completed from random start positions, arriving within ~1-3.5 cm.

## Setup (once)

**Floor**
- Pink tape square, **60 cm** side measured outer edge to outer edge (any size works, enter it in Settings).
- Two green tape squares inside, ~12-15 cm, not touching the pink tape or each other.
- Plain floor that is not yellow, pink or green. Even lighting, no strong sun patches.

**Phone**
- On the table, angled down at the square, **the whole pink square visible** with a margin. Landscape.
- It must not move during a run. If you move it, press DETECT SCENE.

**Mac**
```bash
cd ~/autonomous-excavator
git pull
pip install opencv-contrib-python
```
Allow Camera for Terminal: System Settings → Privacy & Security → Camera → Terminal on.

**Find the iPhone camera number**
```bash
python3 tools/camera_check.py --list
```
iPhone and Mac on the same Apple ID, Wi-Fi and Bluetooth on. The iPhone is usually the highest number. Check with `python3 tools/camera_check.py --cam 1` (q to close).

## Try the simulator first (no hardware)

```bash
python3 dashboard/server.py --sim
```
Open http://localhost:8000, press RUN MISSION. Everything works the same as for real.

## Run it for real

1. Close the RCCar app on the phone. Excavator on, inside the pink square, turret centred.
2. Start (replace `1` with your camera number):
   ```bash
   python3 dashboard/server.py --cam 1
   ```
3. Open http://localhost:8000. Check the header: CAMERA, SCENE A+B, ROBOT SEEN all green.
4. Press **CALIBRATE**. Watch it wiggle. The log shows cm/s and deg/s.
5. Press **GO TO A**, or click anywhere on the map. Then **RUN MISSION**.
6. **STOP** (or Space) halts everything instantly.

## Dashboard

| Area | What |
|---|---|
| Header | Status lights, the live Bluetooth frame, STOP |
| Camera | CAMERA = live view with detections. TOP-DOWN = perspective-corrected map view. COLOURS = what the colour filters see (use when tuning) |
| Mission card | RUN MISSION (+ repeat count), CALIBRATE, GO TO A/B, DIG, DUMP, DETECT SCENE, SWAP A/B |
| Map | Top-down view in cm. Robot, heading, trail, targets. **Click to drive there** |
| Manual | Same controls as the control panel (WASD, arrows, L, throttle, trim). Disabled during a job |
| Settings | Colour sliders (opening it switches to the COLOURS view), sizes, speeds, timings. SAVE SETTINGS writes `autonomy/config.json` |

## Tuning when something is off

| Symptom | Fix |
|---|---|
| NO SCENE / pink not found | Settings → PINK: lower S min / V min until the tape is solid in COLOURS view, and nothing else is |
| Only 1 green square | Same for GREEN. Squares must be inside the pink one |
| A and B the wrong way round | SWAP A/B |
| ROBOT LOST | Settings → YELLOW. Make sure the floor isn't picked up |
| Calibration "only moved X cm" | Raise Auto drive throttle or Calib drive pulse |
| Calibration "spin too small" / spins wildly | Turn speed is the unknown: adjust Calib turn pulse (shorter if it spins more than ~60° per pulse) |
| Stops short or overshoots | Arrive tolerance, Bucket ahead of centre |
| Zig-zags a lot | Raise Settle after move (camera lag) |

Edits apply live. Press SAVE SETTINGS to keep them.

## Files

```
autonomy/config.py   settings + defaults
autonomy/vision.py   tape squares, homography, robot blob, overlays
autonomy/brain.py    calibration, go-to, dig/dump, mission
autonomy/sim.py      simulated camera + excavator
dashboard/server.py  camera + brain + Bluetooth + web server
dashboard/index.html the dashboard
```
