// 채점 화면 장치 — GNPE ESP32-S3-0.96 MINI(C 플러그 동글, 0.96인치 160×80 ST7789)
//
// 대표 결정: 흰색·녹색만(녹색은 정답만) / 첫 화면부터 5×3 바둑판 / 계산 문항은 정답+풀이식 / 해설은 기본 꺼짐
// 2026-11-20 확정: 쪽 넘기기는 카메라 장치의 ◀▶ 단추로 원격(이 장치엔 단추를 달지 않음)
//
// 흐름(늘 켜 둠 — 보조배터리·휴대폰 C 단자에 꽂아 씀)
//   무선 채널 1번(GL_CHANNEL)을 계속 들음 → 결과 조각을 다 받으면 「받음」 답장 → 바둑판
//   → 카메라 ◀▶ 신호로 쪽 넘김 → 1분 동안 아무 신호 없으면 화면 불만 끔(신호 오면 다시 켬)
//   깊은 잠을 쓰지 않는 이유: 잠들면 원격 넘기기가 늦고, 전류가 너무 적으면 보조배터리가 저절로 꺼짐.
//
// 보드 설정(아두이노): 「ESP32S3 Dev Module」, USB CDC On Boot: Enabled(C 플러그로 바로 올림),
//   Flash Size: 보드 표기대로(보통 16MB 또는 4MB), PSRAM: Disabled, 파티션: SPIFFS 포함 아무거나
// 필요한 꾸러미: Adafruit GFX, Adafruit ST7735 and ST7789, U8g2_for_Adafruit_GFX
#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
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
// 0.96인치 ST7789 는 화면 위치(오프셋)를 직접 맞춰야 해서 조금 고친 판을 씀
class St7789Mini : public Adafruit_ST7789 {
 public:
  using Adafruit_ST7789::Adafruit_ST7789;
  void offsets(int8_t c, int8_t r) { _colstart = _colstart2 = c; _rowstart = _rowstart2 = r; }
};
St7789Mini tft(PIN_TFT_CS, PIN_TFT_DC, PIN_TFT_RST);
#endif
U8G2_FOR_ADAFRUIT_GFX u8;
static const int W = 160, H = 80;

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
static bool lightOn = false;
static void screenInit() {
  SPI.begin(PIN_TFT_SCLK, -1, PIN_TFT_MOSI, PIN_TFT_CS);
#if TFT_DRIVER_ST7735
  tft.initR(INITR_MINI160x80_PLUGIN);
#else
  tft.init(80, 160);
  tft.offsets(TFT_COL_OFS, TFT_ROW_OFS);
  tft.invertDisplay(TFT_INVERT);
#endif
  tft.setRotation(TFT_ROTATION);
  u8.begin(tft);
  u8.setFontMode(1);
  pinMode(PIN_TFT_BL, OUTPUT);
}

static void light(bool on) {
  if (on == lightOn) return;
  if (on) tft.enableSleep(false);
  digitalWrite(PIN_TFT_BL, on ? TFT_BL_ON : !TFT_BL_ON);
  if (!on) tft.enableSleep(true);   // 화면 칩 절전
  lightOn = on;
}

// ───────────────────────── 무선 받기 ─────────────────────────
// 받는 쪽(무선 처리 흐름)에서는 표시만 해 두고, 그리기는 loop() 에서
static volatile uint16_t rxId = 0;
static volatile uint8_t rxTotal = 0;
static char rxBuf[GL_PAYLOAD * 40 + 1];
static volatile uint64_t rxMask = 0;
static volatile bool newStudentFlag = false;
static char statusBuf[GL_PAYLOAD + 1];
static volatile bool statusFlag = false;
static volatile char pageCmd = 0;
static volatile uint16_t pageId = 0, lastPageId = 0;
static volatile int powerFlag = -1;     // 1 켬, 0 끔
static volatile uint16_t lastId = 0xFFFF;   // 마지막으로 받은 결과 번호
static volatile bool reAck = false;

static void onRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  if (len < (int)offsetof(GlPacket, payload)) return;
  const GlPacket* p = (const GlPacket*)data;
  if (p->magic != GL_MAGIC || p->group != GROUP_CODE) return;
  switch (p->type) {
    case GL_READY:
    case GL_CHUNK:
      if (p->id == lastId) { reAck = true; break; }   // 이미 받은 결과 → 답장만 다시(loop 에서)
      if (p->id != rxId) { rxId = p->id; rxMask = 0; memset(rxBuf, 0, sizeof(rxBuf)); }
      rxTotal = p->total;
      if (p->type == GL_CHUNK && p->part < 40) {
        memcpy(rxBuf + p->part * GL_PAYLOAD, p->payload, p->len);
        rxMask |= (1ULL << p->part);
      }
      break;
    case GL_STATUS: {
      int n = min((int)p->len, GL_PAYLOAD);
      memcpy(statusBuf, p->payload, n); statusBuf[n] = 0;
      statusFlag = true;
      break;
    }
    case GL_NEWSTUDENT: newStudentFlag = true; break;
    case GL_PAGE:
      if (p->len >= 1) { pageId = p->id; pageCmd = p->payload[0]; }
      break;
    case GL_POWER:
      if (p->len >= 1) powerFlag = p->payload[0] == '1' ? 1 : 0;
      break;
  }
}

