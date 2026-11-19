// 주 중계(넷리파이). 모듈 → 여기 → 클로드 → 모듈.
// 클로드가 쓰는 동안 몇 초마다 빈칸을 흘려 보내 연결이 끊기지 않게 한다(흘려 보내기 응답).
import { checkToken, gradeAuto, loadConfig, mediaOf, meta, record } from "../../relay/core.mjs";

export const config = { path: "/api/grade" };
const enc = new TextEncoder();
const env = (k) => Netlify.env.get(k);

export default async (req) => {
  if (req.method === "GET") return Response.json({ ok: true, relay: "netlify" });
  if (req.method !== "POST") return new Response("method", { status: 405 });
  if (!checkToken(req.headers.get("x-device-token"), env("DEVICE_TOKENS"))) {
    return new Response("unauthorized", { status: 401 });
  }
  const img = new Uint8Array(await req.arrayBuffer());
  if (img.length < 1000 || img.length > 25_000_000) return new Response("bad image", { status: 400 });
  const media = mediaOf(req.headers.get("content-type"));
  const device = req.headers.get("x-device-id") || "unknown";
  const started = Date.now();

  const stream = new ReadableStream({
    async start(ctrl) {
      const beat = setInterval(() => ctrl.enqueue(enc.encode(" ")), 3000);
      try {
        const config = await loadConfig();
        const { text, model, route } = await gradeAuto({ img, media, apiKey: env("ANTHROPIC_API_KEY"), config, prefer: req.headers.get("x-grade-model") || "" });
        ctrl.enqueue(enc.encode("\n" + text + "\n"));
        await record({
          url: env("SUPABASE_URL"), key: env("SUPABASE_SERVICE_KEY"),
          row: { device, relay: "netlify", model: model + " · " + route, ms: Date.now() - started, result: text, ...meta(text) },
        });
      } catch (e) {
        ctrl.enqueue(enc.encode("\n오류: " + (e && e.message ? e.message : "알 수 없음") + "\n"));
      } finally {
        clearInterval(beat);
        ctrl.close();
      }
    },
  });
  return new Response(stream, { headers: { "content-type": "text/plain; charset=utf-8" } });
};
