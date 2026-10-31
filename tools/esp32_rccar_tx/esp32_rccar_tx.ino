// ESP32 replacement for the RCCar app: broadcasts the same BLE advert frames.
// Close the RCCar app on the phone first, otherwise both fight.
//
// Serial Monitor 115200, line ending "Newline". Commands:
//   f [speed] [ms]   forward   (speed 0-50, default 50; ms default 1000)
//   b [speed] [ms]   back
//   l [ms] / r [ms]  left / right
//   u [ms] / d [ms]  bucket/arm up / down
//   tl [ms] / tr [ms] turret rotate left / right
//   light            toggle lights
//   s                stop now
// After [ms] it returns to idle automatically (safety).
//
// Frame (UUID string order): chk ctr 00 14 | A B | C D | ID(8)
//   chk = ctr ^ A ^ B ^ C ^ D ^ 0x08,  B = max(0, A - 16)
// Over the air a 128-bit UUID is little-endian, so the 16 bytes are sent reversed.

#include <BLEDevice.h>
#include "esp_gap_ble_api.h"

// Constant tail seen from Rai's iPhone. May be a pairing ID.
static const uint8_t ID[8] = {0x34, 0x30, 0x34, 0xb7, 0x06, 0x7f, 0x07, 0x0c};
static const char *NAME = "FF04";  // local name the iPhone app advertises

// Set to false if the raw ESP32 scan shows the iPhone sends no flags field.
static const bool SEND_FLAGS = true;

static uint8_t ctr = 0, A = 0, C = 0, D = 0;
static uint32_t stopAt = 0;
static esp_ble_adv_params_t params;

void buildAndSend() {
  uint8_t B = A > 16 ? A - 16 : 0;
  uint8_t f[16] = {0, ctr, 0x00, 0x14, A, B, C, D};
  memcpy(f + 8, ID, 8);
  f[0] = ctr ^ A ^ B ^ C ^ D ^ 0x08;

  uint8_t adv[31];
  int n = 0;
  if (SEND_FLAGS) { adv[n++] = 2; adv[n++] = 0x01; adv[n++] = 0x1A; }
  adv[n++] = 17; adv[n++] = 0x07;                 // complete list of 128-bit UUIDs
  for (int i = 15; i >= 0; i--) adv[n++] = f[i];  // little-endian on air
  int nl = strlen(NAME);
  adv[n++] = nl + 1; adv[n++] = 0x09;             // complete local name
  memcpy(adv + n, NAME, nl); n += nl;

  esp_ble_gap_config_adv_data_raw(adv, n);
  ctr++;
}

void setCmd(uint8_t a, uint8_t d, uint32_t ms) {
  A = a; D = d;
  stopAt = ms ? millis() + ms : 0;
  Serial.printf("A=%u C=%02x D=%02x for %lu ms\n", A, C, D, (unsigned long)ms);
}

void handleSerial() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  char cmd[8] = {0};
  int x = -1, y = -1;
  sscanf(line.c_str(), "%7s %d %d", cmd, &x, &y);
  String c(cmd);
  if (c == "f" || c == "b") {
    int speed = x < 0 ? 50 : constrain(x, 0, 50);
    setCmd(speed, c == "f" ? 0x01 : 0x02, y < 0 ? 1000 : y);
  } else {
    uint32_t ms = x < 0 ? 1000 : x;
    if (c == "l") setCmd(0, 0x04, ms);
    else if (c == "r") setCmd(0, 0x08, ms);
    else if (c == "u") setCmd(0, 0x10, ms);
    else if (c == "d") setCmd(0, 0x20, ms);
    else if (c == "tl") setCmd(0, 0x40, ms);
    else if (c == "tr") setCmd(0, 0x80, ms);
    else if (c == "light") { C ^= 0x04; Serial.printf("lights %s\n", C ? "on" : "off"); }
    else if (c == "s") setCmd(0, 0, 0);
    else Serial.println("? f b l r u d tl tr light s");
  }
}

void setup() {
  Serial.begin(115200);
  BLEDevice::init("");
  memset(&params, 0, sizeof(params));
  params.adv_int_min = 0x20;  // 20 ms
  params.adv_int_max = 0x20;
  params.adv_type = ADV_TYPE_NONCONN_IND;
  params.own_addr_type = BLE_ADDR_TYPE_PUBLIC;
  params.channel_map = ADV_CHNL_ALL;
  params.adv_filter_policy = ADV_FILTER_ALLOW_SCAN_ANY_CON_ANY;
  buildAndSend();
  delay(50);
  esp_ble_gap_start_advertising(&params);
  Serial.println("rccar tx ready: f b l r u d tl tr light s");
}

void loop() {
  handleSerial();
  if (stopAt && (int32_t)(millis() - stopAt) >= 0) setCmd(0, 0, 0);
  static uint32_t last = 0;
  if (millis() - last >= 50) {  // new frame (counter++) every 50 ms
    last = millis();
    buildAndSend();
  }
}
