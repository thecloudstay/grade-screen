// 채점 화면 장치 — ESP32-S3 + 0.96인치 160×80 화면 + 단추 2개(◀ ▶)
//
// 대표 결정(2026-11-19): 전지 직결 + 깊은 잠 / 흰색·녹색만(녹색은 정답만) / 첫 화면부터 5×3 바둑판
//   / 계산 문항은 정답+풀이식 / 해설은 기본 꺼짐(▶ 1초로 켜고 끔)
//
// 흐름
//   깊은 잠 → 3초마다 잠깐(0.06초) 깨어 카메라 장치의 「새 결과」 신호를 들음 → 없으면 다시 잠
//   → 있으면 조각을 다 받고 「받음」 답장 → 화면 켜고 바둑판 → 단추로 넘기기 → 30초 손 안 대면 잠
//   단추로 깨우면 마지막 결과를 다시 보여 줌. 카메라 채널이 바뀌면 1~13 채널을 훑어 다시 찾음.
//
// 보드 설정(아두이노): 「ESP32S3 Dev Module」, PSRAM 은 보드에 맞게
// 필요한 꾸러미: Adafruit GFX, Adafruit ST7735 and ST7789, U8g2_for_Adafruit_GFX
#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <esp_sleep.h>
#include <LittleFS.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>
#include <Adafruit_ST7789.h>
#include <U8g2_for_Adafruit_GFX.h>
#include "config.h"
#include "grade_link.h"

// ── 색: 흰색과 녹색만 ──
#define C_BG 0x0000
#define C_FG 0xFFFF
#define C_OK 0x4E4C   // 녹색(70,200,100 근사)

#if TFT_DRIVER_ST7735
Adafruit_ST7735 tft(PIN_TFT_CS, PIN_TFT_DC, PIN_TFT_RST);
#else
Adafruit_ST7789 tft(PIN_TFT_CS, PIN_TFT_DC, PIN_TFT_RST);
#endif
U8G2_FOR_ADAFRUIT_GFX u8;
static const int W = 160, H = 80;

// ── 깊은 잠을 건너 기억 ──
RTC_DATA_ATTR uint8_t rtcChannel = 1;
RTC_DATA_ATTR uint16_t rtcLastId = 0;
RTC_DATA_ATTR uint32_t rtcWakes = 0;
RTC_DATA_ATTR bool rtcNewStudent = true;
RTC_DATA_ATTR uint32_t rtcLastResultAt = 0;   // 깨어난 횟수 기준(약 3초 단위)

// ───────────────────────── 결과 해석 ─────────────────────────
struct Item {
  String no, label, mine, answer, calc, qkey, note;
  bool ok = false, blank = false;
};
static const int MAXI = 160;
static Item items[MAXI];
static int nItems = 0;
static String statusMsg;
static bool notes = false;

static String field(const String& line, const char* key) {   // 「키: 값」 꺼내기
  int k = line.indexOf(key);
  if (k < 0) return "";
  int c = line.indexOf(':', k);
  int c2 = line.indexOf("：", k);
  if (c < 0 || (c2 >= 0 && c2 < c)) c = c2 >= 0 ? c2 + 2 : c;   // 전각 쌍점(3바이트)
  int e = line.indexOf('|', c + 1);
  String v = line.substring(c + 1, e < 0 ? line.length() : e);
  v.trim();
  return v;
}

