// 화면 장치 설정 — GNPE 「ESP32-S3-0.96 MINI」(C 플러그 동글형, 0.96인치 160×80, ST7789, SD 없음)
// 단자 번호는 같은 모양 동글(LILYGO T-Dongle-S3 배치) 기준. 화면이 안 나오면 판매 페이지의 단자 그림과 맞춰 아래만 고친다.
#pragma once
#if __has_include("config_local.h")
#include "config_local.h"
#else
#define GROUP_CODE 0x20261119UL   // 카메라 장치와 같은 값
#endif

// ── 화면 ──
#define TFT_DRIVER_ST7735 0      // 0 = ST7789(판매 표기). 화면이 어긋나거나 색이 이상하면 1 로 바꿔 시험
#define PIN_TFT_SCLK 5
#define PIN_TFT_MOSI 3
#define PIN_TFT_CS   4
#define PIN_TFT_DC   2
#define PIN_TFT_RST  1
#define PIN_TFT_BL   38          // 백라이트
#define TFT_BL_ON    LOW         // 이 동글은 낮을 때 켜짐. 화면이 계속 까맣면 HIGH 로
#define TFT_ROTATION 1           // 가로로 눕히기(뒤집혀 보이면 3)
#define TFT_COL_OFS  26          // ST7789 0.96인치 화면 위치 맞춤(테두리가 잘리면 0·24·26·40 중에서 시험)
#define TFT_ROW_OFS  1
#define TFT_INVERT   1           // 색이 반전돼 보이면 0

// ── 단추: 쪽 넘기기는 카메라 장치의 ◀▶ 로 원격. 동글의 BOOT 단추(0번)도 덤으로 씀 ──
#define PIN_BTN_LOCAL 0          // 짧게 = 다음 쪽, 1초 = 첫 쪽(없애려면 -1)

// ── 동작 값 ──
#define DIM_MS 60000             // 아무 신호 없이 1분 지나면 화면 불만 끔(장치는 계속 들음)
#define MERGE_MS 600000          // 결과 사이가 10분 넘으면 새 학생으로 봄
#define LONG_MS 1000
