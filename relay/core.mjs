// 채점 중계 공통 부분 — 넷리파이 함수(Node)와 슈퍼베이스 함수(Deno)가 함께 쓴다.
// 이 파일을 고치고 깃허브에 올리면 두 중계가 자동으로 같은 내용으로 바뀐다.

export const SYSTEM = [
  "You grade a practice sheet that the learner has already solved. ",
  "For each numbered question in the image, read the answer the learner marked or wrote. ",
  "Then work out the correct answer yourself and judge the learner's answer. ",
  "If a question has no marked or written answer, count it as unmarked: do not grade it, ",
  "but still solve it and give its correct answer in the unmarked line format below. ",
  "Write everything in Korean. No introductions and no markdown.\n",
  // 결과가 먼저 화면에 뜨도록 점수·문항을 앞에, 해설은 뒤에 몰아서 쓴다(흘려 보내기 대비)
  "Output in this exact order.\n",
  "Line 1: 수험번호: <exam number on the sheet, or 없음> | 이름: <name on the sheet, or 없음>\n",
  "Line 2: 점수: <correct>/<graded> (미표기 <unmarked count>)\n",
  "Then one line per graded question, in question order:\n",
  "<number>번 | 내 답: <learner answer> | 정답: <correct answer> | <O or X>\n",
  "Then one line per unmarked question:\n",
  "<number>번 | 미표기 | 정답: <correct answer>\n",
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

// 모델 목록 순서대로 시도. 혼잡·일시 장애면 잠시 뒤 재시도 → 다음 모델.
export async function gradeImage({ img, media, apiKey, models }) {
  if (!apiKey) throw new Error("인증 열쇠 미설정");
  const data = toBase64(img);
  let last = "";
  for (const model of models) {
    for (let attempt = 0; attempt < 2; attempt++) {
      const r = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
          "x-api-key": apiKey,
          "anthropic-version": "2023-06-01",
          "content-type": "application/json",
        },
        body: JSON.stringify({
          model,
          max_tokens: 3000,
          system: SYSTEM,
          messages: [{
            role: "user",
            content: [
              { type: "image", source: { type: "base64", media_type: media, data } },
              { type: "text", text: USER },
            ],
          }],
        }),
      });
      if (r.ok) {
        const j = await r.json();
        const text = (j.content || [])
          .filter((b) => b.type === "text")
          .map((b) => b.text)
          .join("\n")
          .trim();
        return { text, model };
      }
      last = String(r.status);
      if (!RETRY.has(r.status)) throw new Error("채점 요청 실패 " + r.status);
      await new Promise((ok) => setTimeout(ok, 1500 * (attempt + 1)));
    }
  }
  throw new Error("채점 서버 혼잡 " + last);
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