// 결과 글 한 장을 문항 목록에 더한다(여러 장 합치기: 같은 번호·같은 문항이면 바꾸고, 다른 문항이면 묶음 번호)
static void parseInto(const String& text, bool merge) {
  if (!merge) nItems = 0;
  static int section = 1;
  if (!merge) section = 1;
  int pos = 0;
  while (pos < (int)text.length()) {
    int e = text.indexOf('\n', pos);
    if (e < 0) e = text.length();
    String ln = text.substring(pos, e);
    pos = e + 1;
    ln.trim();
    int b = ln.indexOf("번");
    if (b <= 0 || b > 4) {   // 「해설 N번: …」
      if (ln.startsWith("해설")) {
        int n0 = 6, nb = ln.indexOf("번");   // 「해설 」 = 7바이트
        String no = ln.substring(n0, nb); no.trim();
        int c = ln.indexOf(':', nb);
        for (int i = nItems - 1; i >= 0; i--) if (items[i].no == no) { items[i].note = ln.substring(c + 1); items[i].note.trim(); break; }
      }
      continue;
    }
    String no = ln.substring(0, b); no.trim();
    if (no.toInt() <= 0) continue;
    Item it;
    it.no = no;
    it.blank = ln.indexOf("미표기") > 0;
    if (!it.blank) {
      it.mine = field(ln, "내 답");
      if (it.mine == "" || it.mine == "없음" || it.mine == "-") it.blank = true;
    }
    it.answer = field(ln, "정답");
    it.calc = field(ln, "식");
    it.qkey = field(ln, "문항");
    // O/X: 「| O」 또는 「| X」 칸
    it.ok = !it.blank && (ln.indexOf("| O") > 0 || ln.indexOf("| ○") > 0);
    if (it.answer == "") continue;
    // 같은 번호가 이미 있으면
    int same = -1;
    for (int i = 0; i < nItems; i++) if (items[i].no == it.no && items[i].label.startsWith(String(section) + "-") == (section > 1)) same = i;
    if (same >= 0) {
      bool sameQ = it.qkey == "" || items[same].qkey == "" || it.qkey == items[same].qkey;
      if (sameQ) {   // 겹쳐 찍힘: 답이 읽힌 쪽 또는 나중 사진
        if (!(it.blank && !items[same].blank)) { it.label = items[same].label; items[same] = it; }
        continue;
      }
      section++;     // 번호가 다시 시작됨
    }
    it.label = section > 1 ? String(section) + "-" + it.no : it.no;
    if (nItems < MAXI) items[nItems++] = it;
  }
  if (section > 1) for (int i = 0; i < nItems; i++) if (items[i].label.indexOf('-') < 0) items[i].label = "1-" + items[i].no;
}

// 칸에 넣을 정답: 보기 번호(①~⑳)는 굵은 숫자로
static String gridText(const String& a) {
  // 「①」 = E2 91 A0 … 「⑳」 = E2 91 B3
  if (a.length() >= 3 && (uint8_t)a[0] == 0xE2 && (uint8_t)a[1] == 0x91 &&
      (uint8_t)a[2] >= 0xA0 && (uint8_t)a[2] <= 0xB3) {
    return String((uint8_t)a[2] - 0xA0 + 1);
  }
  return a;
}

// ───────────────────────── 쪽 만들기 ─────────────────────────
enum PageKind : uint8_t { P_GRID, P_DETAIL, P_MSG };
struct Page { PageKind kind; int16_t a; };
static Page pages[80];
static int nPages = 0, cur = 0;

static bool fitsGrid(const String& s, const uint8_t*& font) {
  static const uint8_t* fonts[] = { u8g2_font_helvB14_tr, u8g2_font_helvB10_tr, u8g2_font_6x10_tr };
  bool ascii = true;
  for (char c : s) if ((uint8_t)c >= 0x80) ascii = false;
  if (!ascii) {
    u8.setFont(u8g2_font_unifont_t_korean2);
    if (u8.getUTF8Width(s.c_str()) <= 30) { font = u8g2_font_unifont_t_korean2; return true; }
    return false;
  }
  for (auto f : fonts) { u8.setFont(f); if (u8.getUTF8Width(s.c_str()) <= 30) { font = f; return true; } }
  return false;
}

static void buildPages() {
  nPages = 0;
  if (statusMsg.length() && nItems == 0) { pages[nPages++] = { P_MSG, 0 }; }
  for (int i = 0; i < nItems; i += 15) pages[nPages++] = { P_GRID, (int16_t)i };
  for (int i = 0; i < nItems && nPages < 80; i++) {
    const uint8_t* f;
    bool longAns = !fitsGrid(gridText(items[i].answer), f);
    if ((!items[i].ok && (items[i].calc.length() || (notes && items[i].note.length()))) || longAns)
      pages[nPages++] = { P_DETAIL, (int16_t)i };
  }
  if (nPages == 0) pages[nPages++] = { P_MSG, 0 };
  if (cur >= nPages) cur = 0;
}

// ───────────────────────── 그리기 ─────────────────────────
static void drawTri(int x, int y) { tft.fillTriangle(x - 4, y - 6, x - 4, y + 6, x + 5, y, C_OK); }

