# -*- coding: utf-8 -*-
"""
채점 정확도 일괄 시험 — 두 번 눌러 실행(창 없이 결과 창만 뜸).

시험샘플 폴더의 답안지(과목별 그림·피디에프)를 실제 장치와 같은 길(중계)로 보내고,
정답표(key.json)와 비교해 결과를 grade_results\\정확도보고_시각.txt 로 남긴다.
"""
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
RESULT_DIR = Path.home() / "grade_results"
SAMPLE_DIRS = [HERE / "시험샘플", HERE / "시험샘플_고급"]

import tkinter as tk  # noqa: E402

CIRC = {c: str(i) for i, c in enumerate("①②③④⑤⑥⑦⑧⑨", 1)}


def norm(a):
    """답 비교용: 동그라미 숫자 → 숫자, 쉼표·단위·띄어쓰기 제거."""
    a = str(a or "").strip()
    for c, n in CIRC.items():
        if a.startswith(c):
            return n
    a = a.replace(",", "")
    m = re.search(r"-?\d+(\.\d+)?", a)
    if m:
        return m.group(0)
    return re.sub(r"\s+", "", a)


def same(x, y, alts=()):
    nx = norm(x)
    for t in (y, *alts):
        ny = norm(t)
        if nx == ny:
            return True
        try:
            fx, fy = float(nx), float(ny)
            if fy and abs(fx - fy) / abs(fy) < 0.006:
                return True
        except ValueError:
            pass
    return False


def _largest_blob(mask):
    """밝은 덩어리 중 가장 큰 것(=종이)의 테두리 상자. 컵·계산기 같은 작은 물건은 버린다."""
    w, h = mask.size
    px = mask.tobytes()
    seen = bytearray(w * h)
    best, best_box = 0, None
    for start in range(w * h):
        if px[start] == 0 or seen[start]:
            continue
        stack = [start]
        seen[start] = 1
        n, x0, y0, x1, y1 = 0, w, h, 0, 0
        while stack:
            i = stack.pop()
            n += 1
            x, y = i % w, i // w
            x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
            for j in (i - 1 if x else -1, i + 1 if x < w - 1 else -1, i - w, i + w):
                if 0 <= j < w * h and px[j] and not seen[j]:
                    seen[j] = 1
                    stack.append(j)
        if n > best:
            best, best_box = n, (x0, y0, x1 + 1, y1 + 1)
    return best_box


def crop_paper(im):
    """책상 배경에서 밝은 종이 영역만 잘라 글씨를 크게 보낸다(멀리서 찍은 사진 대비)."""
    from PIL import ImageFilter
    g = im.convert("L")
    small = g.copy()
    small.thumbnail((500, 500))
    hist = small.histogram()
    total = sum(hist)
    acc, thr = 0, 200
    for v in range(255, -1, -1):            # 가장 밝은 30% 경계
        acc += hist[v]
        if acc >= total * 0.30:
            thr = max(150, v - 25)
            break
    mask = small.point(lambda v: 255 if v >= thr else 0).filter(ImageFilter.MinFilter(5))
    box = _largest_blob(mask)
    if not box:
        return im
    sx, sy = im.width / small.width, im.height / small.height
    x0, y0, x1, y1 = box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy
    area = (x1 - x0) * (y1 - y0) / (im.width * im.height)
    if not 0.03 < area < 0.40:              # 멀리서 찍어 종이가 작을 때만 자른다(가까운 사진은 그대로)
        return im
    mx, my = (x1 - x0) * 0.08, (y1 - y0) * 0.08
    return im.crop((max(0, int(x0 - mx)), max(0, int(y0 - my)),
                    min(im.width, int(x1 + mx)), min(im.height, int(y1 + my))))


def prepare(path):
    if path.suffix.lower() == ".pdf":
        return path.read_bytes(), "application/pdf"
    import io
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im = crop_paper(im)
        im.thumbnail((1600, 1600))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        return buf.getvalue(), "image/jpeg"


