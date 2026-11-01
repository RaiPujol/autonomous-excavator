"""Natural-language commands -> plan, using a vision-language model (Claude).

The model sees the camera image with the map grid drawn on it, the robot pose,
and the named targets, and returns a short JSON plan that the existing
navigation executes. It never drives the motors directly.

Needs: pip install anthropic, and ANTHROPIC_API_KEY in the environment.
"""
import base64
import json
import os
import re

import cv2

from . import vision

ACTIONS = """Available steps (JSON objects):
  {"do": "goto", "x": <number>, "y": <number>}        drive so the bucket ends at map point (x, y)
  {"do": "goto_target", "name": "A"}                  drive to a named target
  {"do": "set_target", "name": "A", "x": .., "y": ..} create/move a named target
  {"do": "dig"}                                       dig at the current spot
  {"do": "dump"}                                      dump at the current spot
  {"do": "lights", "on": true}
  {"do": "wait", "seconds": 1.0}"""

PROMPT = """You are the planner for a small toy excavator (1 DOF boom, tracks, rotating cab) on the floor.
The image is from a phone camera at an angle. A white grid of map coordinates is drawn on it:
labels are "x,y" in map units (~cm). The cyan outline is the allowed work area. The robot is the
yellow toy; its heading is the red arrow.

Robot: position ({x:.1f}, {y:.1f}), heading {h} (0 = +x, 90 = +y).
Named targets: {targets}
Work area: points must lie inside the cyan outline, at least 6 units from its edge.

{actions}

User request: "{text}"

Reply with ONLY a JSON object, no prose around it:
{{"say": "<one short sentence: what you will do>", "steps": [ ... ]}}
If the request is impossible or unclear, return {{"say": "<why>", "steps": []}}."""


def make_image(frame, scene, obs, pose):
    img = vision.draw_overlay(frame, scene, obs, pose)
    img = vision.grid_view(img, scene)
    if img.shape[1] > 1280:
        s = 1280 / img.shape[1]
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(jpg.tobytes()).decode()


def plan(frame, scene, obs, pose, targets, text, cfg):
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("pip install anthropic")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("set ANTHROPIC_API_KEY before starting the dashboard")
    if pose is None and obs is None:
        raise RuntimeError("robot not visible")
    if pose is None:
        pose, heading = (obs.center[0], obs.center[1], 0.0), "unknown (not calibrated yet)"
    else:
        heading = f"{pose[2]:.0f} deg"
    tg = {k: [round(v, 1) for v in t["center"]] for k, t in targets.items()} or "none"
    prompt = PROMPT.format(x=pose[0], y=pose[1], h=heading, targets=tg, actions=ACTIONS, text=text)
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=cfg.get("vlm_model", "claude-sonnet-5-5"),
        max_tokens=800,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": make_image(frame, scene, obs, pose)}},
            {"type": "text", "text": prompt}]}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise RuntimeError(f"planner gave no JSON: {raw[:200]}")
    out = json.loads(m.group(0))
    return validate(out, scene)


def validate(p, scene):
    import numpy as np
    roi = np.array(scene.roi_map, np.float32)
    steps = []
    for s in p.get("steps", [])[:20]:
        d = s.get("do")
        if d in ("goto", "set_target"):
            x, y = float(s["x"]), float(s["y"])
            if cv2.pointPolygonTest(roi, (x, y), False) < 0:
                raise RuntimeError(f"planner chose ({x:.0f}, {y:.0f}), outside the work area")
            s["x"], s["y"] = x, y
        if d in ("goto", "goto_target", "set_target", "dig", "dump", "lights", "wait"):
            steps.append(s)
    return {"say": str(p.get("say", ""))[:200], "steps": steps}
