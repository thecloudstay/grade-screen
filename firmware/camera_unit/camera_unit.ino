// 채점 카메라 장치 — XIAO ESP32-S3 Sense + OV5640 자동 초점(또는 OV3660)
//
// 흐름(대표 결정 2026-11-19: 전지 직결 + 깊은 잠)
//   깊은 잠 → 촬영 단추로 깨어남 → (길게 누름이면 「새 학생」만 알리고 다시 잠)
//   → 카메라 켜고 초점·촬영 → 카메라 끔 → 사진을 내부 저장소에 먼저 보관
//   → 와이파이(도시락 → 핫스팟, 지난번 채널로 빠른 재접속) → 중계기로 보냄(최대 170초 대기)
//   → 결과를 화면 장치로 무선 전송(받았다는 답이 올 때까지 반복) → 보관 사진 지움 → 깊은 잠
//   못 보낸 사진은 남겨 두고 5분마다 스스로 깨어 다시 보냄. 다시 켜져도(전압 떨어짐 등) 이어서 보냄.
//
// 보드 설정(아두이노): 「XIAO_ESP32S3」, PSRAM: OPI PSRAM, 파티션: 8M with spiffs(3MB APP/1.5MB SPIFFS)
// 필요한 꾸러미: (OV5640 자동 초점을 쓸 때) 「ESP32_OV5640_AF」 — 없으면 USE_OV5640_AF 를 0 으로
#define USE_OV5640_AF 1

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <esp_camera.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <esp_sleep.h>
#include <esp_task_wdt.h>
#include <driver/rtc_io.h>
#include <LittleFS.h>
#include <vector>
#include <algorithm>
#include <WebServer.h>
#include <Preferences.h>
#include "config.h"
#include "grade_link.h"
#if USE_OV5640_AF
#include "ESP32_OV5640_AF.h"
OV5640 ov5640;
#endif

// ── 깊은 잠을 건너 기억하는 값 ──
RTC_DATA_ATTR uint8_t rtcChannel = 0;      // 지난번 와이파이 채널(빠른 재접속·무선 채널)
RTC_DATA_ATTR uint8_t rtcBssid[6] = {0};
RTC_DATA_ATTR int8_t rtcWifiIdx = -1;      // 지난번 붙은 와이파이 순번
RTC_DATA_ATTR uint16_t rtcResultId = 0;    // 결과 번호
RTC_DATA_ATTR uint8_t rtcBootFails = 0;    // 연속 비정상 재시작 횟수(3번이면 안전 모드)

struct WifiCred { const char* ssid; const char* pass; };
static const WifiCred WIFI_DEFAULT[] = WIFI_LIST;
// 시험장에서 휴대폰으로 추가한 와이파이(최대 5개) + 기본 목록. 추가한 것이 먼저.
struct WifiSaved { String ssid, pass; };
static WifiSaved WIFI[10];
static int WIFI_N = 0;

static void loadWifiList() {
  Preferences p;
  p.begin("wifi", true);
  for (int i = 0; i < 5; i++) {
    String s = p.getString(("s" + String(i)).c_str(), "");
    if (s.length()) { WIFI[WIFI_N].ssid = s; WIFI[WIFI_N].pass = p.getString(("p" + String(i)).c_str(), ""); WIFI_N++; }
  }
  p.end();
  for (auto& d : WIFI_DEFAULT) if (WIFI_N < 10) { WIFI[WIFI_N].ssid = d.ssid; WIFI[WIFI_N].pass = d.pass; WIFI_N++; }
}

static volatile bool gotAck = false;
static volatile uint16_t ackId = 0;

// ───────────────────────── 작은 도우미 ─────────────────────────
static void led(bool on) { if (PIN_LED >= 0) digitalWrite(PIN_LED, on ? LOW : HIGH); }

static void blink(int n, int ms = 120) {
  for (int i = 0; i < n; i++) { led(true); delay(ms); led(false); delay(ms); }
}

