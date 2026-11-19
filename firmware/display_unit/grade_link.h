// 카메라 장치 ↔ 화면 장치 무선(ESP-NOW) 약속. 두 펌웨어가 같은 파일을 쓴다.
//
// - 짝 맺기 없이 「묶음 번호」(GROUP)가 같은 장치끼리만 알아듣는 방송 방식.
//   (공장 출고처럼 두 장치에 같은 번호를 넣어 두면 끝 — 짝 맺기 단계 없음)
// - 무선 채널은 1번으로 고정(GL_CHANNEL). 카메라 장치는 화면 장치와 말할 때 와이파이를 잠깐 끊고 1번으로 옮긴다.
//   그래서 화면 장치는 채널을 찾을 필요 없이 늘 1번만 듣는다.
#pragma once
#include <stdint.h>

#define GL_MAGIC 0x4753       // 'GS'
#define GL_PAYLOAD 200        // 한 조각에 실을 글자(바이트) 수
#define GL_CHANNEL 1          // 두 장치가 말하는 무선 채널(고정)

enum : uint8_t {
  GL_READY = 1,    // 카메라 → 화면: 「새 결과 있음」(id) — 화면이 잠깐 깨어 듣는 신호
  GL_CHUNK = 2,    // 카메라 → 화면: 결과 글 조각(id, part/total)
  GL_ACK = 3,      // 화면 → 카메라: id 다 받음
  GL_STATUS = 4,   // 카메라 → 화면: 상태·오류 번호(E1 등) + 짧은 글
  GL_NEWSTUDENT = 5,  // 카메라 → 화면: 새 학생(여러 장 합치기 끊기)
  GL_PAGE = 6,     // 카메라 → 화면: 쪽 넘기기(payload[0] = GL_CMD_*) — 화면은 같은 id 로 ACK
  GL_POWER = 7,    // 카메라 → 화면: payload[0] = '1' 켬 / '0' 끔(화면 불 끔)
};

// 쪽 넘기기 명령(GL_PAGE 의 payload[0])
#define GL_CMD_PREV 'P'    // ◀ 짧게: 앞 쪽
#define GL_CMD_NEXT 'N'    // ▶ 짧게: 다음 쪽
#define GL_CMD_FIRST 'F'   // ◀ 1초: 첫 쪽(바둑판)
#define GL_CMD_NOTES 'T'   // ▶ 1초: 해설 켜기/끄기

#pragma pack(push, 1)
struct GlPacket {
  uint16_t magic;
  uint32_t group;     // 묶음 번호(두 장치가 같아야 함)
  uint8_t type;
  uint16_t id;        // 결과 번호(촬영마다 1씩 증가)
  uint8_t part;       // 조각 번호(0부터)
  uint8_t total;      // 전체 조각 수
  uint8_t len;        // payload 길이
  char payload[GL_PAYLOAD];
};
#pragma pack(pop)

// 상태 번호(화면 장치에 그대로 뜸)
#define GL_E_WIFI "E1 와이파이 없음 · 핫스팟 켜 주세요"
#define GL_E_NET "E2 인터넷 안 됨"
#define GL_E_RELAY "E3 전송 대기"
#define GL_E_CAMERA "E4 카메라 인식 실패"
#define GL_E_POWER "E5 전원 약함 · 전지 확인"
#define GL_S_SENDING "채점 중…"
