"""Tunable settings. Edited live from the dashboard, saved to autonomy/config.json."""
import copy
import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULTS = {
    "camera_index": 0,
    "square_cm": 60.0,            # side of the pink tape square (outer edge to outer edge)
    # HSV ranges, OpenCV scale: H 0-179, S 0-255, V 0-255. Several ranges per colour allowed.
    "hsv": {
        "pink":   [[140, 70, 90, 179, 255, 255], [0, 70, 90, 6, 255, 255]],
        "green":  [[38, 60, 50, 88, 255, 255]],
        "yellow": [[16, 90, 110, 36, 255, 255]],
    },
    "robot_min_area_px": 120,
    # motion
    "drive_speed": 22,            # throttle for autonomous driving (15-50)
    "turn_speed": 18,
    "calib_drive_s": 0.6,
    "calib_turn_s": 0.45,
    "max_drive_pulse_s": 0.7,
    "max_turn_pulse_s": 0.35,
    "settle_s": 0.35,             # wait after each pulse before looking
    "heading_tol_deg": 18,
    "goal_tol_cm": 3.5,
    "bucket_offset_cm": 5.0,      # bucket is this far ahead of the blob centre
    # actions: [action, seconds]. Actions: forward back left right bucket_up bucket_down turret_left turret_right
    "dig":  [["bucket_down", 0.8], ["forward", 0.35], ["bucket_up", 0.9]],
    "dump": [["turret_left", 1.0], ["bucket_down", 0.6], ["bucket_up", 0.8], ["turret_right", 1.0]],
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
