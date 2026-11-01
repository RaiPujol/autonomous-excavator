# Control panel: how to use it

Drive the excavator from your Mac's browser, your iPhone's browser, or a gamepad.

## First time setup (once)

Open Terminal and run these one at a time:

```bash
cd ~
git clone https://github.com/RaiPujol/autonomous-excavator.git
```
Downloads the project into a folder called `autonomous-excavator` in your home folder.

```bash
pip install pyobjc-framework-CoreBluetooth
```
The Mac Bluetooth library. Already installed if you installed `bleak` before.

Also allow Bluetooth for Terminal: System Settings → Privacy & Security → Bluetooth → Terminal on.

## Every time

1. **Close the RCCar app** on the iPhone (swipe it away). Otherwise the phone and the Mac fight.
2. Turn the excavator on.
3. In Terminal:
   ```bash
   cd ~/autonomous-excavator
   git pull
   python3 ui/server.py
   ```
   `git pull` gets the latest version. The last line starts the panel.
4. Open **http://localhost:8000** in the browser.
5. When done: Ctrl+C in Terminal.

## Controls

| Input | Action |
|---|---|
| `W` `S` | Drive forward / back |
| `A` `D` | Spin left / right |
| `↑` `↓` | Boom up / down |
| `←` `→` | Turret rotate left / right |
| `1` to `5` | Throttle 15, 24, 33, 42, 50 |
| `[` `]` | Trim (straighten the drive) |
| `L` | Lights |
| `Space` | Stop everything |

Mouse/touch: hold a button to move, release to stop. Several at once is fine.

Gamepad (PS/Xbox paired with the Mac): left stick drives (push further = faster), right stick works the arm, A = lights, B = stop.

## Settings in the Drive card

- **Throttle** (15-50) sets the speed for driving **and** spin turns. Below 15 the tracks stall, so 15 is the floor.
- **Turn speed: THROTTLE / PULSE.** THROTTLE sends the throttle value on turns. If turns still feel full speed whatever the throttle, switch to PULSE: it switches the turn on and off quickly so the average speed follows the throttle (a bit jerkier).
- **Trim.** If forward curves, nudge with `[` `]` until it drives straight. Remembered by the browser. Click STRAIGHT to reset.

## From the iPhone

The server prints a second address, like `http://192.168.1.23:8000`. Open it in Safari on the iPhone (same Wi-Fi), turn the phone sideways for the controller layout.

## Safety

If the page stops talking to the server for 0.4 s (tab closed, Wi-Fi drop), the excavator stops by itself.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Bluetooth not ready` | Bluetooth on? Terminal allowed in Privacy & Security → Bluetooth? |
| Page shows OFFLINE | The Terminal running `ui/server.py` was closed. Start it again |
| Excavator jerks or ignores you | RCCar app still open on the phone. Close it |
| `address already in use` | Another panel is still running. Ctrl+C it, or use `python3 ui/server.py --port 8001` |
