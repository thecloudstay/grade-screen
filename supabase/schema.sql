-- 채점 기록 표 (집지니 표와 섞이지 않게 grade_ 로 시작)
create table if not exists public.grade_records (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  device text,
  relay text,
  model text,
  ms integer,
  exam_no text,
  student_name text,
  correct integer,
  graded integer,
  unmarked integer,
  illegible boolean default false,
  result text
);
alter table public.grade_records enable row level security;
-- 서비스 열쇠로만 쓰고 읽는다(공개 읽기 없음)
create index if not exists grade_records_created_idx on public.grade_records (created_at desc);

-- ───────── 구독형 채점 대기열 (2026-11-19) ─────────
-- 기본은 대표 컴퓨터(정액 구독 클로드)가 채점, 컴퓨터가 꺼져 있으면 중계기가 클로드 키로 채점
create table if not exists public.grade_jobs (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  status text not null default 'pending',   -- pending → working → done / failed / cancelled
  device text,
  media text,
  img_b64 text,
  result text,
  model text,
  error text,
  worker text,
  picked_at timestamptz,
  done_at timestamptz,
  rescue boolean not null default false     -- 토큰 소모형이 실패해 구독형으로 되돌린 일
);
alter table public.grade_jobs add column if not exists rescue boolean not null default false;
alter table public.grade_jobs enable row level security;
create index if not exists grade_jobs_pending_idx on public.grade_jobs (status, id);

create table if not exists public.grade_workers (
  id text primary key,
  last_seen timestamptz not null default now(),
  note text
);
alter table public.grade_workers enable row level security;

-- 대기 중인 사진 하나를 겹치지 않게 집어 간다(일꾼이 둘이어도 안전)
drop function if exists public.grade_claim(text);
create or replace function public.grade_claim(p_worker text, p_rescue_only boolean default false)
returns setof public.grade_jobs
language sql security definer set search_path = public as $$
  update public.grade_jobs j set status = 'working', worker = p_worker, picked_at = now()
  where j.id = (
    select id from public.grade_jobs
    where status = 'pending' and created_at > now() - interval '3 minutes'
      and (not p_rescue_only or rescue)
    order by id limit 1 for update skip locked)
  returning j.*;
$$;
revoke all on function public.grade_claim(text, boolean) from public, anon, authenticated;

-- 하루 지난 사진 원본은 지운다(기록은 grade_records 에 남음)
create or replace function public.grade_jobs_cleanup() returns void
language sql security definer set search_path = public as $$
  delete from public.grade_jobs where created_at < now() - interval '1 day';
$$;

-- ───────── 채점 설정 토글 (2026-11-19) ─────────
-- 대표가 시뮬레이터에서 켜고 끄는 값. 예: api_fallback = 컴퓨터가 꺼졌을 때 토큰 소모형으로 넘길지
create table if not exists public.grade_settings (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz not null default now()
);
alter table public.grade_settings enable row level security;
insert into public.grade_settings(key, value) values ('api_fallback', 'false'::jsonb)
  on conflict (key) do nothing;