static void goSleep(bool retryLater) {
  led(false);
  esp_now_deinit();
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  rtc_gpio_pullup_en((gpio_num_t)PIN_SHUTTER);
  rtc_gpio_pulldown_dis((gpio_num_t)PIN_SHUTTER);
  esp_sleep_enable_ext0_wakeup((gpio_num_t)PIN_SHUTTER, 0);   // 단추 누르면(접지) 깨어남
  if (retryLater) esp_sleep_enable_timer_wakeup((uint64_t)RETRY_SLEEP_S * 1000000ULL);
  rtcBootFails = 0;   // 정상적으로 잠들면 연속 실패 기록 지움
  esp_deep_sleep_start();
}

// ───────────────────────── 무선(화면 장치로) ─────────────────────────
static void onRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  if (len < (int)offsetof(GlPacket, payload)) return;
  const GlPacket* p = (const GlPacket*)data;
  if (p->magic != GL_MAGIC || p->group != GROUP_CODE) return;
  if (p->type == GL_ACK) { ackId = p->id; gotAck = true; }
}

static bool linkStart() {
  if (WiFi.getMode() == WIFI_OFF) WiFi.mode(WIFI_STA);
  if (!WiFi.isConnected()) {   // 와이파이 없이 보낼 때는 지난번 채널(없으면 1)
    esp_wifi_set_channel(rtcChannel ? rtcChannel : 1, WIFI_SECOND_CHAN_NONE);
  }
  if (esp_now_init() != ESP_OK) return false;
  esp_now_register_recv_cb(onRecv);
  esp_now_peer_info_t peer = {};
  memset(peer.peer_addr, 0xFF, 6);   // 방송(묶음 번호로 구별)
  peer.channel = 0;                  // 지금 채널
  peer.encrypt = false;
  esp_now_add_peer(&peer);
  return true;
}

static void sendPacket(uint8_t type, uint16_t id, uint8_t part, uint8_t total, const char* buf, size_t n) {
  GlPacket p = {};
  p.magic = GL_MAGIC; p.group = GROUP_CODE; p.type = type; p.id = id;
  p.part = part; p.total = total; p.len = (uint8_t)min(n, (size_t)GL_PAYLOAD);
  if (buf && p.len) memcpy(p.payload, buf, p.len);
  static const uint8_t bc[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
  esp_now_send(bc, (const uint8_t*)&p, offsetof(GlPacket, payload) + p.len);
}

// 상태는 화면 장치가 3초마다 잠깐 깨어 듣기 때문에 3.5초 동안 촘촘히 반복
static void sendStatus(const char* msg) {
  uint32_t t0 = millis();
  while (millis() - t0 < 3500) { sendPacket(GL_STATUS, 0, 0, 1, msg, strlen(msg)); delay(25); }
}

// 결과 글을 조각내 보내고, 화면 장치가 「다 받음」 할 때까지 반복(화면 장치는 2초마다 잠깐 깨어 들음)
static bool sendResult(const String& text) {
  uint16_t id = ++rtcResultId;
  size_t n = text.length();
  uint8_t total = (uint8_t)((n + GL_PAYLOAD - 1) / GL_PAYLOAD);
  if (total == 0) total = 1;
  gotAck = false;
  uint32_t t0 = millis();
  while (millis() - t0 < READY_BEACON_MS + 4000) {
    sendPacket(GL_READY, id, 0, total, nullptr, 0);   // 짧은 알림을 촘촘히
    delay(20);
    if (millis() - t0 > 300) {                        // 조각도 계속 돌려 보냄(놓친 조각 메우기)
      for (uint8_t i = 0; i < total; i++) {
        size_t off = (size_t)i * GL_PAYLOAD;
        sendPacket(GL_CHUNK, id, i, total, text.c_str() + off, min((size_t)GL_PAYLOAD, n - off));
        delay(4);
      }
    }
    if (gotAck && ackId == id) return true;
  }
  return false;
}

// ───────────────────────── 카메라 ─────────────────────────
static bool cameraStart() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0; c.ledc_timer = LEDC_TIMER_0;
  static const int P[] = { CAM_PINS };   // 보드별 배치(config.h)
  c.pin_d0 = P[0]; c.pin_d1 = P[1]; c.pin_d2 = P[2]; c.pin_d3 = P[3];
  c.pin_d4 = P[4]; c.pin_d5 = P[5]; c.pin_d6 = P[6]; c.pin_d7 = P[7];
  c.pin_xclk = P[8]; c.pin_pclk = P[9]; c.pin_vsync = P[10]; c.pin_href = P[11];
  c.pin_sccb_sda = P[12]; c.pin_sccb_scl = P[13];
  c.pin_pwdn = -1; c.pin_reset = -1;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = FRAMESIZE_UXGA;       // 1600×1200 — 중계기·시뮬레이터 기준 크기와 같음
  c.jpeg_quality = 10;
  c.fb_count = 1;
  c.fb_location = CAMERA_FB_IN_PSRAM;
  c.grab_mode = CAMERA_GRAB_LATEST;
  if (esp_camera_init(&c) != ESP_OK) return false;
  sensor_t* s = esp_camera_sensor_get();
  if (!s) return false;
#if USE_OV5640_AF
  if (s->id.PID == OV5640_PID) {
    ov5640.start(s);
    if (ov5640.focusInit() == 0) ov5640.autoFocusMode();
  }
#endif
  s->set_whitebal(s, 1);
  s->set_exposure_ctrl(s, 1);
  s->set_gain_ctrl(s, 1);
  return true;
}

