// 채점 중계 공통 부분 — 넷리파이 함수(Node)와 슈퍼베이스 함수(Deno)가 함께 쓴다.
// 이 파일을 고치고 깃허브에 올리면 두 중계가 자동으로 같은 내용으로 바뀐다.

export const SYSTEM = [
  "You grade a practice sheet that the learner has already solved. ",
  "For each numbered question in the image, read the answer the learner marked or wrote. ",
  "Then work out the correct answer yourself and judge the learner's answer. ",
  "If a question has no marked or written answer, count it as unmarked: do not grade it, ",
  "but still solve it and give its correct answer in the unmarked line format below. ",
  "The photo may be taken close up, from far away, at an angle, tilted, in shadow or slightly blurred: ",
  "read every part of the sheet carefully before answering. ",
  "Write everything in Korean. No introductions and no markdown.\n",
  // 결과가 먼저 화면에 뜨도록 점수·문항을 앞에, 해설은 뒤에 몰아서 쓴다(흘려 보내기 대비)
  "Output in this exact order.\n",
  "Line 1: 수험번호: <exam number on the sheet, or 없음> | 이름: <name on the sheet, or 없음>\n",
  "Line 2: 점수: <correct>/<graded> (미표기 <unmarked count>)\n",
  "Line 3: 촬영: <one of 좋음, 멀리서, 기울어짐, 흐림, 어두움, 잘림> (잘린 문항: <numbers or 없음>)\n",
  "Line 4: 판단: 난이도 <쉬움, 보통, 어려움> | 확신 <높음, 낮음>\n",
  "  (어려움 = multi-step calculation, long written answers or specialist reasoning; ",
  "확신 낮음 = any answer you are not sure of, or marks you could not read clearly)\n",
  "For multiple-choice questions always write answers as the choice number followed by its text, e.g. ② 10%.\n",
  "Then one line per graded question, in question order:\n",
  "<number>번 | 내 답: <learner answer> | 정답: <correct answer> | <O or X> | 식: <calculation> | 문항: <first 8 characters of the question text>\n",
  "Then one line per unmarked question:\n",
  "<number>번 | 미표기 | 정답: <correct answer> | 식: <calculation> | 문항: <first 8 characters of the question text>\n",
  "The 식 field is only for questions answered by calculation (math, tax, accounting, cost, quantity, interest, area and so on): ",
  "write the shortest formula chain that reaches the answer with the real numbers, under 40 characters, e.g. 식: 3x+5=20 → x=5 or 식: 1,000만×10%=100만. ",
  "Omit the whole 식 field for questions that need no calculation.\n",
  "Then the line ---\n",
  "Then one line per wrong or unmarked question only:\n",
  "해설 <number>번: <two or three sentences explaining why>\n",
  "Then one last line:\n",
  "취약 부분: <topics the learner should review>\n",
  "If the image is illegible, output exactly: 판독불가",
].join("");

export const USER = "Grade this solved practice sheet as instructed.";

const RETRY = new Set([429, 500, 502, 503, 504, 529]);

export function toBase64(u8) {
  let s = "";
  for (let i = 0; i < u8.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  }
  return btoa(s);
}

export function checkToken(header, tokensEnv) {
  const list = (tokensEnv || "").split(",").map((s) => s.trim()).filter(Boolean);
  return list.length > 0 && list.includes((header || "").trim());
}

// 실행 중 설정: 깃허브의 relay/config.json 을 5분마다 읽는다.
// 모델·최대 길이·생각 설정·지시문을 바꿀 때 함수를 다시 배포하지 않아도 된다.
const CONFIG_URL = "https://raw.githubusercontent.com/thecloudstay/grade-screen/main/relay/config.json";
export const DEFAULT_CONFIG = {
  // 고급 문제(계산·서술) 정확도를 위해 소넷을 먼저, 생각 기능은 켜 두고 길이를 넉넉히
  models: [
    { model: "claude-sonnet-5-5", max_tokens: 16000 },
    { model: "claude-opus-5-5", max_tokens: 16000 },
  ],
  // 대표 결정(2026-11-19): 하이쿠는 오답률이 높아 쓰지 않는다. 소넷 기본, 오퍼스 예비.
  allow_override: ["claude-sonnet-5-5", "claude-opus-5-5"],
  route: null,
  // 대표 결정(2026-11-19): 기본은 구독형(대표 컴퓨터가 채점), 컴퓨터가 꺼져 있으면 클로드 키
  queue: { enabled: true, alive_sec: 45, pick_sec: 15, wait_sec: 80, api_fallback: true, worker_model: "sonnet" },
};

export function needsEscalation(text, words) {
  const line = (text.match(/^\s*판단\s*[:：].*$/m) || [""])[0];
  if (!line) return true;                          // 판단 줄이 없으면 안전하게 올린다
  return (words || []).some((w) => line.includes(w));
}

