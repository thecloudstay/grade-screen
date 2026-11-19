// 채점 화면 모듈 (ESP32-S3 + 0.96인치 160x80)
//
// 화면 글자는 모듈이 그리지 않는다. 컴퓨터 시뮬레이터가 그린 160x80 그림을
// USB 로 받아 그대로 띄운다. → 한글 글꼴이 필요 없고, 시뮬레이터와 화면이 100% 같다.
//
// 택트 스위치 2개 (한쪽 다리 = 아래 핀, 다른 다리 = GND)
//   ◀ 짧게 = 이전 / 길게(0.8초) = 첫 쪽(점수)
//   ▶ 짧게 = 다음 / 길게(0.8초) = 해설 켜기·끄기
//
// 아두이노 설정: 보드 ESP32S3 Dev Module, USB CDC On Boot = Enabled
// 라이브러리: 라이브러리 관리자에서 "GFX Library for Arduino" 설치
//
// ※ 핀 번호·화면 칩은 판매처 자료 기준 추정값. 실물 도착 후 확정한다.

#include <Arduino_GFX_Library.h>

// ---------------- 보드에 맞게 바꿀 부분 ----------------
#define USE_ST7789   1      // 판매 글 = ST7789. 화면이 안 나오면 0 (ST7735)
#define PIN_SCK      5
#define PIN_MOSI     3
#define PIN_CS       4
#define PIN_DC       2
#define PIN_RST      1
#define PIN_BL       38     // 화면 밝기
#define BL_ON        LOW    // 화면이 꺼져 있으면 HIGH 로
#define COL_OFS      26     // 화면이 옆으로 밀리면 조정
#define ROW_OFS      1
#define ROTATION     1      // 거꾸로 보이면 3

#define PIN_PREV     43     // ◀ 택트 스위치
#define PIN_NEXT     44     // ▶ 택트 스위치
#define PIN_BOOT     0      // 기판 BOOT 버튼(예비: 다음)
#define LONG_MS      800
// --------------------------------------------------------

Arduino_DataBus *bus = new Arduino_ESP32SPI(PIN_DC, PIN_CS, PIN_SCK, PIN_MOSI, GFX_NOT_DEFINED);
#if USE_ST7789
Arduino_GFX *gfx = new Arduino_ST7789(bus, PIN_RST, ROTATION, true, 80, 160,
                                      COL_OFS, ROW_OFS, COL_OFS, ROW_OFS);
#else
Arduino_GFX *gfx = new Arduino_ST7735(bus, PIN_RST, ROTATION, true, 80, 160,
                                      COL_OFS, ROW_OFS, COL_OFS, ROW_OFS);
#endif

static const int W = 160, H = 80;
static uint16_t frame[W * H];
static uint32_t lastFrameMs = 0;
static bool gotFrame = false;

// ---------------- 스위치 ----------------
struct Key {
  uint8_t pin;
  char shortCmd, longCmd;
  bool down = false, longSent = false;
  uint32_t t0 = 0, lastChange = 0;
};
Key keys[] = {
  {PIN_PREV, 'P', 'F'},
  {PIN_NEXT, 'N', 'T'},
  {PIN_BOOT, 'N', 'T'},
};

void pollKeys() {
  uint32_t now = millis();
  for (auto &k : keys) {
    bool pressed = digitalRead(k.pin) == LOW;
    if (pressed != k.down && now - k.lastChange > 25) {       // 떨림 방지
      k.lastChange = now;
      k.down = pressed;
      if (pressed) {
        k.t0 = now;
        k.longSent = false;
      } else if (!k.longSent) {
        Serial.write(k.shortCmd);
      }
    }
    if (k.down && !k.longSent && now - k.t0 >= LONG_MS) {   // 누르고 있는 중에 바로 반응
      Serial.write(k.longCmd);
      k.longSent = true;
    }
  }
}

// ---------------- 대기 화면(글자 없이 점 3개) ----------------
void drawWaiting() {
  static uint8_t step = 0;
  static uint32_t t = 0;
  if (millis() - t < 400) return;
  t = millis();
  gfx->fillScreen(BLACK);
  for (int i = 0; i < 3; i++) {
    uint16_t c = (i <= step % 3) ? gfx->color565(70, 200, 100) : gfx->color565(40, 40, 40);
    gfx->fillCircle(W / 2 - 16 + i * 16, H / 2, 4, c);
  }
  step++;
}

// ---------------- 그림 받기: A5 5A + 25600바이트 ----------------
void readFrame() {
  static uint8_t state = 0;
  while (Serial.available()) {
    int b = Serial.peek();
    if (state == 0) { Serial.read(); state = (b == 0xA5) ? 1 : 0; continue; }
    if (state == 1) { Serial.read(); state = (b == 0x5A) ? 2 : (b == 0xA5 ? 1 : 0); continue; }
    size_t got = Serial.readBytes((uint8_t *)frame, sizeof(frame));
    state = 0;
    if (got == sizeof(frame)) {
      gfx->draw16bitRGBBitmap(0, 0, frame, W, H);
      gotFrame = true;
      lastFrameMs = millis();
    }
    return;
  }
}

void setup() {
  Serial.setRxBufferSize(32768);
  Serial.begin(921600);
  Serial.setTimeout(500);
  for (auto &k : keys) pinMode(k.pin, INPUT_PULLUP);
  pinMode(PIN_BL, OUTPUT);
  digitalWrite(PIN_BL, BL_ON);
  gfx->begin();
  gfx->fillScreen(BLACK);
}

void loop() {
  pollKeys();
  readFrame();
  if (!gotFrame) {
    drawWaiting();
    static uint32_t hello = 0;
    if (millis() - hello > 1000) {        // 컴퓨터에 "현재 화면 보내 줘"
      hello = millis();
      Serial.write('H');
    }
  }
}
