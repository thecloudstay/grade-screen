"""큐넷 공개 기출 문제지(PDF) → 학습자가 푼 것처럼 표시한 답안지 사진 + 정답표(key.json).

- 쪽마다 문항 번호와 보기(①~⑤) 위치를 PDF 글자 좌표에서 찾고
- 학습자 답을 펜 동그라미로 그린다(정답 65% · 오답 25% · 미표기 10%, 고정 난수)
- 사진처럼 약간 기울이고 밝기·잡음을 준다
- 정답은 큐넷 최종정답(공공누리 1유형)

쓰는 법: python3 make_gichul.py <원본 폴더> <출력 폴더>
"""
import json
import math
import random
import re
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

CIRC = "①②③④⑤"

# 시험별: 파일, 문항 범위, 정답(큐넷 최종정답 A형)
EXAMS = [
    dict(tag="세무사_회계학개론", title="세무사 1차 회계학개론(2026 제63회)",
         pdf_hint=("세무사", "2교시"), rng=(1, 40),
         ans="4 2 3 1 5 3 2 4 1 1 1 5 1 2 2 4 3 2 4 3 4 4 5 5 1 3 2 5 4 1 3 1 1 4 5 2 3 5 4 5"),
    dict(tag="관세사_관세법개론", title="관세사 1차 관세법개론(2026 제43회)",
         pdf_hint=("관세사", "1교시"), rng=(1, 40),
         ans="4 1 2 2 2 3 1 1 3 5 2 4 2 1 5 1 5 5 3 2 4 3 4 4 3 4 3 3 5 2 2 4 2 5 5 1 5 1 1 3"),
    dict(tag="행정사_행정법", title="행정사 1차 행정법(2026 제14회)",
         pdf_hint=("행정사", ""), rng=(26, 50),
         ans="4 3 5 2 4 1 3 3 3 1 2 5 4 2 1 1 4 2 4 1 3 3 5 5 4"),
]


def find_pdf(src, hint):
    a, b = hint
    for p in sorted(src.glob("*.pdf")):
        if a in p.name and (not b or b in p.name):
            return p
    return None


def layout(page):
    """문항 번호와 보기 글자 위치. 두 단 편집을 고려해 단(왼/오)별로 읽는다."""
    W = page.rect.width
    qs, chs = [], []
    d = page.get_text("rawdict")
    for blk in d["blocks"]:
        for line in blk.get("lines", []):
            chars = [c for sp in line["spans"] for c in sp["chars"]]
            text = "".join(c["c"] for c in chars)
            m = re.match(r"\s*(\d{1,2})\s*\.", text)
            if m:
                x0, y0 = chars[0]["bbox"][:2]
                qs.append((int(m.group(1)), x0, y0))
            for c in chars:
                if c["c"] in CIRC:
                    x0, y0, x1, y1 = c["bbox"]
                    chs.append((CIRC.index(c["c"]) + 1, (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0))
    col = lambda x: 0 if x < W / 2 else 1
    out = {}
    for k, cx, cy, w in chs:
        cands = [q for q in qs if col(q[1]) == col(cx) and q[2] <= cy + 2]
        if not cands:
            continue
        q = max(cands, key=lambda t: t[2])
        out.setdefault(q[0], {})
        out[q[0]].setdefault(k, (cx, cy, w))
    return out


def pen_circle(d, x, y, r, rnd, color):
    pts = []
    start = rnd.uniform(0, 2 * math.pi)
    for i in range(34):
        t = start + i / 30 * 2 * math.pi
        rr = r * (1 + rnd.uniform(-0.08, 0.1))
        pts.append((x + rr * 1.15 * math.cos(t), y + rr * math.sin(t)))
    d.line(pts, fill=color, width=max(3, int(r / 5)), joint="curve")


def photo(img, rnd):
    img = img.rotate(rnd.uniform(-2.5, 2.5), resample=Image.BICUBIC, expand=True, fillcolor=(90, 88, 84))
    img = ImageEnhance.Brightness(img).enhance(rnd.uniform(0.85, 1.05))
    img = img.filter(ImageFilter.GaussianBlur(rnd.uniform(0.2, 0.6)))
    return img


def main(src, dst):
    src, dst = Path(src), Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(20261119)
    keys = {}
    for ex in EXAMS:
        pdf = find_pdf(src, ex["pdf_hint"])
        if not pdf:
            print("문제지 없음:", ex["tag"])
            continue
        answers = dict(zip(range(ex["rng"][0], ex["rng"][1] + 1), map(int, ex["ans"].split())))
        doc = pymupdf.open(pdf)
        for pno, page in enumerate(doc):
            lay = {q: v for q, v in layout(page).items() if q in answers}
            if not lay:
                continue
            zoom = 2.0
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            d = ImageDraw.Draw(img)
            pen = rnd.choice([(25, 45, 140), (30, 30, 30)])
            items = []
            for q in sorted(lay):
                a = answers[q]
                roll = rnd.random()
                if roll < 0.10 or len(lay[q]) < 5:
                    mine, mark = None, "-"
                elif roll < 0.35:
                    mine = rnd.choice([k for k in lay[q] if k != a] or [a])
                    mark = "O" if mine == a else "X"
                else:
                    mine, mark = a, "O"
                if mine:
                    cx, cy, w = lay[q][mine]
                    pen_circle(d, cx * zoom, cy * zoom, w * zoom * 0.95, rnd, pen)
                items.append(dict(no=q, mark=mark, mine=CIRC[mine - 1] if mine else "",
                                  answer=CIRC[a - 1], alts=[]))
            fn = f"{ex['tag']}_{pno + 1:02d}쪽.jpg"
            photo(img, rnd).convert("RGB").save(dst / fn, quality=88)
            keys[fn] = dict(exam_no="", name="", items=items, title=ex["title"],
                            condition="기출 원본·펜 표시·약간 기울임", file=fn)
            print(fn, len(items), "문항")
    (dst / "key.json").write_text(json.dumps(keys, ensure_ascii=False, indent=1), encoding="utf-8")
    print("총", len(keys), "장,", sum(len(k["items"]) for k in keys.values()), "문항")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
