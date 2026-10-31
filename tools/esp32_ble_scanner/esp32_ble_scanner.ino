// ESP32 BLE advert scanner for discovery.
// Prints every advertisement from nearby devices (RSSI filter) with raw payload hex.
// Use it to see (a) whether the excavator advertises (GATT mode) and
// (b) whether the phone's adverts change when you press app buttons (broadcast mode).
//
// Arduino IDE: board "ESP32 Dev Module", Serial Monitor 115200.
// Send over serial:  r<number>  set RSSI threshold (e.g. r-60)
//                    m<mac>     only show this MAC (e.g. m11:22:33:44:55:66), "m" alone clears
//                    c          toggle change-only mode (print only when payload changes)

#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <map>

static int rssiMin = -55;          // keep only things close to the ESP32
static String macFilter = "";
static bool changeOnly = true;
static std::map<std::string, std::string> lastPayload;

class Cb : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice d) override {
    if (d.getRSSI() < rssiMin) return;
    std::string mac = d.getAddress().toString().c_str();
    if (macFilter.length() && macFilter != mac.c_str()) return;

    uint8_t *p = d.getPayload();
    size_t n = d.getPayloadLength();
    char hex[3 * 64 + 1];
    size_t k = 0;
    for (size_t i = 0; i < n && i < 64; i++) k += sprintf(hex + k, "%02x ", p[i]);
    hex[k] = 0;
    std::string h(hex);

    if (changeOnly && lastPayload[mac] == h) return;
    lastPayload[mac] = h;

    Serial.printf("%10lu  %s  rssi=%4d  %-12s  %s\n", millis(), mac.c_str(), d.getRSSI(),
                  d.haveName() ? d.getName().c_str() : "-", hex);
  }
};

BLEScan *scan;

void handleSerial() {
  if (!Serial.available()) return;
  String s = Serial.readStringUntil('\n');
  s.trim();
  if (s.startsWith("r")) { rssiMin = s.substring(1).toInt(); Serial.printf("rssiMin=%d\n", rssiMin); }
  else if (s.startsWith("m")) { macFilter = s.substring(1); macFilter.toLowerCase(); Serial.printf("mac=%s\n", macFilter.c_str()); }
  else if (s == "c") { changeOnly = !changeOnly; Serial.printf("changeOnly=%d\n", changeOnly); }
}

void setup() {
  Serial.begin(115200);
  BLEDevice::init("");
  scan = BLEDevice::getScan();
  scan->setAdvertisedDeviceCallbacks(new Cb(), true);  // true = report duplicates
  scan->setActiveScan(true);
  scan->setInterval(100);
  scan->setWindow(99);
  Serial.println("scanner ready");
}

void loop() {
  handleSerial();
  scan->start(1, false);
  scan->clearResults();
}
