// 카메라 장치 설정. 실제 값은 config_local.h 에 넣는다(공개 저장소에 올라가지 않음).
#pragma once

#if __has_include("config_local.h")
#include "config_local.h"
#else
// ── 예시 값(config_local.h 가 없을 때) ──
#define WIFI_LIST { {"와이파이도시락_이름", "비밀번호"}, {"대표휴대폰_핫스팟", "비밀번호"} }
#define RELAY_URL "https://pnqyysuyrovgnmrchrrg.supabase.co/functions/v1/grade-relay"
#define DEVICE_TOKEN "여기에_장치_열쇠"
#define DEVICE_ID "camera-1"
#define GROUP_CODE 0x20261119UL   // 화면 장치와 같은 값
#endif

// ── 보드 고르기: 2 = ESP32-S3-CAM(Diymore N16R8, CH340, C타입 2개) — 확정 보드 / 1 = XIAO ESP32-S3 Sense ──
#ifndef BOARD
#define BOARD 2
#endif

// 단추 4개: 모두 「한 다리는 단자, 다른 다리는 GND」. 깊은 잠에서 깨우려면 0~21번 단자여야 함.
#if BOARD == 2   // ESP32-S3-CAM (ESP32-S3-EYE 와 같은 카메라 배치)
#define CAM_PINS 11,9,8,10,12,18,17,16, 15,13,6,7, 4,5   // d0~d7, xclk, pclk, vsync, href, sda, scl
#define PIN_SHUTTER 1      // 촬영(길게 1.5초 = 새 학생, 8초 = 와이파이 설정)
#define PIN_POWER 3        // 전원(짧게 = 켬·상태 보기, 1.5초 = 끔)
#define PIN_PREV 14        // ◀ 앞 쪽(1초 = 첫 쪽)
#define PIN_NEXT 21        // ▶ 다음 쪽(1초 = 해설 켜고 끔)
#define PIN_LED -1         // 보드 등은 색 등(WS2812)이라 쓰지 않음
// GPIO2 는 일부 보드에서 작은 등이 붙어 있어 단추로 쓰지 않음. 0번은 BOOT 단추.
#else            // XIAO ESP32-S3 Sense
#define CAM_PINS 15,17,18,16,14,12,11,48, 10,13,38,47, 40,39
#define PIN_SHUTTER 1      // D0
#define PIN_POWER 2        // D1
#define PIN_PREV 3         // D2
#define PIN_NEXT 4         // D3
#define PIN_LED 21         // 보드 노란 등(낮으면 켜짐)
#endif
#define PIN_VBAT_ADC -1    // 전지 전압 측정(분압 저항을 달면 단자 번호, 없으면 -1)

// ── 동작 값 ──
#define LONG_PRESS_MS 1500       // 길게 누르면 「새 학생」
#define HTTP_TIMEOUT_MS 170000   // 중계기 최대 대기(구독형 140초 + 여유)
#define WIFI_TRY_MS 10000        // 와이파이 하나당 시도 시간
#define QUEUE_MAX 20             // 못 보낸 사진 최대 보관 장수
#define RETRY_SLEEP_S 300        // 못 보낸 사진이 있으면 5분 뒤 스스로 깨어 다시 보냄
#define READY_BEACON_MS 6000     // 결과 알림을 화면 장치가 받을 때까지 최대 몇 초 반복
#define POWER_OFF_MS 1500        // 전원 단추를 이만큼 누르면 끔
#define PAGE_LONG_MS 1000        // ◀▶ 길게
#define PAGE_STAY_MS 5000        // ◀▶ 누른 뒤 이만큼 깨어 있으며 연달아 넘기기를 받음
