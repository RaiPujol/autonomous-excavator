# Phase 1: Reverse engineering the control protocol

Target: Trasped 1:64 RC excavator (HG4-301 / HG4-413 family). Spec sheets list "2.4G remote + mobile app dual control", 4 channels, 3.7 V 200 mAh battery, ~20 min runtime.

Hardware available: ESP32, Flipper Zero, phone, two GPU machines.

## Key point: attack the app, not the 2.4G remote

The toy is controlled two ways:

1. **2.4G remote.** Almost certainly a proprietary GFSK chip (XN297 / nRF24 / Beken style). Neither the ESP32 nor the Flipper can sniff this (Flipper's CC1101 is sub-GHz only, and the ESP32 radio only speaks real BLE/Wi-Fi). Skip it.
2. **Phone app over BLE.** The phone can log every Bluetooth byte it sends, for free. This is the path.

Cheap dual-control toys usually do one of two things over BLE:

| Mode | What happens | How to tell |
|---|---|---|
| **A. GATT connection** | Phone connects to the toy and writes bytes to a characteristic | The toy shows up in a BLE scan with a name, the app "connects" |
| **B. Advertising broadcast** | Phone never connects. It changes its BLE advertisement payload ~every button press. The toy's 2.4G receiver chip picks the advertisement up as if it were a remote packet (often whitened/XOR'd) | Toy does not show up as connectable; the phone's own adverts change when you press buttons |

Mode B is common on HG/HuiNa-style 1:64 toys because one cheap receiver chip serves both the remote and the app. The capture method below works for both.

## Findings so far

- App: **RCCar**, `com.DeliMiniChe.carapp` (developer JIACHENG / Hainan Yunyu Technology). The listing advertises "stable 2.4G transmission" from the phone with no dongle, which strongly suggests **Mode B (advertising broadcast)**.
- No Android phone available. Primary capture path is now **iPhone running the app + laptop sniffing adverts** with `tools/ble_sniff.py`.
- iOS apps cannot put arbitrary manufacturer data in adverts, so on iPhone the command is probably encoded in the **advertised service UUID list** or local name. Watch the `uuids=` field.

## Step 0b: iPhone + laptop capture (no Android, no ESP32 needed)

```bash
pip install bleak
python3 tools/ble_sniff.py --rssi -45 --log captures/session-01.jsonl
```

1. Hold the iPhone right next to the laptop, app in the foreground (iOS stops custom advertising in the background).
2. Run the sniffer first with the app closed for ~10 s, then open the app.
3. Before each action type a label + Enter (`idle`, `forward`, `stop`, ...), then do the action for ~2 s.
4. Ctrl+C. The device with the most distinct payloads is the phone. Re-run with `--addr <it>` for clean output.
5. Check the toy actually reacts during capture, so we know the frames are the real ones.

On macOS the address is a per-Mac UUID, not a MAC. That is fine for filtering.

## Step 0: Identify the app and the radio (15 min)

1. Note the app name from the manual/QR code and its package name (Play Store URL `id=...`).
2. Install **nRF Connect** on the phone. Power on the excavator, scan.
   - Toy appears with a name and is connectable → Mode A. Connect, note services/characteristics.
   - Nothing new appears → probably Mode B.
3. Flash `tools/esp32_ble_scanner` to the ESP32, open serial at 115200. Put the phone next to the ESP32 and press buttons in the app. If a device's advert payload changes per button, that is the phone broadcasting commands (Mode B).

## Step 1: Capture ground truth with the phone's HCI snoop log (main method)

Android:

1. Settings → About phone → tap Build number 7x → Developer options.
2. Enable **Bluetooth HCI snoop log** (set to "Enabled", not "Filtered"). Toggle Bluetooth off/on.
3. Open the app, run a **scripted session**, one action at a time with ~2 s gaps so they are easy to separate:
   - idle 5 s
   - forward, stop, back, stop, left, stop, right, stop
   - boom up/down, arm in/out, bucket in/out, swing left/right
   - lights, sound, speed 1/2
   Write the order and approximate times in `captures/session-01.md`.
4. Pull the log:
   ```bash
   adb bugreport bugreport.zip
   # log is inside at FS/data/misc/bluetooth/logs/btsnoop_hci.log
   ```
5. Parse it:
   ```bash
   python3 tools/parse_btsnoop.py btsnoop_hci.log --csv captures/session-01.csv
   ```
   The script prints every ATT write (Mode A) and every advertising-data change (Mode B) with timestamps. Line them up with your session notes.

iPhone: no on-device snoop log. Needs a Mac with Xcode's PacketLogger plus Apple's Bluetooth logging profile. If you only have an iPhone, use the ESP32 scanner (Mode B) or nRF Connect (Mode A) instead, and borrow an Android for one capture if possible.

## Step 2: Decode the frame

Typical structure to look for:

- Fixed header bytes (sync / ID / bound-address bytes that never change)
- One byte or nibble per channel (drive L/R tracks, swing, boom, arm, bucket) with a neutral value (0x00, 0x80, or 0x7F)
- Flags byte for lights / sound / speed
- A rolling counter and/or a checksum (sum, XOR, or CRC8/CRC16) at the end

Method: diff each action's frame against idle. Exactly one field should move per action. For Mode B, if bytes look random even at idle, the payload is whitened/XOR'd; decompile the app (Step 3) to get the key instead of guessing.

## Step 3: Decompile the APK to confirm (this is where REA fits)

The capture tells you *what* is sent; the APK tells you *why* (checksum algorithm, encryption key, pairing ID derivation).

1. Get the APK: `adb shell pm path <package>` then `adb pull <path>`.
2. Run REA (`npx rea-agents setup`, register with Claude Code or Cursor) and ask it to find where the app builds BLE packets: search for `writeCharacteristic`, `startAdvertising`, `AdvertiseData`, `addManufacturerData`, or a native `.so` doing the encoding.
3. If the encoder is in a native library (`lib*.so`), REA hands it to Ghidra.

REA does not need GPUs. It wraps JADX/Ghidra and runs on any laptop with Node 22+ and a JDK; your coding agent supplies the reasoning. The GPUs and Tailscale only matter if you insist on a local LLM as the agent, which is slower and weaker than Claude/Cursor for this. Save the GPUs for the autonomy phase (vision models).

## Step 4: Replay from the ESP32

- Mode A: ESP32 as BLE central, connect to the toy, write the decoded frame to the characteristic at the same rate the app does (usually 20-50 Hz).
- Mode B: ESP32 as BLE advertiser, broadcast the decoded payload, updating it at the app's rate. The phone app must be closed so it does not fight the ESP32.

Success = ESP32 drives forward/stop on command. Then expose a serial or Wi-Fi API (`drive(l, r)`, `swing(x)`, `boom(x)`, ...) so the autonomy stack can call it.

## Role of each tool

| Tool | Use |
|---|---|
| Phone | Run the app, HCI snoop log (ground truth), nRF Connect |
| ESP32 | Scanner during discovery; final controller (replay, later the bridge to the autonomy stack) |
| Laptop | Parse logs, REA/JADX decompile |
| Flipper Zero | Not useful here (no 2.4 GHz sniffing, no BLE sniffing). Only with an add-on nRF24 board, for the 2.4G remote |
| GPUs + Tailscale | Not needed for phase 1. Phase 2: run vision/policy models, ESP32 + camera stream to them over Tailscale |
