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
