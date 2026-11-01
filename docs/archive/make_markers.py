#!/usr/bin/env python3
"""Make a printable A4/Letter sheet of ArUco markers (DICT_4X4_50).

  python3 tools/make_markers.py          # writes markers.pdf
  Print at 100% / "Actual size" (not "Fit to page").

ID 0       20 mm  -> stick on the excavator cab roof (front = top of the marker)
ID 1-4     40 mm  -> tape at the 4 corners of the work area (1 top-left, 2 top-right,
                     3 bottom-right, 4 bottom-left as seen by the camera)
ID 5-7     30 mm  -> spares: dig pile, dump spot, obstacles
"""
import cv2
import numpy as np

DPI = 300
MM = DPI / 25.4
W, H = int(210 * MM), int(279 * MM)  # fits both A4 and Letter
DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)

# (id, size_mm, x_mm, y_mm)
LAYOUT = [(0, 20, 20, 20), (0, 20, 55, 20), (0, 20, 90, 20),          # 3 spares for the toy
          (1, 40, 20, 70), (2, 40, 80, 70), (3, 40, 140, 70),
          (4, 40, 20, 135), (5, 30, 80, 135), (6, 30, 130, 135), (7, 30, 20, 200)]


def main():
    page = np.full((H, W), 255, np.uint8)
    for mid, size, x, y in LAYOUT:
        px = int(size * MM)
        m = cv2.aruco.generateImageMarker(DICT, mid, px)
        x0, y0 = int(x * MM), int(y * MM)
        page[y0:y0 + px, x0:x0 + px] = m
        cv2.putText(page, f"id {mid}  {size} mm", (x0, y0 + px + int(5 * MM)),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, 0, 2)
    cv2.putText(page, "Print at 100% (Actual size). Check: the 40 mm squares measure 40 mm.",
                (int(20 * MM), int(265 * MM)), cv2.FONT_HERSHEY_SIMPLEX, 1.1, 0, 2)
    cv2.imwrite("markers.png", page)
    try:
        from PIL import Image
        Image.fromarray(page).save("markers.pdf", resolution=DPI)
        print("wrote markers.pdf and markers.png")
    except ImportError:
        print("wrote markers.png (pip install pillow for a PDF). Print at 300 dpi, 100%.")


if __name__ == "__main__":
    main()