// 촬영해서 내부 저장소에 보관. 성공하면 파일 이름
static String captureToQueue() {
  if (!cameraStart()) return "";
  // 노출·초점이 자리 잡을 때까지 몇 장 버림(자동 초점은 최대 약 1.5초 기다림)
  uint32_t t0 = millis();
  for (int i = 0; i < 4 || millis() - t0 < 1500; i++) {
    camera_fb_t* f = esp_camera_fb_get();
    if (f) esp_camera_fb_return(f);
#if USE_OV5640_AF
    if (i >= 4 && ov5640.getFWStatus() == FW_STATUS_S_FOCUSED) break;
#endif
    if (millis() - t0 > 2500) break;
  }
  camera_fb_t* fb = esp_camera_fb_get();
  String name;
  if (fb && fb->len > 1000) {
    // 이름 = 결과 번호 다음 값 + 가동 시간(겹치지 않게)
    name = "/q/" + String(rtcResultId + 1) + "_" + String(millis()) + ".jpg";
    File f = LittleFS.open(name, "w");
    if (f) { f.write(fb->buf, fb->len); f.close(); } else name = "";
  }
  if (fb) esp_camera_fb_return(fb);
  esp_camera_deinit();   // 카메라 전원·시계 끄기
  return name;
}

static void trimQueue() {   // 너무 많이 쌓이면 오래된 것부터 지움
  File d = LittleFS.open("/q");
  std::vector<String> names;
  for (File f = d.openNextFile(); f; f = d.openNextFile()) names.push_back(String("/q/") + f.name());
  std::sort(names.begin(), names.end());
  while ((int)names.size() > QUEUE_MAX) { LittleFS.remove(names.front()); names.erase(names.begin()); }
}

// ───────────────────────── 와이파이·중계기 ─────────────────────────
static bool wifiConnect() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(true);   // 기다리는 동안 절전
  // 1) 지난번 와이파이·채널로 빠른 재접속
  if (rtcWifiIdx >= 0 && rtcWifiIdx < WIFI_N && rtcChannel) {
    WiFi.begin(WIFI[rtcWifiIdx].ssid.c_str(), WIFI[rtcWifiIdx].pass.c_str(), rtcChannel, rtcBssid, true);
    uint32_t t0 = millis();
    while (millis() - t0 < 4000) { if (WiFi.isConnected()) return true; delay(50); }
    WiFi.disconnect();
  }
  // 2) 목록 순서대로(도시락 → 핫스팟)
  for (int i = 0; i < WIFI_N; i++) {
    WiFi.begin(WIFI[i].ssid.c_str(), WIFI[i].pass.c_str());
    uint32_t t0 = millis();
    while (millis() - t0 < WIFI_TRY_MS) {
      if (WiFi.isConnected()) {
        rtcWifiIdx = i;
        rtcChannel = WiFi.channel();
        memcpy(rtcBssid, WiFi.BSSID(), 6);
        return true;
      }
      delay(100);
    }
    WiFi.disconnect();
  }
  return false;
}