static void drawGrid(int start) {
  for (int k = 0; k < 15 && start + k < nItems; k++) {
    const Item& it = items[start + k];
    int cx = (k % 5) * 32, cy = (k / 5) * 26;
    if (!it.ok) tft.drawRect(cx, cy, 32, 26, C_FG);     // 틀림·미표기 = 흰 테두리
    u8.setFont(u8g2_font_5x8_tr);
    u8.setForegroundColor(C_FG);
    String no = it.label + (it.blank ? "-" : "");
    u8.drawUTF8(cx + 2, cy + 8, no.c_str());
    String t = gridText(it.answer);
    const uint8_t* f;
    if (fitsGrid(t, f)) {
      u8.setFont(f);
      u8.setForegroundColor(C_OK);
      int w = u8.getUTF8Width(t.c_str());
      u8.drawUTF8(cx + (32 - w) / 2, cy + 23, t.c_str());
    } else {
      drawTri(cx + 16, cy + 16);   // 길어서 뒤쪽에 크게
    }
  }
}

static int wrapDraw(const String& s, int x, int y, int maxW, int lineH, uint16_t col, int maxLines) {
  u8.setFont(u8g2_font_unifont_t_korean2);
  u8.setForegroundColor(col);
  String line;
  int lines = 0, i = 0;
  while (i < (int)s.length() && lines < maxLines) {
    int n = 1;
    uint8_t c = s[i];
    if (c >= 0xF0) n = 4; else if (c >= 0xE0) n = 3; else if (c >= 0xC0) n = 2;
    String ch = s.substring(i, i + n);
    if (u8.getUTF8Width((line + ch).c_str()) > maxW) {
      u8.drawUTF8(x, y + lines * lineH, line.c_str());
      lines++; line = "";
    }
    line += ch; i += n;
  }
  if (line.length() && lines < maxLines) { u8.drawUTF8(x, y + lines * lineH, line.c_str()); lines++; }
  return lines;
}

static void drawDetail(int idx) {
  const Item& it = items[idx];
  String head = it.label + "번 " + (it.blank ? "미표기" : it.ok ? "정답" : "오답");
  if (!it.blank && !it.ok) head += " · 내 답 " + it.mine;
  wrapDraw(head, 2, 14, W - 4, 16, C_FG, 1);
  tft.drawFastHLine(0, 18, W, C_FG);
  int y = 34;
  y += 16 * wrapDraw(it.answer, 2, y, W - 4, 16, C_OK, it.calc.length() ? 2 : 3);
  if (it.calc.length() && !it.ok) wrapDraw("식 " + it.calc, 2, y, W - 4, 16, C_FG, (H - y + 12) / 16);
  else if (notes && it.note.length()) wrapDraw(it.note, 2, y, W - 4, 16, C_FG, (H - y + 12) / 16);
}

static void drawMsg() {
  String s = statusMsg.length() ? statusMsg : String("결과 없음");
  wrapDraw(s, 2, 16, W - 4, 18, C_FG, 4);
}

static void render() {
  tft.fillScreen(C_BG);
  if (nPages == 0) buildPages();
  const Page& p = pages[cur];
  if (p.kind == P_GRID) drawGrid(p.a);
  else if (p.kind == P_DETAIL) drawDetail(p.a);
  else drawMsg();
}

// ───────────────────────── 화면 켜고 끄기 ─────────────────────────
static bool screenOn = false;
static void screenStart() {
  if (screenOn) return;
  SPI.begin(PIN_TFT_SCLK, -1, PIN_TFT_MOSI, PIN_TFT_CS);
#if TFT_DRIVER_ST7735
  tft.initR(INITR_MINI160x80_PLUGIN);
#else
  tft.init(80, 160);
#endif
  tft.setRotation(TFT_ROTATION);
  u8.begin(tft);
  u8.setFontMode(1);
  pinMode(PIN_TFT_BL, OUTPUT);
  digitalWrite(PIN_TFT_BL, HIGH);
  screenOn = true;
}

static void screenStop() {
  if (!screenOn) return;
  digitalWrite(PIN_TFT_BL, LOW);
  tft.enableSleep(true);   // 화면 칩 절전
  screenOn = false;
}

// ───────────────────────── 무선 받기 ─────────────────────────
static volatile bool heard = false;
static volatile uint16_t rxId = 0;
static volatile uint8_t rxTotal = 0;
static char rxBuf[GL_PAYLOAD * 40];
static volatile uint64_t rxMask = 0;
static volatile bool newStudentFlag = false;
static String pendingStatus;
static volatile bool statusFlag = false;

