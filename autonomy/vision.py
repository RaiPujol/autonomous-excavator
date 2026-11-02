"""Scene + robot perception, no markers.

Arena (work area) = any rectangle on the floor, found one of three ways:
  "auto"    the big uniform region under the robot (e.g. a blanket)
  "corners" 4 corners clicked on the camera image
  "pink"    a pink tape square
Its real size (width x depth, cm) turns the angled camera image into a top-down
map in cm via a homography. Targets A/B come from clicks (or green tape squares).
Robot = largest yellow blob inside the arena.
Map frame: origin at the arena's far-left corner as seen by the camera, x right,
y towards the camera, units cm.
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
    """tl, tr, br, bl as seen in the image, robust to rotation."""
    pts = np.asarray(pts, np.float32).reshape(-1, 2)
    c = pts.mean(0)
    ang = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    pts = pts[np.argsort(ang)]                      # clockwise on screen (y down)
    start = int(np.argmin(pts.sum(1)))
    return np.roll(pts, -start, axis=0)


def quad_from_contour(c):
    hull = cv2.convexHull(c)
    peri = cv2.arcLength(hull, True)
    for eps in np.linspace(0.01, 0.15, 29):
        ap = cv2.approxPolyDP(hull, eps * peri, True)
        if len(ap) == 4:
            return order_corners(ap)
    # fallback: best 4-gon = min-area rectangle of the hull
    return order_corners(cv2.boxPoints(cv2.minAreaRect(hull)))


def to_map(H, pts):
    pts = np.asarray(pts, np.float32).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(pts, H).reshape(-1, 2)


@dataclass
class Scene:
    ok: bool = False
    msg: str = "not detected"
    w_cm: float = 100.0
    h_cm: float = 70.0
    source: str = ""
    corners_img: np.ndarray = None       # 4x2 tl tr br bl (metric modes only)
    roi_img: np.ndarray = None           # Nx2 polygon: where the robot may be (image px)
    roi_map: list = None                 # same polygon in map units, for drawing
    metric: bool = True                  # False = camera-view mode, scale from robot size
    H: np.ndarray = None                 # image -> map
    Hinv: np.ndarray = None
    targets: dict = field(default_factory=dict)  # name -> {"center":[x,y], "poly":[[x,y]...]} cm

    def to_json(self):
        return {"ok": self.ok, "msg": self.msg, "w_cm": self.w_cm, "h_cm": self.h_cm,
                "source": self.source, "targets": self.targets, "metric": self.metric, "roi_map": self.roi_map,
                "corners_img": None if self.corners_img is None else self.corners_img.round(1).tolist()}


def scene_from_corners(corners_img, w_cm, h_cm, source):
    sc = Scene(w_cm=float(w_cm), h_cm=float(h_cm), source=source)
    q = order_corners(corners_img)
    dst = np.array([[0, 0], [w_cm, 0], [w_cm, h_cm], [0, h_cm]], np.float32)
    sc.corners_img = q
    sc.roi_img = q.copy()
    sc.H = cv2.getPerspectiveTransform(q, dst)
    sc.Hinv = np.linalg.inv(sc.H)
    sc.roi_map = dst.tolist()
    sc.ok = True
    sc.msg = f"arena OK ({source}, {w_cm:.0f}x{h_cm:.0f} cm)"
    return sc


def robot_length_px(frame, roi, cfg):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    y = color_mask(hsv, cfg["hsv"]["yellow"]) & roi
    y = cv2.morphologyEx(y, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    cs, _ = cv2.findContours(y, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea)
    if cv2.contourArea(c) < cfg["robot_min_area_px"]:
        return None
    pts = c.reshape(-1, 2).astype(np.float32)
    (_, (w, h), _) = cv2.minAreaRect(pts)
    return max(w, h)


def scene_camera_view(frame, region_contour, cfg):
    """No known rectangle: work in the camera view, scaled so the robot is ~robot_len_cm long."""
    fh, fw = frame.shape[:2]
    roi = np.zeros((fh, fw), np.uint8)
    cv2.drawContours(roi, [region_contour], -1, 255, -1)
    L = robot_length_px(frame, roi, cfg)
    s = cfg.get("robot_len_cm", 11.0) / L if L else 100.0 / fw     # cm per px (near the robot)
    sc = Scene(w_cm=fw * s, h_cm=fh * s, source="auto", metric=False)
    sc.H = np.diag([s, s, 1.0])
    sc.Hinv = np.linalg.inv(sc.H)
    poly = cv2.approxPolyDP(region_contour, 0.004 * cv2.arcLength(region_contour, True), True).reshape(-1, 2)
    sc.roi_img = poly.astype(np.float32)
    sc.roi_map = (poly * s).round(2).tolist()
    sc.ok = True
    sc.msg = "work area OK (camera view, scale from robot size)" if L else \
             "work area OK (camera view; put the robot in to set the scale)"
    return sc


def detect_arena_auto(frame, cfg, seed=None):
    """Largest uniform-colour region around `seed` (default: image centre)."""
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(cv2.GaussianBlur(frame, (7, 7), 0), cv2.COLOR_BGR2HSV)
    sx, sy = seed if seed is not None else (w // 2, h // 2)
    r = max(20, min(w, h) // 8)
    patch = hsv[max(0, sy - r):sy + r, max(0, sx - r):sx + r].reshape(-1, 3).astype(np.int32)
    yellow = color_mask(patch.reshape(-1, 1, 3).astype(np.uint8), cfg["hsv"]["yellow"]).ravel() > 0
    patch = patch[~yellow] if (~yellow).sum() > 50 else patch      # ignore the robot itself
    h0, s0, v0 = np.median(patch, 0)
    tol = cfg.get("arena_tol", 14)
    dh = np.abs(hsv[..., 0].astype(np.int32) - int(h0))
    dh = np.minimum(dh, 180 - dh)
    if s0 < 35:   # grey/white surface: hue is meaningless, use brightness only
        m = (np.abs(hsv[..., 2].astype(np.int32) - int(v0)) < 2.2 * tol) & (hsv[..., 1] < 60)
    else:
        m = (dh < tol) & (hsv[..., 1] > max(25, s0 * 0.45)) & \
            (hsv[..., 2] > v0 * 0.35) & (hsv[..., 2] < min(255, v0 * 2.5 + 20))
    m = m.astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25)))
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cs = [c for c in cs if cv2.pointPolygonTest(c, (float(sx), float(sy)), False) >= 0] or cs
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.05 * w * h:
        return None
    return c


def detect_pink_square(frame, cfg):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    pink = cv2.morphologyEx(color_mask(hsv, cfg["hsv"]["pink"]), cv2.MORPH_CLOSE, k)
    cs, _ = cv2.findContours(pink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.01 * frame.shape[0] * frame.shape[1]:
        return None
    return quad_from_contour(c)


def find_green_targets(frame, sc, cfg):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    green = cv2.morphologyEx(color_mask(hsv, cfg["hsv"]["green"]), cv2.MORPH_CLOSE, k)
    gs, _ = cv2.findContours(green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    found = []
    for g in sorted(gs, key=cv2.contourArea, reverse=True):
        poly = to_map(sc.H, cv2.convexHull(g))
        if len(poly) < 3:
            continue
        cx, cy = poly.mean(0)
        area = cv2.contourArea(poly.astype(np.float32))
        inside = cv2.pointPolygonTest(np.array(sc.roi_map, np.float32), (float(cx), float(cy)), False) >= 0
        if inside and area > 25:   # > 5x5 cm
            q2 = quad_from_contour(g)
            p = to_map(sc.H, q2)
            found.append({"center": [float(p[:, 0].mean()), float(p[:, 1].mean())],
                          "poly": p.round(2).tolist()})
        if len(found) == 2:
            break
    return sorted(found, key=lambda t: t["center"][0])


def detect_scene(frame, cfg, swap=False):
    mode = cfg.get("arena_mode", "auto")
    if mode == "pink":
        q = detect_pink_square(frame, cfg)
        w = h = float(cfg["square_cm"])
        if q is None:
            return Scene(msg="no pink square found (check pink colour sliders)")
    elif mode == "corners":
        pts = cfg.get("arena_corners")
        if not pts or len(pts) != 4:
            return Scene(msg="click the 4 corners of the work area")
        fh, fw = frame.shape[:2]
        q = np.array([[u * fw, v * fh] for u, v in pts], np.float32)
        w, h = float(cfg["arena_w_cm"]), float(cfg["arena_h_cm"])
    else:
        c = detect_arena_auto(frame, cfg)
        if c is None:
            return Scene(msg="no uniform work area found; try CLICK CORNERS")
        q = None
        sc = scene_camera_view(frame, c, cfg)
    if q is not None:
        sc = scene_from_corners(q, w, h, mode)
    greens = find_green_targets(frame, sc, cfg) if cfg.get("green_targets", True) else []
    if len(greens) == 2:
        if swap:
            greens.reverse()
        sc.targets = {"A": greens[0], "B": greens[1]}
    return sc


def square_target(center, size=10.0):
    x, y = center
    s = size / 2
    return {"center": [float(x), float(y)],
            "poly": [[x - s, y - s], [x + s, y - s], [x + s, y + s], [x - s, y + s]]}


@dataclass
class RobotObs:
    t: float
    center: tuple          # cm, map
    axis_deg: float        # long axis, mod 180
    elong: float           # sqrt(l1/l2); <1.3 means axis is unreliable
    area_cm2: float
    contour_img: np.ndarray = None
    front_deg: float = 0.0     # full heading of the arm side, 0-360 (from blob asymmetry)
    skew: float = 0.0          # how lopsided the blob is; ~0 = front/back unknown, >0.3 = clear


def detect_robot(frame, scene, cfg, t=0.0):
    if not scene.ok:
        return None
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    y = color_mask(hsv, cfg["hsv"]["yellow"])
    roi = np.zeros_like(y)
    q = scene.roi_img
    if scene.metric:
        q = (q - q.mean(0)) * cfg.get("arena_shrink", 0.96) + q.mean(0)
    cv2.fillPoly(roi, [q.astype(np.int32)], 255)
    if not scene.metric:   # stay off the region border (floor leaks in there)
        e = max(3, int(0.012 * frame.shape[1]))
        roi = cv2.erode(roi, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * e + 1, 2 * e + 1)))
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
    # Front vs back: the arm sticks out one end only, so yellow pixels trail off
    # towards the front (positive skew along the long axis). Third moment, normalised.
    proj = (P - mu) @ major
    sd = float(proj.std()) or 1.0
    sk = float(np.mean((proj / sd) ** 3))
    front = math.degrees(math.atan2(major[1], major[0])) % 360
    if sk < 0:
        front = (front + 180) % 360
    poly = to_map(scene.H, c)
    return RobotObs(t=t, center=(float(mu[0]), float(mu[1])), axis_deg=axis, elong=elong,
                    area_cm2=float(cv2.contourArea(poly.astype(np.float32))), contour_img=c,
                    front_deg=front, skew=abs(sk))


# ---------- drawing helpers ----------
PINK, GREEN, YEL, WHITE, CYAN = (180, 80, 255), (90, 220, 90), (11, 185, 246), (255, 255, 255), (255, 220, 60)


def average_obs(got):
    """Average several RobotObs from consecutive frames (axis averaged mod 180,
    front direction averaged as a vector)."""
    if len(got) < 2:
        return None
    cx = sum(o.center[0] for o in got) / len(got)
    cy = sum(o.center[1] for o in got) / len(got)
    s = sum(math.sin(math.radians(2 * o.axis_deg)) for o in got)
    c = sum(math.cos(math.radians(2 * o.axis_deg)) for o in got)
    axis = (math.degrees(math.atan2(s, c)) / 2) % 180
    fx = sum(o.skew * math.cos(math.radians(o.front_deg)) for o in got)
    fy = sum(o.skew * math.sin(math.radians(o.front_deg)) for o in got)
    return RobotObs(t=got[-1].t, center=(cx, cy), axis_deg=axis,
                    elong=sum(o.elong for o in got) / len(got),
                    area_cm2=got[-1].area_cm2, contour_img=got[-1].contour_img,
                    front_deg=math.degrees(math.atan2(fy, fx)) % 360,
                    skew=math.hypot(fx, fy) / len(got))


def map_to_img(scene, pts):
    return to_map(scene.Hinv, pts)


def draw_overlay(frame, scene, obs=None, pose=None, target=None, path=None):
    img = frame.copy()
    if scene is not None and scene.ok:
        cv2.polylines(img, [scene.roi_img.astype(np.int32)], True, CYAN, 3)
        if scene.corners_img is not None:
            for p in scene.corners_img.astype(int):
                cv2.circle(img, tuple(int(v) for v in p), 9, CYAN, -1)
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


def topdown_view(frame, scene, px_per_cm=None, max_px=900):
    if not scene.metric:
        return frame          # camera-view mode: the map is the camera image
    if px_per_cm is None:
        px_per_cm = max_px / max(scene.w_cm, scene.h_cm)
    A = np.diag([px_per_cm, px_per_cm, 1.0]) @ scene.H
    return cv2.warpPerspective(frame, A, (int(scene.w_cm * px_per_cm), int(scene.h_cm * px_per_cm)))


def grid_view(frame, scene, step=10):
    """Camera image with the map-coordinate grid projected on it (for the VLM planner)."""
    img = frame.copy()
    col = (255, 255, 255)
    xs = range(0, int(scene.w_cm) + 1, step)
    ys = range(0, int(scene.h_cm) + 1, step)
    for x in xs:
        p = map_to_img(scene, [(x, 0), (x, scene.h_cm)]).astype(int)
        cv2.line(img, tuple(p[0]), tuple(p[1]), col, 1)
    for y in ys:
        p = map_to_img(scene, [(0, y), (scene.w_cm, y)]).astype(int)
        cv2.line(img, tuple(p[0]), tuple(p[1]), col, 1)
    for x in xs:
        for y in ys:
            if (x // step + y // step) % 2 == 0:
                p = map_to_img(scene, [(x, y)])[0].astype(int)
                cv2.putText(img, f"{x},{y}", (int(p[0]) + 2, int(p[1]) - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 0, 0), 3)
                cv2.putText(img, f"{x},{y}", (int(p[0]) + 2, int(p[1]) - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.38, col, 1)
    return img
