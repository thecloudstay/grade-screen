// 화면 장치 설정. 단자 번호는 GNPE 보드 실물 사진을 보고 확정한다(아래는 흔한 0.96인치 보드 값).
#pragma once
#if __has_include("config_local.h")
#include "config_local.h"
#else
#define GROUP_CODE 0x20261119UL   // 카메라 장치와 같은 값
#endif

// ── 화면(0.96인치 160×80, 보통 ST7735S) ──
#define TFT_DRIVER_ST7735 1      // ST7789 보드면 0
#define PIN_TFT_SCLK 3
#define PIN_TFT_MOSI 2
#define PIN_TFT_CS   5
#define PIN_TFT_DC   4
#define PIN_TFT_RST  1
#define PIN_TFT_BL   38          // 화면 밝기(백라이트), 높으면 켜짐
#define TFT_ROTATION 3           // 가로로 눕히기(화면이 뒤집혀 보이면 1)

// ── 단추(누르면 접지) — 깊은 잠에서 깨우려면 0~21번 단자여야 함 ──
#define PIN_BTN_PREV 6           // ◀
#define PIN_BTN_NEXT 7           // ▶

// ── 동작 값 ──
#define LISTEN_EVERY_S 3         // 몇 초마다 깨어 「결과 왔나」 들을지
#define LISTEN_MS 60             // 한 번 깨어 듣는 시간
#define SCAN_EVERY 20            // 몇 번 깨어날 때마다 채널 1~13을 훑을지(카메라 채널이 바뀐 경우)
#define IDLE_SLEEP_MS 30000      // 단추 없이 이만큼 지나면 화면 끄고 잠
#define LONG_MS 1000             // 1초 = 길게(◀ 처음 / ▶ 해설)
#define OFF_MS 5000              // ◀ 5초 = 바로 끄기
