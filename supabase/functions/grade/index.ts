// 예비 중계(슈퍼베이스). 넷리파이가 3초 안에 응답하지 않으면 모듈이 여기로 보낸다.
// _shared/core.mjs 는 배포할 때 relay/core.mjs 를 복사해 넣는다(깃허브 작업).
import { checkToken, gradeImage, loadConfig, mediaOf, meta, record } from "../_shared/core.mjs";

const env = (k: string) => Deno.env.get(k);

Deno.serve(async (req) => {
  if (req.method === "GET") return Response.json({ ok: true, relay: "supabase" });
  if (req.method !== "POST") return new Response("method", { status: 405 });
  // 집지니 프로젝트에 함께 두므로 비밀값 이름 앞에 GRADE_ 를 붙여 섞이지 않게 한다
  if (!checkToken(req.headers.get("x-device-token"), env("GRADE_DEVICE_TOKENS") || env("DEVICE_TOKENS"))) {
    return new Response("unauthorized", { status: 401 });
  }
  const img = new Uint8Array(await req.arrayBuffer());
  if (img.length < 1000 || img.length > 25_000_000) return new Response("bad image", { status: 400 });
  const media = mediaOf(req.headers.get("content-type"));
  const device = req.headers.get("x-device-id") || "unknown";
  const started = Date.now();
  try {
    const config = await loadConfig();
    const { text, model } = await gradeImage({ img, media, apiKey: env("GRADE_ANTHROPIC_KEY") || env("ANTHROPIC_API_KEY"), config });
    // 기록은 같은 프로젝트 안이라 서비스 열쇠로 바로 저장
    await record({
      url: env("SUPABASE_URL"), key: env("SUPABASE_SERVICE_ROLE_KEY"),
      row: { device, relay: "supabase", model, ms: Date.now() - started, result: text, ...meta(text) },
    });
    return new Response(text + "\n", { headers: { "content-type": "text/plain; charset=utf-8" } });
  } catch (e) {
    return new Response("오류: " + ((e as Error)?.message || "알 수 없음") + "\n", {
      status: 502, headers: { "content-type": "text/plain; charset=utf-8" },
    });
  }
});
