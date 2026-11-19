# 집지니 프로젝트 전달 — 채점 중계기 「구독형 + 자동 전환」 배포 (2026-11-19)

대표 결정: 채점은 기본 **구독형**(대표 컴퓨터의 채점일꾼이 정액 구독 클로드로 채점), 컴퓨터가 꺼져 있으면 **토큰 소모형**(GRADE_ANTHROPIC_KEY). 양방향 자동 전환.

## 해 줄 일 (2가지)

1. **슈퍼베이스 SQL 실행** (프로젝트 pnqyysuyrovgnmrchrrg)
   - 저장소 thecloudstay/grade-screen 의 `supabase/schema.sql` 전체를 실행 (모두 `if not exists`/`or replace` 라 여러 번 실행해도 안전)
   - 새로 생기는 것: 표 `grade_jobs`, `grade_workers`, 함수 `grade_claim(text, boolean)`, `grade_jobs_cleanup()`
   - 선택: 예약 작업으로 하루 한 번 `select public.grade_jobs_cleanup();`
2. **grade-relay 함수 다시 배포** (기존 grade-relay.yml 작업 그대로 실행 — grade-screen 의 최신 main 을 받아 `relay/core.mjs` → `_shared/core.mjs` 복사 후 배포)
   - 새 경로: `POST .../grade-relay/worker/next`, `POST .../grade-relay/worker/result` (같은 함수 안, 장치 열쇠 GRADE_DEVICE_TOKENS 로 인증)
   - 새 비밀값 없음. SUPABASE_URL·SUPABASE_SERVICE_ROLE_KEY(기본 제공) 사용

## 확인

- 배포 후 `GET .../grade-relay` → `{"ok":true,"relay":"supabase"}`
- 대표 컴퓨터 채점일꾼이 켜지면 `grade_workers` 에 `pc-worker` 줄이 25초마다 갱신
- 채점 결과 머리 `x-grade-route` 가 「구독」이면 구독형, 「토큰 …」이면 토큰 소모형
- 설정 전환(배포 없이): grade-screen `relay/config.json` 의 `queue` — `enabled:false` 면 예전처럼 토큰만, `api_fallback:false` 면 토큰 소모 완전 차단
