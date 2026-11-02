"""Tunable settings. Edited live from the dashboard, saved to autonomy/config.json."""
import copy
import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULTS = {
    "camera_index": 0,
    "arena_mode": "auto",         # auto (uniform surface, e.g. blanket) | corners (clicked) | pink (tape square)
    "arena_w_cm": 100.0,          # work area width, left-right as seen from the camera
    "arena_h_cm": 70.0,           # work area depth, far-near as seen from the camera
    "arena_corners": None,        # 4 clicked corners, normalised image coords
    "arena_tol": 14,              # colour tolerance for auto arena
    "arena_shrink": 0.96,         # ignore the outer 4% of the arena when looking for the robot
    "green_targets": True,        # use green tape squares as A/B if present
    "manual_targets": {},         # A/B placed by clicking, map cm
    "square_cm": 60.0,            # pink mode only
    # HSV ranges, OpenCV scale: H 0-179, S 0-255, V 0-255. Several ranges per colour allowed.
    "hsv": {
        "pink":   [[140, 70, 90, 179, 255, 255], [0, 70, 90, 6, 255, 255]],
        "green":  [[38, 60, 50, 88, 255, 255]],
        "yellow": [[16, 90, 110, 36, 255, 255]],
    },
    "robot_min_area_px": 120,
    "robot_len_cm": 11.0,         # real length of the toy, used as the ruler in camera-view mode
    # motion
    "drive_speed": 22,            # throttle for autonomous driving (15-50)
    "turn_speed": 18,
    "calib_drive_s": 0.6,
    "calib_turn_s1": 0.15,        # calibration spins: two lengths each way -> spin rate + motor dead time
    "calib_turn_s2": 0.30,        #   (kept short so even a fast toy turns < 90 deg per pulse)
    "calib_track_diff": 12,       # calibration: forward with tracks A/B = arc_speed +/- 6 to learn steering
    "arc_speed": 30,              # average track speed when steering while driving
    "arc_gain": 1.5,              # deg/s of turn per deg of heading error
    "arc_max_turn_deg_s": 60,
    "spin_tol_deg": 60,           # spin in place only if the target is more than this off the nose
    "spin_aim": 0.8,              # spin this fraction of the error (overshoot is worse than undershoot)
    "max_spin_deg": 60,           # max turn per spin pulse (must stay < 90 to read it from the long axis)
    "near_cm": 12,                # closer than this: spin then go straight (target inside the turning circle)
    "probe_sd_deg": 25,           # heading this uncertain: drive a short probe to re-measure it
    "skew_min": 0.08,             # blob lopsidedness needed to trust the arm side
    "arm_offset_max_deg": 20,     # calibration: arm this far from the drive direction = arm reading unreliable
    "max_steps": 60,
    "max_drive_pulse_s": 0.7,
    "max_turn_pulse_s": 0.35,
    "settle_s": 0.35,             # wait after each pulse before looking
    "min_drive_pulse_s": 0.1,     # raise both (e.g. 0.3) for "gentle mode": fewer, longer motor starts
    "min_turn_pulse_s": 0.08,     #   (helps if the toy browns out / switches off on a weak battery)
    "heading_tol_deg": 18,
    "goal_tol_cm": 3.5,
    "bucket_offset_cm": 5.0,      # bucket is this far ahead of the blob centre
    # actions: [action, seconds]. Actions: forward back left right bucket_up bucket_down turret_left turret_right
    "dig":  [["bucket_down", 0.8], ["forward", 0.35], ["bucket_up", 0.9]],
    "dump": [["turret_left", 1.0], ["bucket_down", 0.6], ["bucket_up", 0.8], ["turret_right", 1.0]],
    "vlm_model": "claude-sonnet-5-5",   # needs ANTHROPIC_API_KEY
}


def load():
    cfg = copy.deepcopy(DEFAULTS)
    if os.path.exists(PATH):
        try:
            with open(PATH) as f:
                cfg.update(json.load(f))
        except (OSError, json.JSONDecodeError):
            pass
    return cfg


def save(cfg):
    with open(PATH, "w") as f:
        json.dump(cfg, f, indent=2)