// 난이도에 따라 모델 자동 선택. prefer(시험용 지정)가 있으면 그 모델만 우선.
export async function gradeAuto({ img, media, apiKey, config, prefer }) {
  const cfg = config || DEFAULT_CONFIG;
  const r = cfg.route;
  if (prefer || !r) return { ...(await gradeImage({ img, media, apiKey, config: cfg, prefer })), route: "지정" };
  const first = await gradeImage({ img, media, apiKey, config: cfg, prefer: r.first });
  if (first.model !== r.first || !needsEscalation(first.text, r.escalate_if)) {
    return { ...first, route: "빠른 채점" };
  }
  try {
    const second = await gradeImage({ img, media, apiKey, config: cfg, prefer: r.escalate });
    return { ...second, route: "어려움→정밀 채점" };
  } catch (_) {
    return { ...first, route: "정밀 채점 실패→빠른 결과" };
  }
}
let _cfg = null, _cfgAt = 0;
export async function loadConfig() {
  if (_cfg && Date.now() - _cfgAt < 300000) return _cfg;
  try {
    const r = await fetch(CONFIG_URL, { signal: AbortSignal.timeout(3000) });
    if (r.ok) { _cfg = { ...DEFAULT_CONFIG, ...(await r.json()) }; _cfgAt = Date.now(); return _cfg; }
  } catch (_) { /* 못 읽으면 기본값 */ }
  return _cfg || DEFAULT_CONFIG;
}

// 사진(jpeg·png·gif·webp)은 그림 칸, 피디에프는 문서 칸으로 보낸다
export function fileBlock(media, data) {
  if (media === "application/pdf") {
    return { type: "document", source: { type: "base64", media_type: media, data } };
  }
  return { type: "image", source: { type: "base64", media_type: media, data } };
}

export function mediaOf(contentType) {
  const c = (contentType || "").toLowerCase();
  if (c.includes("pdf")) return "application/pdf";
  if (c.includes("png")) return "image/png";
  if (c.includes("webp")) return "image/webp";
  if (c.includes("gif")) return "image/gif";
  return "image/jpeg";
}

// 모델 목록 순서대로 시도. 혼잡·일시 장애·빈 응답·거절이면 다음 모델로.
export async function gradeImage({ img, media, apiKey, config, prefer }) {
  if (!apiKey) throw new Error("인증 열쇠 미설정");
  const cfg = config || DEFAULT_CONFIG;
  // 시험용: 요청 머리에 모델을 지정하면 그 모델을 먼저 쓴다(허용 목록 안에서만)
  let list = cfg.models;
  if (prefer && (cfg.allow_override || []).includes(prefer)) {
    const hit = list.find((m) => m.model === prefer) || { model: prefer, max_tokens: 16000 };
    list = [hit, ...list.filter((m) => m.model !== prefer)];
  }
  const data = toBase64(img);
  let last = "";
  for (const m of list) {
    for (let attempt = 0; attempt < 2; attempt++) {
      const body = {
        model: m.model,
        max_tokens: m.max_tokens || 8000,
        system: cfg.system || SYSTEM,
        messages: [{ role: "user", content: [fileBlock(media, data), { type: "text", text: cfg.user || USER }] }],
      };
      if (m.thinking) body.thinking = m.thinking;
      const r = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: { "x-api-key": apiKey, "anthropic-version": "2023-06-01", "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (r.ok) {
        const j = await r.json();
        const text = (j.content || []).filter((b) => b.type === "text").map((b) => b.text).join("\n").trim();
        if (text) return { text, model: m.model, stop: j.stop_reason };
        last = "빈 응답(" + (j.stop_reason || "?") + ")";
        break;                       // 같은 모델로 다시 해도 같으니 다음 모델로
      }
      const err = await r.text().catch(() => "");
      last = r.status + " " + err.slice(0, 120);
      if (!RETRY.has(r.status)) break;   // 요청 형식 문제면 다음 모델로
      await new Promise((ok) => setTimeout(ok, 1500 * (attempt + 1)));
    }
  }
  throw new Error("채점 실패: " + last);
}

// 결과 글에서 기록용 숫자만 뽑는다.
export function meta(text) {
  const m = {};
  const id = text.match(/수험번호\s*[:：]\s*([^|\n]+)/);
  const nm = text.match(/이름\s*[:：]\s*([^|\n]+)/);
  const sc = text.match(/점수\s*[:：]\s*(\d+)\s*\/\s*(\d+)/);
  const un = text.match(/미표기\s*(\d+)\s*\)/);
  m.exam_no = id && !/없음/.test(id[1]) ? id[1].trim() : null;
  m.student_name = nm && !/없음/.test(nm[1]) ? nm[1].trim() : null;
  m.correct = sc ? Number(sc[1]) : null;
  m.graded = sc ? Number(sc[2]) : null;
  m.unmarked = un ? Number(un[1]) : null;
  m.illegible = /판독\s*불가/.test(text);
  return m;
}

