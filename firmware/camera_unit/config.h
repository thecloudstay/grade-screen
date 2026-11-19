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

// ── 보드 고르기: 1 = XIAO ESP32-S3 Sense(초소형, 전지 충전 내장) / 2 = ESP32-S3-CAM(N16R8, CH340, C타입 2개) ──
#ifndef BOARD
#define BOARD 1
#endif

#if BOARD == 1
#define CAM_PINS 15,17,18,16,14,12,11,48, 10,13,38,47, 40,39   // d0~d7, xclk, pclk, vsync, href, sda, scl
#define PIN_SHUTTER 1      // 촬영 단추(D0 = GPIO1) — 깊은 잠에서 깨우는 단자, 누르면 접지
#define PIN_LED 21         // 보드 노란 등(낮으면 켜짐)
#else   // ESP32-S3-CAM (ESP32-S3-EYE 와 같은 배치) — 실물 표기로 한 번 더 확인
#define CAM_PINS 11,9,8,10,12,18,17,16, 15,13,6,7, 4,5
#define PIN_SHUTTER 1      // 빈 단자 GPIO1 에 단추
#define PIN_LED -1         // 보드 등은 색 등(WS2812)이라 쓰지 않음
#endif
#define PIN_VBAT_ADC -1    // 전지 전압 측정(분압 저항을 달면 단자 번호, 없으면 -1)

// ── 동작 값 ──
#define LONG_PRESS_MS 1500       // 길게 누르면 「새 학생」
#define HTTP_TIMEOUT_MS 170000   // 중계기 최대 대기(구독형 140초 + 여유)
#define WIFI_TRY_MS 10000        // 와이파이 하나당 시도 시간
#define QUEUE_MAX 20             // 못 보낸 사진 최대 보관 장수
#define RETRY_SLEEP_S 300        // 못 보낸 사진이 있으면 5분 뒤 스스로 깨어 다시 보냄
#define READY_BEACON_MS 6000     // 결과 알림을 화면 장치가 받을 때까지 최대 몇 초 반복