static bool rxComplete() { return rxTotal && rxMask == ((rxTotal >= 64) ? ~0ULL : ((1ULL << rxTotal) - 1)); }

static void radioStart() {
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_channel(GL_CHANNEL, WIFI_SECOND_CHAN_NONE);
  esp_wifi_set_promiscuous(false);
  esp_wifi_set_ps(WIFI_PS_NONE);   // 늘 들음(놓치지 않게)
  esp_now_init();
  esp_now_register_recv_cb(onRecv);
  esp_now_peer_info_t peer = {};
  memset(peer.peer_addr, 0xFF, 6);
  peer.channel = 0;
  esp_now_add_peer(&peer);
}

static void sendAck(uint16_t id, int times = 5) {
  GlPacket p = {};
  p.magic = GL_MAGIC; p.group = GROUP_CODE; p.type = GL_ACK; p.id = id; p.total = 1;
  static const uint8_t bc[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
  for (int i = 0; i < times; i++) { esp_now_send(bc, (const uint8_t*)&p, offsetof(GlPacket, payload)); delay(5); }
}

// ───────────────────────── 저장(꺼졌다 켜져도 마지막 학생 결과 유지) ─────────────────────────
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

static bool newStudent = true;
static uint32_t lastResultAt = 0;

static void acceptResult(const String& text) {
  // 새 학생 표시가 있었거나 10분 넘게 지났으면 새 묶음, 아니면 이어 붙임(여러 장 합치기)
  bool fresh = newStudent || millis() - lastResultAt > MERGE_MS;
  String all = fresh ? String() : loadText("/batch.txt");
  if (all.length()) all += "\n\x1e\n";
  all += text;
  saveText("/batch.txt", all);
  newStudent = false;
  lastResultAt = millis();
  statusMsg = "";
  loadAll();
  cur = 0;
  buildPages();
}

// ───────────────────────── 쪽 넘기기 ─────────────────────────
static uint32_t lastActive = 0;

static void wake() { light(true); lastActive = millis(); }

static void doCmd(char cmd) {
  if (nPages == 0) buildPages();
  switch (cmd) {
    case GL_CMD_PREV:  cur = (cur - 1 + nPages) % nPages; break;
    case GL_CMD_NEXT:  cur = (cur + 1) % nPages; break;
    case GL_CMD_FIRST: cur = 0; break;
    case GL_CMD_NOTES: notes = !notes; buildPages(); break;
  }
  // 화면 불이 꺼져 있었으면 첫 누름은 「켜기」만(어디까지 봤는지 보이게)
  bool wasOff = !lightOn;
  wake();
  if (wasOff && (cmd == GL_CMD_PREV || cmd == GL_CMD_NEXT)) cur = (cmd == GL_CMD_NEXT) ? (cur - 1 + nPages) % nPages : (cur + 1) % nPages;
  render();
}

static void localButton() {
  if (PIN_BTN_LOCAL < 0 || digitalRead(PIN_BTN_LOCAL) != LOW) return;
  uint32_t t0 = millis();
  while (digitalRead(PIN_BTN_LOCAL) == LOW && millis() - t0 < 3000) delay(10);
  doCmd(millis() - t0 >= LONG_MS ? GL_CMD_FIRST : GL_CMD_NEXT);
}

// ───────────────────────── 본 흐름 ─────────────────────────
void setup() {
  if (PIN_BTN_LOCAL >= 0) pinMode(PIN_BTN_LOCAL, INPUT_PULLUP);
  LittleFS.begin(true);
  screenInit();
  radioStart();
  loadAll();
  if (nItems == 0) statusMsg = "준비됨 · 촬영 단추를 누르세요";
  buildPages();
  wake();
  render();
}

void loop() {
  // 새 결과
  if (rxComplete() && rxId != lastId) {
    uint16_t id = rxId;
    String text = String(rxBuf).substring(0, min((int)strlen(rxBuf), rxTotal * GL_PAYLOAD));
    lastId = id;
    rxTotal = 0; rxMask = 0;
    sendAck(id);
    acceptResult(text);
    wake(); render();
  }
  // 카메라가 「받음」을 못 듣고 같은 결과를 다시 보내면 답장만 다시(0.2초에 한 번까지)
  static uint32_t lastReAck = 0;
  if (reAck && millis() - lastReAck > 200) { reAck = false; lastReAck = millis(); sendAck(lastId, 2); }

  // 쪽 넘기기(같은 번호 반복은 한 번만 처리, 답장은 매번)
  if (pageCmd) {
    char cmd = pageCmd; uint16_t id = pageId; pageCmd = 0;
    sendAck(id, 2);
    if (id != lastPageId) { lastPageId = id; doCmd(cmd); }
  }
  // 상태 글(채점 중·오류 등)
  if (statusFlag) {
    statusFlag = false;
    statusMsg = String(statusBuf);
    // 상태 글을 화면 가득 보여 줌(채점 중·오류·켜짐 등). ◀▶ 를 누르면 지난 결과로 돌아감
    if (nItems == 0) buildPages();
    tft.fillScreen(C_BG);
    drawMsg();
    wake();
  }
  if (newStudentFlag) { newStudentFlag = false; newStudent = true; }
  if (powerFlag >= 0) {
    int on = powerFlag; powerFlag = -1;
    if (on) { wake(); render(); } else { light(false); }
  }
  localButton();
  if (lightOn && millis() - lastActive > DIM_MS) light(false);
  delay(5);
}
