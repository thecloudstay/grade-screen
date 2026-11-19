// 채점 중계기(슈퍼베이스, 함수 이름 grade-relay).
// _shared/core.mjs 는 배포할 때 relay/core.mjs 를 복사해 넣는다(깃허브 작업).
//
// 대표 결정(2026-11-19): 기본은 구독형 — 사진을 대기열(grade_jobs)에 넣고 대표 컴퓨터의
// 「채점일꾼」이 정액 구독 클로드로 채점한다. 컴퓨터가 꺼져 있거나 일꾼이 못 받으면 클로드 키로 채점.
//
//   POST /grade-relay                 장치·시뮬레이터: 사진 보내고 결과 받기(예전과 같음)
//   POST /grade-relay/worker/next     채점일꾼: 살아 있음 알림 + 다음 사진 받기(최대 25초 기다림)
//                                     머리 x-worker-standby: 1 = 쉬는 중(되살림 일만 받음)
//
// 자동 전환(양방향):
//   구독형 → 토큰: 일꾼이 꺼짐·쉬는 중·15초 안에 안 집어 감·실패·80초 넘김
//   토큰 → 구독형: 클로드 키 채점이 실패(충전금 소진·키 문제·연결 끊김)했는데 컴퓨터가 켜져 있으면
//                  쉬는 중인 일꾼에게도 「되살림」으로 맡긴다
//   POST /grade-relay/worker/result   채점일꾼: 결과 올리기
import {
  checkToken, claimJob, enqueue, gradeAuto, heartbeat, loadConfig, mediaOf, meta, record,
  setJob, SYSTEM, waitJob, workerAlive,
} from "../_shared/core.mjs";

const env = (k: string) => Deno.env.get(k);
const SB = () => ({ url: env("SUPABASE_URL")!, key: env("SUPABASE_SERVICE_ROLE_KEY")! });
const txt = (body: string, status = 200, extra: Record<string, string> = {}) =>
  new Response(body, { status, headers: { "content-type": "text/plain; charset=utf-8", ...extra } });

async function workerNext(req: Request) {
  const worker = req.headers.get("x-device-id") || "pc";
  const standby = req.headers.get("x-worker-standby") === "1";
  const { url, key } = SB();
  const config = await loadConfig();
  const q = config.queue || {};
  const until = Date.now() + 25_000;
  while (Date.now() < until) {
    await heartbeat({ url, key, worker, note: standby ? "standby" : null });
    const job = await claimJob({ url, key, worker, rescueOnly: standby });
    if (job) {
      return Response.json({
        id: job.id, media: job.media, img_b64: job.img_b64,
        system: config.system || SYSTEM, model: q.worker_model || "sonnet",
      });
    }
    await new Promise((ok) => setTimeout(ok, 1500));
  }
  return Response.json({ id: null });
}

async function workerResult(req: Request) {
  const { url, key } = SB();
  const b = await req.json();
  const patch = b.ok
    ? { status: "done", result: String(b.text || "").trim(), model: b.model || "구독", done_at: new Date().toISOString() }
    : { status: "failed", error: String(b.error || "").slice(0, 300), done_at: new Date().toISOString() };
  // 이미 취소된(시간 넘어 클로드 키로 넘어간) 일은 덮어쓰지 않는다
  const n = await setJob({ url, key, id: b.id, patch, onlyStatus: "working" });
  return Response.json({ saved: n > 0 });
  // 주의: 응답 머리값에는 한글을 그대로 넣을 수 없다(ByteString 오류) → 항상 encodeURIComponent
}

Deno.serve(async (req) => {
  const path = new URL(req.url).pathname;
  if (req.method === "GET") return Response.json({ ok: true, relay: "supabase" });
  if (req.method !== "POST") return txt("method", 405);
  // 집지니 프로젝트에 함께 두므로 비밀값 이름 앞에 GRADE_ 를 붙여 섞이지 않게 한다
  if (!checkToken(req.headers.get("x-device-token"), env("GRADE_DEVICE_TOKENS") || env("DEVICE_TOKENS"))) {
    return txt("unauthorized", 401);
  }
  try {
    if (path.endsWith("/worker/next")) return await workerNext(req);
    if (path.endsWith("/worker/result")) return await workerResult(req);
  } catch (e) {
    return txt("오류: " + ((e as Error)?.message || "알 수 없음"), 502);
  }

  const img = new Uint8Array(await req.arrayBuffer());
  if (img.length < 1000 || img.length > 25_000_000) return txt("bad image", 400);
  const media = mediaOf(req.headers.get("content-type"));
  const device = req.headers.get("x-device-id") || "unknown";
  const prefer = req.headers.get("x-grade-model") || "";
  const started = Date.now();
  const { url, key } = SB();
  try {
    const config = await loadConfig();
    const q = config.queue || {};
    let out: { text: string; model: string; route: string } | null = null;

    // 1) 구독형: 대표 컴퓨터 일꾼이 살아 있으면 대기열로 (시험용 모델 지정 요청은 바로 클로드 키로)
    if (q.enabled !== false && !prefer && url && key && await workerAlive({ url, key, sec: q.alive_sec || 45 })) {
      const id = await enqueue({ url, key, img, media, device });
      const got = await waitJob({ url, key, id, pickSec: q.pick_sec || 15, waitSec: q.wait_sec || 80 });
      if (got) out = { ...got, route: "구독" };
    }
    // 2) 토큰 소모형: 컴퓨터가 꺼져 있거나 일꾼이 실패·지연
    if (!out) {
      if (q.enabled !== false && q.api_fallback === false && !prefer) {
        return txt("오류: 채점 컴퓨터가 꺼져 있습니다\n", 503);
      }
      try {
        const r = await gradeAuto({ img, media, apiKey: env("GRADE_ANTHROPIC_KEY") || env("ANTHROPIC_API_KEY"), config, prefer });
        out = { text: r.text, model: r.model, route: "토큰 " + r.route };
      } catch (e) {
        // 3) 토큰 소모형이 끊김 → 컴퓨터가 켜져 있으면(쉬는 중이어도) 다시 구독형으로
        const spent = (Date.now() - started) / 1000;
        if (q.enabled !== false && url && key && spent < 60 &&
            await workerAlive({ url, key, sec: 90, standby: true })) {
          const id = await enqueue({ url, key, img, media, device, rescue: true });
          const got = await waitJob({ url, key, id, pickSec: 30, waitSec: Math.min(80, 140 - spent) });
          if (got) out = { ...got, route: "구독(토큰 실패 후 되돌림)" };
        }
        if (!out) throw e;
      }
    }
    await record({
      url, key,
      row: { device, relay: "supabase", model: out.model + " · " + out.route, ms: Date.now() - started, result: out.text, ...meta(out.text) },
    });
    return txt(out.text + "\n", 200, { "x-grade-model": encodeURIComponent(out.model), "x-grade-route": encodeURIComponent(out.route) });
  } catch (e) {
    return txt("오류: " + ((e as Error)?.message || "알 수 없음") + "\n", 502);
  }
});
