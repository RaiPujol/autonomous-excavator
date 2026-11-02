# Autonomy: setup and run

The excavator finds itself with the iPhone camera, learns how it moves, and drives wherever you click or tell it. No markers, no tape needed, phone placed anywhere.

## How it works (short)

1. **Work area.** Three ways, pick in the dashboard (WORK AREA card):
   - **AUTO** (default): the uniform surface under the robot, e.g. a blanket. Its outline stops the robot search from picking up the floor around it. Works even if the blanket runs out of the camera view. Distances are in the camera view, scaled by the robot's own length (11 cm) as a ruler.
   - **CLICK CORNERS**: click 4 corners of any rectangle of known size on the camera image, enter its size. Gives true top-down cm.
   - **PINK TAPE**: the original pink tape square.
2. **Targets.** Click SET A / SET B (bottom-left of the camera), then click on the camera image. (Green tape squares still work automatically.)
3. **Robot.** The biggest yellow blob inside the work area. **Which end is the front** comes from the arm: it sticks out one end only, so the yellow blob is lopsided towards it. That gives a full 0-360° heading from a single look.
4. **Heading filter.** Three clues fused by a small Kalman filter: where the robot actually went when it drove (strongest), the arm side (every frame, a bit noisy), and the blob's long axis (precise, but can't tell front from back). It also learns the turret offset, and stops trusting the arm side if it keeps disagreeing with the motion.
5. **Calibration by active perception.** Forward + back (speed, true heading, which end the arm is on), 4 short spins (spin rate and motor dead time, kept under 90° each), then forward + back with uneven tracks (how much uneven tracks steer, and which track is A).
6. **Steer while driving.** A and B are the two track speeds, so it drives in curves towards the target and corrects every look (like pure pursuit). It only spins in place if the target is more than 60° off, or very close. Spins aim 80% of the way and the spin rate is re-measured after every spin, because the toy spins fast whatever throttle is sent. If uneven tracks don't steer, it falls back to spin-then-drive automatically.
7. **Mission / commands.** RUN MISSION = A, dig, B, dump. Or type a request in COMMAND (needs an API key, see below).

Tested in a realistic simulator (fast fixed-speed spins, motor dead time, random track wiring, drift, dark engine deck): `python3 tests/sim_missions.py` → 90/90 goals on 30 random robots. The previous controller got 48/90 there, failing with the same "too many steps" seen on the real toy.

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

1. Close the RCCar app on the phone. Excavator on, on the blanket, turret centred, **arm low and stretched out forward** (travel pose: the arm is how it tells front from back).
2. Start (replace `1` with your camera number):
   ```bash
   python3 dashboard/server.py --cam 1
   ```
3. Open http://localhost:8000. Check the header: CAMERA, AREA, ROBOT SEEN green. The cyan outline should follow the blanket.
4. Place targets: CLICK SET A, click a spot on the camera; SET B, click another.
5. Press **CALIBRATE**. Watch it wiggle. The log shows speed and turn rate.
6. Click anywhere on the camera image (CLICK: DRIVE TO) to send it there. Then **RUN MISSION**, or type a command like "dig near the far corner, then dump next to B".
7. **STOP** (or Space) halts everything instantly.

## Dashboard

| Area | What |
|---|---|
| Header | Status lights, the live Bluetooth frame, STOP |
| Camera card | Status bar on top (job + the command on air, e.g. `▶ FORWARD @22`). The camera image is the map: click it to drive there, or set A/B with the CLICK buttons. Views: CAMERA, TOP-DOWN (only with CLICK CORNERS or PINK TAPE), COLOURS (for tuning). Plain-language command box appears here only if an API key is set |
| Controls | WASD and arrow pads, throttle, trim, lights. Yellow = you, cyan = autopilot pressing the keys. Manual input is ignored while a job runs |
| Mission card | RUN MISSION (+ repeat count), CALIBRATE, GO TO A/B, DIG, DUMP, RESET CALIB, SWAP A/B, telemetry |
| Work area card | AUTO / CLICK CORNERS / PINK TAPE, DETECT AGAIN, CLEAR A/B |
| Log | Everything the brain does. The Terminal also prints every motor pulse and any `RADIO GAP` |
| Settings | Colour sliders (opening it switches to the COLOURS view), sizes, speeds, timings. SAVE SETTINGS writes `autonomy/config.json` |

**Diagnosing shutdowns**: `python3 tools/motion_test.py calib` (or `goto`, `--gentle`, `--app-turns`) replays the autonomy motion without camera or dashboard. If the toy dies there, it is power, not code. First suspect: battery.

## Tuning when something is off

| Symptom | Fix |
|---|---|
| NO WORK AREA (auto) | The surface under the robot isn't uniform enough: raise "Work area colour tolerance" in Settings, or use CLICK CORNERS |
| Cyan outline leaks onto the floor | Lower "Work area colour tolerance" |
| ROBOT LOST although it's visible | It's outside the outline, or YELLOW sliders need widening (COLOURS view) |
| A and B the wrong way round | SWAP A/B |
| ROBOT LOST | Settings → YELLOW. Make sure the floor isn't picked up |
| Calibration "only moved X cm" | Raise Auto drive throttle or Calib drive pulse |
| Calibration "spin too small" | Raise Calib spin pulse |
| "robot looks round from here" | Arm tucked in or raised: stretch it out low and forward. Without the arm, some viewing angles give no heading at all |
| "arm direction unclear" / "ignoring it" | Fine, it still works from motion + long axis, just more probe drives. Check the turret is centred |
| "uneven tracks barely steer" | It falls back to spin-then-drive. Raise "Steer: track speed" (more room between the two tracks) |
| Arrow on the camera points the wrong way after calibration | Arm folded back? It detects that, but recalibrate in travel pose |
| Orbits around a close target | Raise "Steer: near target" |
| Stops short or overshoots | Arrive tolerance, Bucket ahead of centre |
| Zig-zags a lot | Raise Settle after move (camera lag) |
| Excavator switches off mid-run | Charge it first (200 mAh, ~20 min). If it still happens: "gentle mode" = Settings → Min drive pulse 0.3, Min turn pulse 0.25 (fewer motor starts, smaller current spikes). Also try TURN: PULSE in the Manual card |

Edits apply live. Press SAVE SETTINGS to keep them.

## Files

```
autonomy/config.py   settings + defaults
autonomy/vision.py   work area, homography, robot blob, overlays, grid for the planner
autonomy/brain.py    calibration, go-to, dig/dump, mission
autonomy/sim.py      simulated camera + excavator (realistic: fast spins, dead time, random track wiring)
tests/sim_missions.py  headless regression test: calibrate + go-to on many random robots
autonomy/vlm.py      plain-language commands -> plan (Claude vision)
dashboard/server.py  camera + brain + Bluetooth + web server
dashboard/index.html the dashboard
```