// 사진 한 장 보내고 결과 글 받기. http 코드(연결 실패는 -1)
static int postPhoto(const String& path, String& out) {
  File f = LittleFS.open(path, "r");
  if (!f) return -2;
  size_t n = f.size();
  uint8_t* buf = (uint8_t*)ps_malloc(n);
  if (!buf) { f.close(); return -3; }
  f.read(buf, n);
  f.close();
  WiFiClientSecure cli;
  cli.setInsecure();   // 중계기 주소는 고정(인증서 고정은 다음 판)
  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.setConnectTimeout(10000);
  int code = -1;
  if (http.begin(cli, RELAY_URL)) {
    http.addHeader("content-type", "image/jpeg");
    http.addHeader("x-device-token", DEVICE_TOKEN);
    http.addHeader("x-device-id", DEVICE_ID);
    code = http.POST(buf, n);
    if (code > 0) out = http.getString();
    http.end();
  }
  free(buf);
  return code;
}

// ───────────────────────── 와이파이 설정 모드(시험장에서 휴대폰으로) ─────────────────────────
// 촬영 단추를 8초 누르고 있으면 장치가 스스로 「채점장치-설정」 와이파이를 띄운다.
// 휴대폰으로 그 와이파이(비밀번호 12345678)에 붙어 주소창에 192.168.4.1 → 이름·비밀번호 입력 → 저장.
// 와이파이 도시락 이름이 바뀌어도, 새 핫스팟이어도 장치 프로그램을 다시 올릴 필요가 없다. 5분 지나면 저절로 끝.
static void setupMode() {
  WiFi.mode(WIFI_AP_STA);   // 설정 화면(공유기) + 화면 장치 무선 알림을 함께
  WiFi.softAP("채점장치-설정", "12345678", rtcChannel ? rtcChannel : 1);
  linkStart();
  sendStatus("설정 모드 · 휴대폰으로 「채점장치-설정」 접속 → 192.168.4.1");
  WebServer web(80);
  web.on("/", [&]() {
    Preferences p; p.begin("wifi", true);
    String rows;
    for (int i = 0; i < 5; i++) {
      String s = p.getString(("s" + String(i)).c_str(), "");
      rows += "<p>" + String(i + 1) + ". 이름 <input name=s" + String(i) + " value='" + s +
              "'> 비밀번호 <input name=p" + String(i) + " type=password placeholder='(그대로 두면 유지)'></p>";
    }
    p.end();
    web.send(200, "text/html; charset=utf-8",
             "<meta name=viewport content='width=device-width'><h3>채점 장치 와이파이</h3>"
             "<form method=post action=/save>" + rows + "<button>저장</button></form>"
             "<p>먼저 적은 순서대로 붙습니다. 비우면 그 칸은 지웁니다.</p>");
  });
  web.on("/save", HTTP_POST, [&]() {
    Preferences p; p.begin("wifi", false);
    for (int i = 0; i < 5; i++) {
      String s = web.arg("s" + String(i)), pw = web.arg("p" + String(i));
      s.trim();
      if (!s.length()) { p.remove(("s" + String(i)).c_str()); p.remove(("p" + String(i)).c_str()); continue; }
      p.putString(("s" + String(i)).c_str(), s);
      if (pw.length()) p.putString(("p" + String(i)).c_str(), pw);
    }
    p.end();
    rtcWifiIdx = -1;   // 다음엔 새 목록으로 찾음
    web.send(200, "text/html; charset=utf-8", "<h3>저장했습니다. 장치가 곧 잠듭니다.</h3>");
    delay(1500);
    goSleep(false);
  });
  web.begin();
  uint32_t t0 = millis();
  while (millis() - t0 < 300000) { web.handleClient(); esp_task_wdt_reset(); delay(5); }
  goSleep(false);
}

