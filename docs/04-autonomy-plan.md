> **Superseded (2026-10-31):** markers dropped. Final design: phone at an angle on the table, pink tape square as calibration target, green squares as targets, self-calibration by driving. See [05-autonomy-guide.md](05-autonomy-guide.md).

# Phase 2: Autonomy stack

## Camera: iPhone overhead, via Continuity Camera

The excavator is 1:64 (~100 g), so it can't carry a camera or a computer. The robot's "eyes" sit above the work area instead, like a motion-capture lab.

**iPhone as the camera.** macOS Continuity Camera makes the iPhone show up as a normal webcam, so OpenCV reads it like any camera, wirelessly. Needs the same Apple ID on both, Wi-Fi + Bluetooth on, and the iPhone locked and in landscape. Better image and placement than the MacBook webcam.

**Mount.** Phone facing straight down, ~40-60 cm above a desk or a sheet of paper/cardboard (the "job site"). A cheap phone gooseneck/overhead tripod is ideal; a phone taped under a shelf works for a start.

**Markers.** `tools/make_markers.py` makes a printable sheet:
- ID 0 (20 mm) on the cab roof, gives the excavator position + heading
- IDs 1-4 (40 mm) at the corners of the work area, give a fixed world frame in mm
- IDs 5-7 spares for dig pile / dump spot / obstacles

Note: the cab rotates relative to the tracks. Start with the marker on the cab and keep the turret centered while driving; add a second marker on the track body later if needed.

## Stack (each layer usable on its own)

```
iPhone camera ──> perception ──> state estimate ──> planner ──> controller ──> ui/server ──> BLE ──> excavator
                  (ArUco)        (x, y, heading)    (waypoints,  (turn/drive
                                                     tasks)       commands)
```

| Step | What | Done when |
|---|---|---|
| 1. Camera check | `tools/camera_check.py`: find the iPhone, detect markers | Markers boxed in the live view |
| 2. World frame | Corner markers 1-4 → homography → pixel to mm | Clicking the image prints mm coordinates |
| 3. Pose | Excavator marker → x, y (mm), heading, ~30 Hz | Pose overlay follows the toy |
| 4. Calibration | Measure mm/s per throttle and deg/s per turn | Table of speeds saved to a config |
| 5. Go-to-point | Turn to face target, drive, re-correct from camera | Click a spot, the toy drives there within ~1 cm |
| 6. Dig / dump task | State machine: go to pile, boom down, dig, boom up, go to dump, rotate, dump | Moves rice/sand from A to B unattended |
| 7. Learning (GPUs) | Object detection for the pile without markers; learned policies from teleop demos | Later |

The controller talks to the excavator through the same `ui/server.py` API, so the control panel stays usable (and the Stop button still works) while autonomy runs.