MODELS = [("하이쿠", "claude-haiku-5-5"), ("소넷", "claude-sonnet-5-5"), ("자동", "")]


def send(cfg, raw, ctype, model=""):
    last = ""
    for url in cfg.get("relays", []):
        req = urllib.request.Request(url, data=raw, method="POST", headers={
            "content-type": ctype,
            "x-device-token": cfg.get("token", ""),
            "x-device-id": "accuracy-test",
            "x-grade-model": model,
        })
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                body = r.read().decode("utf-8", "replace").strip()
                used = r.headers.get("x-grade-model", "")
                route = urllib.parse.unquote(r.headers.get("x-grade-route", ""))
                if not model and route:
                    body = f"[자동 선택: {used} · {route}]\n" + body
                if model and used and used != model:
                    body = f"[실제 사용 모델: {used}]\n" + body
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace").strip()
        except Exception as e:
            last = f"연결 실패({e})"
            continue
        if body and not body.startswith("오류"):
            return body
        last = body or "빈 응답(중계가 옛 버전일 수 있음)"
    raise RuntimeError(last or "중계 주소 없음")


def check(fn, key, text):
    import screen as S
    r = S.parse(text)
    got = {}
    for it in r.items:
        got.setdefault(it.no, it)
    rows, n_found, n_judge, n_ans = [], 0, 0, 0
    exp = key["items"]
    for e in exp:
        it = got.get(str(e["no"]))
        if not it:
            rows.append(f"  {e['no']}번  인식 못함")
            continue
        n_found += 1
        kind = "-" if it.blank else ("O" if it.ok else "X")
        ok_judge = kind == e["mark"]
        if e.get("kind") == "text":
            low = re.sub(r"\s+", "", it.answer)
            hits = sum(1 for w in e.get("keywords", []) if re.sub(r"\s+", "", w) in low)
            ok_ans = hits >= max(1, e.get("need", 1))
        else:
            ok_ans = same(it.answer, e["answer"], e.get("alts", []))
        n_judge += ok_judge
        n_ans += ok_ans
        flag = "" if ok_judge and ok_ans else "   ← 틀림"
        rows.append(f"  {e['no']}번  학습자 {e['mine'] or '미표기'} / 정답 {e['answer']}"
                    f"  ⇒ 판정 {kind}({'맞음' if ok_judge else '틀림'}), "
                    f"정답 {it.answer}({'맞음' if ok_ans else '틀림'}){flag}")
    who = (key.get("name") or "") in text
    no_ok = (key.get("exam_no") or "x") in text
    return dict(file=fn, total=len(exp), found=n_found, judge=n_judge, ans=n_ans,
                who=who, exam_no=no_ok, rows=rows,
                score=(r.correct, r.graded, r.unmarked))


