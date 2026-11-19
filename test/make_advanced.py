# -*- coding: utf-8 -*-
"""고급 문제 100개 → 답안지 20장(장당 5문항) + 정답표.  실행: python3 test/make_advanced.py"""
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw

from advanced_bank import BANK
from make_samples import BOLD, SANS, SERIF, STUDENTS, f, hand, photo, wrap

OUT = Path(__file__).resolve().parent / "samples_advanced"

CONDS = [
    dict(rot=0.0, shadow=0.0, blur=0.0, scale=1.0, name="깨끗한 스캔"),
    dict(rot=1.2, shadow=0.2, blur=0.5, scale=0.9, name="약간 기운 사진"),
    dict(rot=-2.0, shadow=0.3, blur=0.7, scale=0.8, name="그림자 진 사진"),
    dict(rot=2.8, shadow=0.15, blur=0.9, scale=0.75, name="기울고 흐린 사진"),
]


def hand_lines(img, x, y, text, size, width):
    d = ImageDraw.Draw(img)
    for line in wrap(d, text, f(SERIF, size), width):
        hand(img, (x, y), line, size)
        y += int(size * 1.45)
    return y


def sheet(field, part, qs, seed):
    rnd = random.Random(seed)
    W, H = 1240, 1754
    img = Image.new("RGB", (W, H), (252, 252, 248))
    d = ImageDraw.Draw(img)
    d.text((80, 66), f"{field} 고급 평가 ({part})", font=f(BOLD, 38), fill=(20, 20, 20))
    exam_no = f"2026-A{seed:03d}"
    name = STUDENTS[seed % len(STUDENTS)]
    d.text((80, 136), "수험번호", font=f(SANS, 24), fill=(60, 60, 60))
    d.text((620, 136), "성명", font=f(SANS, 24), fill=(60, 60, 60))
    d.line([(190, 168), (560, 168)], fill=(120, 120, 120), width=1)
    d.line([(690, 168), (1000, 168)], fill=(120, 120, 120), width=1)
    hand(img, (210, 124), exam_no, 30)
    hand(img, (710, 124), name, 32)
    d.line([(80, 196), (W - 80, 196)], fill=(40, 40, 40), width=2)
    plan = ["O", "O", "X", "X", "-"][: len(qs)]
    rnd.shuffle(plan)
    y, items = 232, []
    for i, (q, kind, ans, alts, kw, need, wrong) in enumerate(qs, 1):
        mark = plan[i - 1]
        for k, line in enumerate(wrap(d, f"{i}. {q}", f(SANS, 26), W - 200)):
            d.text((80 if k == 0 else 110, y), line, font=f(SANS, 26), fill=(25, 25, 25))
            y += 38
        y += 8
        d.text((110, y), "답 :", font=f(SANS, 24), fill=(35, 35, 35))
        box_h = 120 if kind == "text" else 54
        for ly in range(y + 40, y + box_h + 1, 40):
            d.line([(165, ly), (W - 110, ly)], fill=(170, 170, 170), width=1)
        mine = ans if mark == "O" else wrong if mark == "X" else ""
        if mine:
            shown = f"{int(mine):,}" if kind == "num" and mine.isdigit() and len(mine) > 3 else mine
            hand_lines(img, 185, y - 4, shown, 28, W - 330)
        y += box_h + 30
        items.append(dict(no=i, mark=mark, mine=mine, answer=ans, alts=alts,
                          kind=kind, keywords=kw, need=need))
    return img, dict(exam_no=exam_no, name=name, items=items)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    keys, n = {}, 0
    for field, qs in BANK.items():
        for p, s in enumerate(range(0, len(qs), 5), 1):
            n += 1
            img, k = sheet(field, p, qs[s:s + 5], n * 11)
            cond = CONDS[n % len(CONDS)]
            fn = f"A{n:02d}_{field}_{p}.jpg"
            photo(img, cond, n).save(OUT / fn, quality=82)
            k.update(title=f"{field} 고급 {p}", condition=cond["name"], file=fn)
            keys[fn] = k
    (OUT / "key.json").write_text(json.dumps(keys, ensure_ascii=False, indent=1), encoding="utf-8")
    print("고급 답안지:", len(keys), "장 /", sum(len(k["items"]) for k in keys.values()), "문항")


if __name__ == "__main__":
    main()
