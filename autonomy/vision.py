"""Scene + robot perception, no markers.

Scene: pink tape square of known size -> homography image <-> map (cm, top-down).
       Two green tape squares inside -> targets A and B.
Robot: largest yellow blob inside the pink square, measured in map coordinates
       (centre, long-axis angle mod 180, elongation).
Map frame: origin at the pink square's image-top-left corner, x right, y "down"
(towards the camera), units cm.
"""
import math
from dataclasses import dataclass, field

import cv2
import numpy as np


def color_mask(hsv, ranges):
    m = np.zeros(hsv.shape[:2], np.uint8)
    for r in ranges:
        m |= cv2.inRange(hsv, np.array(r[:3], np.uint8), np.array(r[3:], np.uint8))
    return m


def order_corners(pts):
    pts = np.asarray(pts, np.float32).reshape(-1, 2)
    s, d = pts.sum(1), pts[:, 1] - pts[:, 0]
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]],
                    np.float32)  # tl, tr, br, bl


def quad_from_contour(c):
    hull = cv2.convexHull(c)
    peri = cv2.arcLength(hull, True)
    for eps in np.linspace(0.01, 0.12, 23):
        ap = cv2.approxPolyDP(hull, eps * peri, True)
        if len(ap) == 4:
            return order_corners(ap)
    return None


def to_map(H, pts):
    pts = np.asarray(pts, np.float32).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(pts, H).reshape(-1, 2)


@dataclass
class Scene:
    ok: bool = False
    msg: str = "not detected"
    square_cm: float = 60.0
    corners_img: np.ndarray = None       # 4x2 tl tr br bl
    H: np.ndarray = None                 # image -> map
    Hinv: np.ndarray = None
    targets: dict = field(default_factory=dict)  # "A"/"B" -> {"center":[x,y], "poly":[[x,y]...]} in cm

    def to_json(self):
        return {"ok": self.ok, "msg": self.msg, "square_cm": self.square_cm,
                "targets": self.targets}