// ───────────────────────── 본 흐름 ─────────────────────────
void setup() {
  if (PIN_LED >= 0) pinMode(PIN_LED, OUTPUT);
  led(false);
  pinMode(PIN_SHUTTER, INPUT_PULLUP);
  // 감시 타이머: 200초 넘게 멈추면 자동 재시작(중계기 최대 대기 170초 + 여유)
  esp_task_wdt_config_t wdt = { .timeout_ms = 200000, .idle_core_mask = 0, .trigger_panic = true };
  esp_task_wdt_reconfigure(&wdt);
  esp_task_wdt_add(NULL);

  esp_reset_reason_t why = esp_reset_reason();
  if (why == ESP_RST_BROWNOUT || why == ESP_RST_PANIC || why == ESP_RST_TASK_WDT || why == ESP_RST_WDT) {
    if (++rtcBootFails >= 3) {   // 안전 모드: 연속 실패 3번이면 알리고 길게 쉼
      linkStart();
      sendStatus(why == ESP_RST_BROWNOUT ? GL_E_POWER : "E9 안전 모드 · 다시 켜 주세요");
      blink(10, 60);
      rtcBootFails = 0;
      goSleep(true);
    }
  }
  if (!LittleFS.begin(true)) blink(5, 50);
  loadWifiList();
  LittleFS.mkdir("/q");

  bool byButton = esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_EXT0 ||
                  esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_UNDEFINED;   // 처음 켤 때 포함
  if (esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_EXT0) {
    // 길게 누름 = 새 학생(여러 장 합치기 끊기)
    uint32_t t0 = millis();
    while (digitalRead(PIN_SHUTTER) == LOW && millis() - t0 < 9000) delay(10);
    if (millis() - t0 >= 8000) { blink(5, 60); setupMode(); }
    if (millis() - t0 >= LONG_PRESS_MS) {
      blink(2, 80);
      linkStart();
      for (int i = 0; i < 30; i++) { sendPacket(GL_NEWSTUDENT, 0, 0, 1, nullptr, 0); delay(30); }
      goSleep(false);
    }
  }

  if (byButton && esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_EXT0) {
    led(true);
    String name = captureToQueue();
    led(false);
    if (name == "") { linkStart(); sendStatus(GL_E_CAMERA); blink(3); goSleep(false); }
    trimQueue();
    blink(1, 60);   // 찍힘
  }

  // 보관된 사진이 없으면 그대로 잠
  File d = LittleFS.open("/q");
  std::vector<String> queue;
  for (File f = d.openNextFile(); f; f = d.openNextFile()) queue.push_back(String("/q/") + f.name());
  std::sort(queue.begin(), queue.end());
  if (queue.empty()) goSleep(false);

  if (!wifiConnect()) {
    linkStart();
    sendStatus(GL_E_WIFI);
    goSleep(true);   // 5분 뒤 다시
  }
  linkStart();
  sendStatus(GL_S_SENDING);

  bool left = false;
  for (auto& path : queue) {
    esp_task_wdt_reset();
    String text;
    int code = postPhoto(path, text);
    if (code == 200 && text.length() > 0) {
      LittleFS.remove(path);   // 결과를 받았으면 사진은 지움
      sendResult(text);        // 화면 장치가 자고 있어도 깨어 들을 때까지 반복
    } else {
      left = true;
      String msg = String(code < 0 ? GL_E_NET : GL_E_RELAY) + " (" + String(queue.size()) + "장)";
      if (code > 0 && text.length()) msg += " " + text.substring(0, 60);
      sendStatus(msg.c_str());
      break;   // 다음 사진도 같은 이유로 실패할 것이니 다음 기회에
    }
  }
  goSleep(left);
}

void loop() {}   // 깊은 잠에서 매번 setup() 부터 다시 시작