static void onRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  if (len < (int)offsetof(GlPacket, payload)) return;
  const GlPacket* p = (const GlPacket*)data;
  if (p->magic != GL_MAGIC || p->group != GROUP_CODE) return;
  heard = true;
  switch (p->type) {
    case GL_READY:
    case GL_CHUNK:
      if (p->id == rtcLastId) break;               // 이미 받은 결과
      if (p->id != rxId) { rxId = p->id; rxMask = 0; memset(rxBuf, 0, sizeof(rxBuf)); }
      rxTotal = p->total;
      if (p->type == GL_CHUNK && p->part < 40) {
        memcpy(rxBuf + p->part * GL_PAYLOAD, p->payload, p->len);
        rxMask |= (1ULL << p->part);
      }
      break;
    case GL_STATUS:
      pendingStatus = String(p->payload).substring(0, p->len);
      statusFlag = true;
      break;
    case GL_NEWSTUDENT:
      newStudentFlag = true;
      break;
  }
}

static bool rxComplete() { return rxTotal && rxMask == ((rxTotal >= 64) ? ~0ULL : ((1ULL << rxTotal) - 1)); }

static void radioStart(uint8_t ch) {
  WiFi.mode(WIFI_STA);
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_channel(ch, WIFI_SECOND_CHAN_NONE);
  esp_wifi_set_promiscuous(false);
  esp_now_init();
  esp_now_register_recv_cb(onRecv);
  esp_now_peer_info_t peer = {};
  memset(peer.peer_addr, 0xFF, 6);
  peer.channel = 0;
  esp_now_add_peer(&peer);
}

static void setChannel(uint8_t ch) {
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_channel(ch, WIFI_SECOND_CHAN_NONE);
  esp_wifi_set_promiscuous(false);
}