def detect_scene(frame, cfg, swap=False):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    S = float(cfg["square_cm"])
    sc = Scene(square_cm=S)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    pink = cv2.morphologyEx(color_mask(hsv, cfg["hsv"]["pink"]), cv2.MORPH_CLOSE, k)
    cs, _ = cv2.findContours(pink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        sc.msg = "no pink tape found (check lighting / pink HSV)"
        return sc
    c = max(cs, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.01 * frame.shape[0] * frame.shape[1]:
        sc.msg = "pink found but too small; is the whole square in view?"
        return sc
    q = quad_from_contour(c)
    if q is None:
        sc.msg = "pink tape is not a clean 4-corner shape"
        return sc
    dst = np.array([[0, 0], [S, 0], [S, S], [0, S]], np.float32)
    sc.corners_img = q
    sc.H = cv2.getPerspectiveTransform(q, dst)
    sc.Hinv = np.linalg.inv(sc.H)

    green = cv2.morphologyEx(color_mask(hsv, cfg["hsv"]["green"]), cv2.MORPH_CLOSE, k)
    gs, _ = cv2.findContours(green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    found = []
    for g in sorted(gs, key=cv2.contourArea, reverse=True):
        poly = to_map(sc.H, cv2.convexHull(g))
        if len(poly) < 3:
            continue
        cx, cy = poly.mean(0)
        area = cv2.contourArea(poly.astype(np.float32))
        if 0 < cx < S and 0 < cy < S and area > 9:  # > 3x3 cm, inside the pink square
            q2 = quad_from_contour(g)
            p = to_map(sc.H, q2) if q2 is not None else poly
            found.append({"center": [float(p[:, 0].mean()), float(p[:, 1].mean())],
                          "poly": p.round(2).tolist()})
        if len(found) == 2:
            break
    if len(found) < 2:
        sc.ok = True
        sc.msg = f"square OK, but found {len(found)}/2 green squares"
        for name, t in zip("AB", sorted(found, key=lambda t: t["center"][0])):
            sc.targets[name] = t
        return sc
    found.sort(key=lambda t: t["center"][0])        # A = left one in the map
    if swap:
        found.reverse()
    sc.targets = {"A": found[0], "B": found[1]}
    sc.ok = True
    sc.msg = "scene OK"
    return sc


@dataclass
class RobotObs:
    t: float
    center: tuple          # cm, map
    axis_deg: float        # long axis, mod 180
    elong: float           # sqrt(l1/l2); <1.3 means axis is unreliable
    area_cm2: float
    contour_img: np.ndarray = None


def detect_robot(frame, scene, cfg, t=0.0):
    if not scene.ok:
        return None
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    y = color_mask(hsv, cfg["hsv"]["yellow"])
    roi = np.zeros_like(y)
    cv2.fillConvexPoly(roi, scene.corners_img.astype(np.int32), 255)
    y &= roi
    y = cv2.morphologyEx(y, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    y = cv2.morphologyEx(y, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    cs, _ = cv2.findContours(y, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea)
    if cv2.contourArea(c) < cfg["robot_min_area_px"]:
        return None
    blob = np.zeros_like(y)
    cv2.drawContours(blob, [c], -1, 255, -1)
    ys, xs = np.nonzero(blob)
    if len(xs) > 3000:
        idx = np.random.default_rng(0).choice(len(xs), 3000, replace=False)
        xs, ys = xs[idx], ys[idx]
    P = to_map(scene.H, np.stack([xs, ys], 1).astype(np.float32))
    mu = P.mean(0)
    cov = np.cov((P - mu).T)
    w, v = np.linalg.eigh(cov)
    major = v[:, 1]
    axis = math.degrees(math.atan2(major[1], major[0])) % 180
    elong = math.sqrt(max(w[1], 1e-6) / max(w[0], 1e-6))
    poly = to_map(scene.H, c)
    return RobotObs(t=t, center=(float(mu[0]), float(mu[1])), axis_deg=axis, elong=elong,
                    area_cm2=float(cv2.contourArea(poly.astype(np.float32))), contour_img=c)


# ---------- drawing helpers ----------
PINK, GREEN, YEL, WHITE, CYAN = (180, 80, 255), (90, 220, 90), (11, 185, 246), (255, 255, 255), (255, 220, 60)


def map_to_img(scene, pts):
    return to_map(scene.Hinv, pts)


def draw_overlay(frame, scene, obs=None, pose=None, target=None, path=None):
    img = frame.copy()
    if scene is not None and scene.ok:
        cv2.polylines(img, [scene.corners_img.astype(np.int32)], True, PINK, 3)
        for name, t in scene.targets.items():
            p = map_to_img(scene, t["poly"]).astype(np.int32)
            cv2.polylines(img, [p], True, GREEN, 3)
            c = map_to_img(scene, [t["center"]])[0].astype(int)
            cv2.putText(img, name, (c[0] - 12, c[1] + 12), cv2.FONT_HERSHEY_SIMPLEX, 1.3, WHITE, 6)
            cv2.putText(img, name, (c[0] - 12, c[1] + 12), cv2.FONT_HERSHEY_SIMPLEX, 1.3, GREEN, 3)
        if path:
            pp = map_to_img(scene, path).astype(np.int32)
            cv2.polylines(img, [pp], False, CYAN, 2)
        if target is not None:
            c = map_to_img(scene, [target])[0].astype(int)
            cv2.drawMarker(img, tuple(int(v) for v in c), CYAN, cv2.MARKER_CROSS, 28, 3)
    if obs is not None and obs.contour_img is not None:
        cv2.drawContours(img, [obs.contour_img], -1, YEL, 2)
    if pose is not None and scene is not None and scene.ok:
        x, y, h = pose
        a = math.radians(h)
        tip = (x + 8 * math.cos(a), y + 8 * math.sin(a))
        p0, p1 = map_to_img(scene, [(x, y), tip]).astype(int)
        cv2.arrowedLine(img, tuple(int(v) for v in p0), tuple(int(v) for v in p1), WHITE, 6, tipLength=0.35)
        cv2.arrowedLine(img, tuple(int(v) for v in p0), tuple(int(v) for v in p1), (40, 40, 255), 3, tipLength=0.35)
    return img


def mask_view(frame, cfg, scene=None):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    out = (frame * 0.15).astype(np.uint8)
    for name, col in (("pink", PINK), ("green", GREEN), ("yellow", YEL)):
        m = color_mask(hsv, cfg["hsv"][name]) > 0
        out[m] = col
    return out


def topdown_view(frame, scene, px_per_cm=8):
    S = scene.square_cm
    n = int(S * px_per_cm)
    A = np.diag([px_per_cm, px_per_cm, 1.0]) @ scene.H
    return cv2.warpPerspective(frame, A, (n, n))