// 슈퍼베이스 기록 표(grade_records)에 한 줄 저장. 실패해도 채점 응답은 막지 않는다.
export async function record({ url, key, row }) {
  if (!url || !key) return;
  try {
    await fetch(`${url}/rest/v1/grade_records`, {
      method: "POST",
      headers: {
        apikey: key,
        Authorization: `Bearer ${key}`,
        "content-type": "application/json",
        Prefer: "return=minimal",
      },
      body: JSON.stringify(row),
    });
  } catch (_) { /* 기록 실패는 무시 */ }
}


// ───────── 구독형 채점 대기열 ─────────
// 중계기는 사진을 grade_jobs 에 넣고, 대표 컴퓨터의 「채점일꾼」이 집어 가 정액 구독 클로드로 채점한다.
function sbHeaders(key, extra = {}) {
  return { apikey: key, Authorization: `Bearer ${key}`, "content-type": "application/json", ...extra };
}

// standby=true 면 「쉬는 중」(구독 한도 등으로 물러난) 일꾼도 켜진 것으로 본다
export async function workerAlive({ url, key, sec, standby }) {
  const since = new Date(Date.now() - sec * 1000).toISOString();
  const only = standby ? "" : "&note=is.null";
  const r = await fetch(`${url}/rest/v1/grade_workers?select=id&last_seen=gte.${since}${only}&limit=1`,
    { headers: sbHeaders(key) });
  return r.ok && (await r.json()).length > 0;
}

export async function heartbeat({ url, key, worker, note }) {
  await fetch(`${url}/rest/v1/grade_workers?on_conflict=id`, {
    method: "POST",
    headers: sbHeaders(key, { Prefer: "resolution=merge-duplicates,return=minimal" }),
    body: JSON.stringify({ id: worker, last_seen: new Date().toISOString(), note: note || null }),
  });
}

export async function enqueue({ url, key, img, media, device, rescue }) {
  const r = await fetch(`${url}/rest/v1/grade_jobs`, {
    method: "POST",
    headers: sbHeaders(key, { Prefer: "return=representation" }),
    body: JSON.stringify({ device, media, img_b64: toBase64(img), rescue: !!rescue }),
  });
  if (!r.ok) throw new Error("대기열 넣기 실패 " + r.status);
  return (await r.json())[0].id;
}

async function jobRow({ url, key, id }) {
  const r = await fetch(`${url}/rest/v1/grade_jobs?select=status,result,model,error&id=eq.${id}`,
    { headers: sbHeaders(key) });
  return r.ok ? (await r.json())[0] : null;
}

export async function setJob({ url, key, id, patch, onlyStatus }) {
  const cond = onlyStatus ? `&status=eq.${onlyStatus}` : "";
  const r = await fetch(`${url}/rest/v1/grade_jobs?id=eq.${id}${cond}`, {
    method: "PATCH", headers: sbHeaders(key, { Prefer: "return=representation" }),
    body: JSON.stringify(patch),
  });
  return r.ok ? (await r.json()).length : 0;
}

// 결과를 기다린다. pick_sec 안에 아무도 안 집어 가거나, 일꾼이 실패하거나, wait_sec 이 넘으면 null
export async function waitJob({ url, key, id, pickSec, waitSec }) {
  const start = Date.now();
  while (Date.now() - start < waitSec * 1000) {
    await new Promise((ok) => setTimeout(ok, 1000));
    const row = await jobRow({ url, key, id });
    if (!row) return null;
    if (row.status === "done" && row.result) return { text: row.result, model: row.model || "구독" };
    if (row.status === "failed") return null;
    if (row.status === "pending" && Date.now() - start > pickSec * 1000) {
      // 아무도 안 집어 감 → 취소(늦게 집어 가지 않게) 후 클로드 키로
      if (await setJob({ url, key, id, patch: { status: "cancelled" }, onlyStatus: "pending" })) return null;
    }
  }
  await setJob({ url, key, id, patch: { status: "cancelled" } });
  return null;
}

export async function claimJob({ url, key, worker, rescueOnly }) {
  const r = await fetch(`${url}/rest/v1/rpc/grade_claim`, {
    method: "POST", headers: sbHeaders(key), body: JSON.stringify({ p_worker: worker, p_rescue_only: !!rescueOnly }),
  });
  if (!r.ok) return null;
  const rows = await r.json();
  return rows && rows[0] ? rows[0] : null;
}