class App:
    def __init__(self, root):
        self.root = root
        root.title("채점 정확도 시험")
        root.configure(bg="#111")
        self.txt = tk.Text(root, width=96, height=34, bg="#111", fg="#ddd",
                           font=("맑은 고딕", 10), bd=0, padx=14, pady=12)
        self.txt.pack()
        self.lines = []
        threading.Thread(target=self.run, daemon=True).start()
        self.tick()

    def say(self, s):
        self.lines.append(s)

    def tick(self):
        if self.lines:
            self.txt.insert("end", "\n".join(self.lines) + "\n")
            self.txt.see("end")
            self.lines = []
        self.root.after(200, self.tick)

    def run(self):
        try:
            cfg = json.loads((HERE / "설정.json").read_text(encoding="utf-8"))
        except Exception:
            self.say("설정.json 이 없습니다.")
            return
        keys = {}
        for d in SAMPLE_DIRS:
            kf = d / "key.json"
            if kf.exists():
                for fn, k in json.loads(kf.read_text(encoding="utf-8")).items():
                    keys[fn] = dict(k, _dir=str(d))
        self.say(f"시험 답안지 {len(keys)}장 × 모델 {len(MODELS)}개(하이쿠·소넷·자동) — 동시에 4장씩 채점합니다(15~25분).\n")

        def one(job):
            fn, (mname, mid) = job
            k = keys[fn]
            t0 = time.time()
            try:
                raw, ctype = prepare(Path(k["_dir"]) / fn)
                text = send(cfg, raw, ctype, mid)
                sec = time.time() - t0
                (RESULT_DIR / "정확도_원문").mkdir(parents=True, exist_ok=True)
                (RESULT_DIR / "정확도_원문" / f"{mname}_{fn}.txt").write_text(text, encoding="utf-8")
                if fn.endswith(".pdf"):
                    k = dict(k, items=k["items"])     # 첫 쪽 기준 비교 + 두 쪽 문항 수 점검
                res = check(fn, k, text)
                res.update(sec=sec, cond=k.get("condition", ""), title=k.get("title", ""), model=mname)
                if fn.endswith(".pdf"):
                    res["pdf_lines"] = len(re.findall(r"^\s*\d+\s*번\s*\|", text, re.M))
                self.say(f"끝: [{mname}] {fn}  ({sec:.1f}초)  문항 {res['found']}/{res['total']} · "
                         f"판정 {res['judge']}/{res['total']} · 정답 {res['ans']}/{res['total']}")
                return res
            except Exception as e:
                self.say(f"실패: [{mname}] {fn}  {e}")
                return dict(file=fn, error=str(e), sec=time.time() - t0, model=mname,
                            cond=k.get("condition", ""), title=k.get("title", ""))

        with ThreadPoolExecutor(4) as ex:
            jobs = [(fn, m) for m in MODELS for fn in keys]
            results = list(ex.map(one, jobs))

        rep = [f"채점 정확도 시험  {time.strftime('%Y-%m-%d %H:%M')}", ""]
        summary = []
        for mname, _ in MODELS:
            tot = dict(total=0, found=0, judge=0, ans=0)
            secs = []
            rep.append(f"#### {mname}")
            for r in [x for x in results if x.get("model") == mname]:
                rep.append(f"■ {r['file']}  [{r.get('title','')} · {r.get('cond','')}]  {r['sec']:.1f}초")
                if "error" in r:
                    rep.append(f"  실패: {r['error']}")
                    continue
                secs.append(r["sec"])
                for k2 in tot:
                    tot[k2] += r[k2]
                rep.append(f"  수험번호 {'읽음' if r['exam_no'] else '못 읽음'} · 이름 {'읽음' if r['who'] else '못 읽음'}"
                           f" · 점수 줄 {r['score'][0]}/{r['score'][1]} (미표기 {r['score'][2]})")
                if "pdf_lines" in r:
                    rep.append(f"  피디에프 두 쪽 문항 줄 수: {r['pdf_lines']} (기대 12)")
                rep += r["rows"]
                rep.append("")
            if tot["total"]:
                line = (f"{mname}  문항 인식 {tot['found']}/{tot['total']} · 판정 {tot['judge']}/{tot['total']} "
                        f"({100*tot['judge']/tot['total']:.0f}%) · 정답 {tot['ans']}/{tot['total']} "
                        f"({100*tot['ans']/tot['total']:.0f}%)")
                if secs:
                    line += f" · 시간 평균 {sum(secs)/len(secs):.1f}초(최소 {min(secs):.1f}, 최대 {max(secs):.1f})"
                summary.append(line)
                by = {}
                for r in [x for x in results if x.get("model") == mname and "error" not in x]:
                    fld = r.get("title", "").split()[0]
                    b = by.setdefault(fld, [0, 0, 0])
                    b[0] += r["total"]; b[1] += r["judge"]; b[2] += r["ans"]
                for fld, (t, j, a) in by.items():
                    summary.append(f"    {fld}: 판정 {j}/{t} · 정답 {a}/{t}")
        rep.append("=" * 60)
        rep += summary
        out = RESULT_DIR / f"정확도보고_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        RESULT_DIR.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(rep), encoding="utf-8")
        self.say("\n" + "\n".join(summary) + f"\n\n보고 파일: {out}")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
