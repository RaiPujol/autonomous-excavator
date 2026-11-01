# Autonomy: setup and run

The excavator finds itself with the iPhone camera, learns how it moves, and drives wherever you click or tell it. No markers, no tape needed, phone placed anywhere.

## How it works (short)

1. **Work area.** Three ways, pick in the dashboard (WORK AREA card):
   - **AUTO** (default): the uniform surface under the robot, e.g. a blanket. Its outline stops the robot search from picking up the floor around it. Works even if the blanket runs out of the camera view. Distances are in the camera view, scaled by the robot's own length (11 cm) as a ruler.
   - **CLICK CORNERS**: click 4 corners of any rectangle of known size on the camera image, enter its size. Gives true top-down cm.
   - **PINK TAPE**: the original pink tape square.
2. **Targets.** Click TARGET A / TARGET B, then click on the camera image or the map. (Green tape squares still work automatically.)
3. **Robot.** The biggest yellow blob inside the work area.
4. **Calibration by active perception.** Drives forward, back, spins left and right, watching itself: learns heading, speed, turn rate, which spin is which.
5. **Move, stop, look.** Short pulses, fresh camera measurement, repeat until the bucket is at the target. Works in the camera view because straight lines on the floor stay straight in the image.
6. **Mission / commands.** RUN MISSION = A, dig, B, dump. Or type a request in COMMAND (needs an API key, see below).

Tested in the simulator: 17/17 missions from random start poses (metric and camera-view modes).

## Setup (once)

**Surface**: something plain under the robot that is not yellow (your blue blanket is ideal). Even lighting.

**Phone**: on the table, angled down at the area, landscape. It must not move during a run (if it does, DETECT AGAIN).

**Mac**
```bash
cd ~/autonomous-excavator
git pull
pip install opencv-contrib-python anthropic
```
Allow Camera for Terminal: System Settings → Privacy & Security → Camera → Terminal on.

**Find the iPhone camera number**
```bash
python3 tools/camera_check.py --list
```
iPhone and Mac on the same Apple ID, Wi-Fi and Bluetooth on. The iPhone is usually the highest number.

**Plain-language commands (optional)**: get an API key at console.anthropic.com, then before starting the dashboard:
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```
The planner (Claude, model set in `autonomy/config.py` as `vlm_model`) sees the camera image with a coordinate grid drawn on it and returns a short JSON plan (go to x,y / dig / dump / set targets). The normal navigation executes it, so the STOP button and all safety still apply. Any point outside the work area is rejected.

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
3. Open http://localhost:8000. Check the header: CAMERA, AREA, ROBOT SEEN green. The cyan outline should follow the blanket.
4. Place targets: TARGET A, click a spot; TARGET B, click another.
5. Press **CALIBRATE**. Watch it wiggle. The log shows speed and turn rate.
6. Click anywhere (in DRIVE TO mode) to send it there. Then **RUN MISSION**, or type a command like "dig near the far corner, then dump next to B".
7. **STOP** (or Space) halts everything instantly.

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
| NO WORK AREA (auto) | The surface under the robot isn't uniform enough: raise "Work area colour tolerance" in Settings, or use CLICK CORNERS |
| Cyan outline leaks onto the floor | Lower "Work area colour tolerance" |
| ROBOT LOST although it's visible | It's outside the outline, or YELLOW sliders need widening (COLOURS view) |
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
autonomy/vlm.py      plain-language commands -> plan (Claude vision)
dashboard/server.py  camera + brain + Bluetooth + web server
dashboard/index.html the dashboard
```