static void sendAck(uint16_t id) {
  GlPacket p = {};
  p.magic = GL_MAGIC; p.group = GROUP_CODE; p.type = GL_ACK; p.id = id; p.total = 1;
  static const uint8_t bc[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
  for (int i = 0; i < 5; i++) { esp_now_send(bc, (const uint8_t*)&p, offsetof(GlPacket, payload)); delay(10); }
}

// ───────────────────────── 저장 ─────────────────────────
static void saveText(const char* path, const String& s) { File f = LittleFS.open(path, "w"); if (f) { f.print(s); f.close(); } }
static String loadText(const char* path) { File f = LittleFS.open(path, "r"); String s; if (f) { s = f.readString(); f.close(); } return s; }

static void loadAll() {   // 지금 학생의 결과 묶음(여러 장)을 다시 해석
  nItems = 0;
  String all = loadText("/batch.txt");
  int pos = 0; bool first = true;
  while (pos < (int)all.length()) {
    int e = all.indexOf("\n\x1e\n", pos);   // 장 구분 표시
    if (e < 0) e = all.length();
    parseInto(all.substring(pos, e), !first);
    first = false;
    pos = e + 3;
  }
}

static void acceptResult(const String& text) {
  // 새 학생 표시가 있었거나 10분 넘게 지났으면 새 묶음, 아니면 이어 붙임(여러 장 합치기)
  bool fresh = rtcNewStudent || (rtcWakes - rtcLastResultAt) * LISTEN_EVERY_S > 600;
  String all = fresh ? String() : loadText("/batch.txt");
  if (all.length()) all += "\n\x1e\n";
  all += text;
  saveText("/batch.txt", all);
  rtcNewStudent = false;
  rtcLastResultAt = rtcWakes;
  statusMsg = "";
  loadAll();
  cur = 0;
  buildPages();
}

// ───────────────────────── 잠들기 ─────────────────────────
static void goSleep() {
  screenStop();
  esp_now_deinit();
  WiFi.mode(WIFI_OFF);
  uint64_t mask = (1ULL << PIN_BTN_PREV) | (1ULL << PIN_BTN_NEXT);
  esp_sleep_enable_ext1_wakeup(mask, ESP_EXT1_WAKEUP_ANY_LOW);
  esp_sleep_enable_timer_wakeup((uint64_t)LISTEN_EVERY_S * 1000000ULL);
  esp_deep_sleep_start();
}

// ───────────────────────── 들어 보기(짧게) ─────────────────────────
// 새 결과 신호가 들리면 끝까지 받고 true
static bool listenOnce() {
  rtcWakes++;
  bool scan = (rtcWakes % SCAN_EVERY) == 0;
  radioStart(rtcChannel);
  uint32_t t0 = millis();
  while (millis() - t0 < LISTEN_MS && !heard) delay(2);
  if (!heard && scan) {   // 카메라 채널이 바뀌었을 수 있음 → 1~13 훑기
    for (uint8_t ch = 1; ch <= 13 && !heard; ch++) {
      setChannel(ch);
      uint32_t t1 = millis();
      while (millis() - t1 < 35 && !heard) delay(2);
      if (heard) rtcChannel = ch;
    }
    if (!heard) setChannel(rtcChannel);
  }
  if (!heard) return false;
  // 들렸으면 결과 조각을 최대 8초 기다림
  uint32_t t2 = millis();
  while (millis() - t2 < 8000) {
    if (rxComplete()) {
      String text = String(rxBuf).substring(0, min((int)strlen(rxBuf), rxTotal * GL_PAYLOAD));
      rtcLastId = rxId;
      sendAck(rxId);
      acceptResult(text);
      return true;
    }
    if (statusFlag && !rxTotal) break;
    delay(5);
  }
  return false;
}

// ───────────────────────── 단추 ─────────────────────────
static uint32_t lastTouch = 0;

static int pressLen(int pin) {   // 누른 시간(ms). 5초 넘으면 바로 반환
  uint32_t t0 = millis();
  while (digitalRead(pin) == LOW && millis() - t0 < OFF_MS) delay(10);
  return millis() - t0;
}

static void handleButtons() {
  if (digitalRead(PIN_BTN_PREV) == LOW) {
    int ms = pressLen(PIN_BTN_PREV);
    if (ms >= OFF_MS) { tft.fillScreen(C_BG); wrapDraw("끄는 중", 40, 46, 120, 16, C_FG, 1); delay(600); goSleep(); }
    if (ms >= LONG_MS) cur = 0; else cur = (cur - 1 + nPages) % nPages;
    render(); lastTouch = millis();
  }
  if (digitalRead(PIN_BTN_NEXT) == LOW) {
    int ms = pressLen(PIN_BTN_NEXT);
    if (ms >= LONG_MS) { notes = !notes; buildPages(); } else cur = (cur + 1) % nPages;
    render(); lastTouch = millis();
  }
}

// ───────────────────────── 본 흐름 ─────────────────────────
void setup() {
  pinMode(PIN_BTN_PREV, INPUT_PULLUP);
  pinMode(PIN_BTN_NEXT, INPUT_PULLUP);
  LittleFS.begin(true);
  esp_sleep_wakeup_cause_t why = esp_sleep_get_wakeup_cause();

  if (why == ESP_SLEEP_WAKEUP_TIMER) {
    if (!listenOnce()) {
      if (statusFlag) { statusMsg = pendingStatus; nItems = 0; screenStart(); buildPages(); render(); lastTouch = millis(); return; }
      if (newStudentFlag) rtcNewStudent = true;
      goSleep();
    }
    screenStart(); render(); lastTouch = millis();
    return;
  }
  // 단추로 깨움 또는 처음 켬: 마지막 결과 다시 보기
  radioStart(rtcChannel);
  loadAll();
  if (nItems == 0) statusMsg = why == ESP_SLEEP_WAKEUP_UNDEFINED ? "준비됨 · 촬영 단추를 누르세요" : "결과 없음";
  buildPages();
  screenStart();
  render();
  lastTouch = millis();
}

void loop() {
  handleButtons();
  // 켜져 있는 동안 새 결과·상태도 바로 받음
  if (rxComplete() && rxId != rtcLastId) {
    String text = String(rxBuf).substring(0, min((int)strlen(rxBuf), rxTotal * GL_PAYLOAD));
    rtcLastId = rxId; sendAck(rxId); acceptResult(text); render(); lastTouch = millis();
  }
  if (statusFlag) { statusFlag = false; statusMsg = pendingStatus; if (nItems == 0) { buildPages(); render(); } }
  if (newStudentFlag) { newStudentFlag = false; rtcNewStudent = true; }
  if (millis() - lastTouch > IDLE_SLEEP_MS) goSleep();
  delay(10);
}
