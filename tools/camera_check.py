#!/usr/bin/env python3
"""Find the iPhone (Continuity Camera) or webcam and test ArUco marker detection.

  pip install opencv-contrib-python
  python3 tools/camera_check.py --list        # which camera number is which
  python3 tools/camera_check.py --cam 1       # live view with marker detection

Window keys: q quit, s save snapshot to captures/.
"""
import argparse
import os
import time

import cv2

DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)


def list_cams(n=6):
    for i in range(n):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ok, frame = cap.read()
            if ok:
                h, w = frame.shape[:2]
                print(f"camera {i}: {w}x{h}")
            else:
                print(f"camera {i}: opens but no image yet (try again)")
        cap.release()
    print("\nThe iPhone is usually the highest number, or the one with 1920x1080.")


def live(index):
    cap = cv2.VideoCapture(index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    if not cap.isOpened():
        raise SystemExit(f"camera {index} did not open")
    det = cv2.aruco.ArucoDetector(DICT, cv2.aruco.DetectorParameters())
    t0, n, fps = time.time(), 0, 0.0
    os.makedirs("captures", exist_ok=True)
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        corners, ids, _ = det.detectMarkers(frame)
        if ids is not None:
            cv2.aruco.drawDetectedMarkers(frame, corners, ids)
        n += 1
        if time.time() - t0 >= 1:
            fps, n, t0 = n / (time.time() - t0), 0, time.time()
        found = "none" if ids is None else ",".join(str(i) for i in sorted(ids.flatten()))
        cv2.putText(frame, f"{fps:4.1f} fps   markers: {found}", (20, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (11, 185, 246), 3)
        cv2.imshow("camera check (q quit, s snapshot)", frame)
        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            break
        if k == ord("s"):
            p = f"captures/snapshot-{int(time.time())}.png"
            cv2.imwrite(p, frame)
            print("saved", p)
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--cam", type=int, default=0)
    a = ap.parse_args()
    list_cams() if a.list else live(a.cam)
