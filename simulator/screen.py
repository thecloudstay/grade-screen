# -*- coding: utf-8 -*-
"""
0.96인치 화면(160x80, ST7789) 그리기 모듈.

채점 결과 글 -> 쪽(page) 목록 -> 160x80 그림.
쪽 나누기 규칙은 실제 기판(ESP32-S3)으로 그대로 옮길 수 있게
화소 단위로만 계산한다.
"""
import glob
import os
import re
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

W, H = 160, 80
ROW_H = 16          # 한 줄 높이(화소)
ROWS = 4            # 머리줄 아래 본문 줄 수
PAD = 3

# 색상(실제 화면은 RGB565 라서 마지막에 깎아 낸다)
BG = (0, 0, 0)
# 화면 색은 흰색과 녹색 두 가지만: 녹색은 정답에만 쓰고 나머지는 모두 흰색
FG = (255, 255, 255)
GREEN = (70, 200, 100)
DIM = FG
HEAD_BG = BG
LINE = FG
RED = FG
YELLOW = FG
GRAY = FG


# ---------------------------------------------------------------- 글꼴
def _find_font(bold=False):
    win = os.environ.get("WINDIR", r"C:\Windows")
    cands = [
        os.path.join(win, "Fonts", "malgunbd.ttf" if bold else "malgun.ttf"),
        os.path.join(win, "Fonts", "malgun.ttf"),
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ]
    cands += glob.glob("/usr/share/fonts/**/NanumGothic*.ttf", recursive=True)
    cands += glob.glob("/usr/share/fonts/**/NotoSansCJK-*.ttc", recursive=True)
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


_FONT_PATH = _find_font()
_BOLD_PATH = _find_font(bold=True) or _FONT_PATH
_cache = {}


def font(size, bold=False):
    key = (size, bold)
    if key not in _cache:
        path = _BOLD_PATH if bold else _FONT_PATH
        if path:
            idx = 1 if path.endswith(".ttc") and "Noto" in path else 0
            try:
                _cache[key] = ImageFont.truetype(path, size, index=idx)
            except OSError:
                _cache[key] = ImageFont.truetype(path, size)
        else:
            _cache[key] = ImageFont.load_default()
    return _cache[key]


def tw(text, f):
    return f.getlength(text)


def wrap(text, f, width):
    """화소 폭 기준 줄바꿈. 띄어쓰기에서 우선 끊고, 안 되면 글자 단위."""
    out = []
    for para in str(text).split("\n"):
        line = ""
        for ch in para:
            if tw(line + ch, f) <= width:
                line += ch
                continue
            cut = line.rfind(" ")
            if cut > len(line) // 2:
                out.append(line[:cut])
                line = line[cut + 1:] + ch
            else:
                out.append(line)
                line = ch.lstrip()
        if line or not out:
            out.append(line)
    return out


def fit(text, f, width):
    if tw(text, f) <= width:
        return text
    while text and tw(text + "…", f) > width:
        text = text[:-1]
    return text + "…"


# ---------------------------------------------------------------- 결과 해석
ITEM_RE = re.compile(
    r"^\s*(\d+)\s*번\s*\|\s*내\s*답\s*[:：]\s*(.*?)\s*\|\s*정답\s*[:：]\s*(.*?)"
    r"\s*(?:\|\s*([OXox○×]))?\s*(?:\|\s*문항\s*[:：]\s*(.*?))?\s*$"
)
UNM_RE = re.compile(
    r"^\s*(\d+)\s*번\s*\|\s*(?:미표기|내\s*답\s*[:：]\s*(?:없음|미표기|-|—|\(없음\))?)"
    r"\s*\|\s*정답\s*[:：]\s*(.*?)\s*(?:\|\s*[OXox○×-])?\s*(?:\|\s*문항\s*[:：]\s*(.*?))?\s*$"
)
FIELD_RE = re.compile(r"\|\s*(식|풀이식|계산식|문항)\s*[:：]\s*([^|]*)")
NOTE_RE = re.compile(r"^\s*해설\s*(\d+)\s*번\s*[:：]\s*(.*)$")
SCORE_RE = re.compile(r"점수\s*[:：]\s*(\d+)\s*/\s*(\d+)")
UNMARK_RE = re.compile(r"미표기\s*(\d+)")


@dataclass
class Item:
    no: str
    mine: str
    answer: str
    ok: bool = False
    note: str = ""
    blank: bool = False   # 내 답 없음(미표기)
    qkey: str = ""        # 문항 첫머리(여러 장 합칠 때 같은 문항인지 가리는 데 씀)
    label: str = ""       # 화면에 쓸 번호(번호가 다시 1번부터 시작하면 「2-1」처럼)
    calc: str = ""        # 계산 문제의 풀이식(해설을 꺼도 정답과 함께 보여 줌)


@dataclass
class Result:
    items: list = field(default_factory=list)
    correct: int = 0
    graded: int = 0
    unmarked: int = 0
    weak: str = ""
    illegible: bool = False
    has_score: bool = False
    who: str = ""
    shot: str = ""


def parse(text):
    r = Result()
    if "판독불가" in text.replace(" ", ""):
        r.illegible = True
        return r
    in_note = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            in_note = False
            continue
        extra = {}
        if "번" in line[:6]:
            for k, v in FIELD_RE.findall(line):
                extra["문항" if k == "문항" else "식"] = v.strip()
            line = FIELD_RE.sub("", line).strip()
        m = UNM_RE.match(line)
        if m:
            r.items.append(Item(m.group(1), "", m.group(2), blank=True,
                                qkey=extra.get("문항", ""), calc=extra.get("식", "")))
            in_note = False
            continue
        m = ITEM_RE.match(line)
        if m:
            mark = (m.group(4) or "X").upper()
            r.items.append(Item(m.group(1), m.group(2), m.group(3),
                                ok=mark in ("O", "○"), qkey=extra.get("문항", ""),
                                calc=extra.get("식", "")))
            in_note = False
            continue
        m = SCORE_RE.search(line)
        if m:
            r.correct, r.graded = int(m.group(1)), int(m.group(2))
            r.has_score = True
            u = UNMARK_RE.search(line)
            r.unmarked = int(u.group(1)) if u else 0
            in_note = False
            continue
        if line.startswith("취약"):
            r.weak = line.split(":", 1)[-1].strip()
            in_note = False
            continue
        m = NOTE_RE.match(line)
        if m:
            it = next((i for i in r.items if i.no == m.group(1)), None)
            if it:
                it.note = m.group(2).strip()
            in_note = False
            continue
        if line.startswith("촬영"):
            r.shot = line.split(":", 1)[-1].strip()
            continue
        if line.startswith("수험번호") or line.startswith("이름"):
            nm = re.search(r"이름\s*[:：]\s*([^|]+)", line)
            if nm and "없음" not in nm.group(1):
                r.who = nm.group(1).strip()
            continue
        if line.startswith("해설") and r.items:
            r.items[-1].note = line.split(":", 1)[-1].strip()
            in_note = True
            continue
        if in_note and r.items:
            r.items[-1].note += " " + line
    r.items.sort(key=lambda i: int(i.no))
    blanks = sum(1 for i in r.items if i.blank)
    if not r.has_score and r.items:
        r.graded = sum(1 for i in r.items if not i.blank)
        r.correct = sum(1 for i in r.items if i.ok)
    r.unmarked = max(r.unmarked, blanks)
    return r


# ---------------------------------------------------------------- 여러 장 합치기
def _key(q):
    return re.sub(r"[^0-9A-Za-z가-힣]", "", q or "")[:8]


def merge(results):
    """한 학생이 여러 장을 찍었을 때 문항을 하나로 정리한다.

    - 같은 번호·같은 문항(겹쳐 찍힘): 하나만 남김. 미표기보다 답이 읽힌 쪽, 같으면 나중 사진.
    - 같은 번호인데 문항이 다름(다음 쪽·다른 과목이 1번부터 다시 시작): 「2-1번」처럼 묶음 번호를 붙임.
    - 점수·미표기 수는 정리된 문항으로 다시 셈.
    """
    out = Result()
    section = 1
    seen = {}            # (묶음, 번호) → Item
    keys = {}            # (묶음, 번호) → 문항 첫머리
    last_no = 0
    for r in results:
        if r.illegible:
            continue
        out.who = out.who or r.who
        if r.weak and r.weak not in out.weak:
            out.weak = (out.weak + ", " + r.weak).strip(", ")
        out.shot = r.shot or out.shot
        for it in r.items:
            n = int(it.no) if it.no.isdigit() else 0
            k = _key(it.qkey)
            cur = (section, n)
            if cur in seen:
                same = (not k or not keys.get(cur) or k == keys[cur])
                if same:                     # 겹쳐 찍힌 같은 문항
                    old = seen[cur]
                    if old.blank and not it.blank or (old.blank == it.blank):
                        it.label = old.label
                        seen[cur] = it
                        keys[cur] = k or keys[cur]
                    continue
                section += 1                 # 번호가 다시 시작됨 → 새 묶음
                cur = (section, n)
            it.label = f"{section}-{n}" if section > 1 else str(n)
            seen[cur] = it
            keys[cur] = k
            last_no = n
    items = sorted(seen.items(), key=lambda kv: kv[0])
    if section > 1:                          # 묶음이 여러 개면 첫 묶음도 「1-」 붙여 통일
        for (sec, n), it in items:
            it.label = f"{sec}-{n}"
    out.items = [it for _, it in items]
    out.correct = sum(1 for i in out.items if i.ok)
    out.graded = sum(1 for i in out.items if not i.blank)
    out.unmarked = sum(1 for i in out.items if i.blank)
    out.has_score = True
    return out


# ---------------------------------------------------------------- 쪽 만들기
BODY_H = H - ROW_H          # 머리줄 아래 본문 높이(64)
LIST_ROWS = 3               # 문항 목록은 한 쪽에 3줄(크게)
LIST_H = BODY_H // LIST_ROWS
NUM_SIZE, ANS_SIZE = 16, 18  # 문항 번호, 답 글자 크기
LABEL_W = 30


def _answer_lines(label, text, col):
    """내 답/정답 한 줄을 가능한 크게. 넘치면 줄여서 여러 줄."""
    room = W - PAD * 2 - LABEL_W
    for size in (22, 18, 15):
        if tw(text, font(size, True)) <= room:
            return [dict(label=label, text=text, col=col, size=size, bold=True,
                         h=max(24, size + 8))]
    out = []
    for k, t in enumerate(wrap(text, font(13, True), room)):
        out.append(dict(label=label if k == 0 else "", text=t, col=col,
                        size=13, bold=True, h=16))
    return out


def wrap_calc(text, f, width):
    """풀이식 줄바꿈: 숫자 중간이 아니라 → = × + 같은 기호나 빈칸 뒤에서 끊는다."""
    toks = [t for t in re.split(r"(?<=[ →=×÷+\-])", text) if t]
    out, cur = [], ""
    for t in toks:
        if tw(cur + t, f) <= width:
            cur += t
            continue
        if cur.strip():
            out.append(cur.strip())
        cur = t
        while tw(cur, f) > width:                # 기호 없이 긴 덩어리는 글자 단위로
            parts = wrap(cur, f, width)
            out.extend(p.strip() for p in parts[:-1])
            cur = parts[-1]
    if cur.strip():
        out.append(cur.strip())
    return out


def _pack(lines, limit=BODY_H):
    pages, cur, used = [], [], 0
    for ln in lines:
        if cur and used + ln["h"] > limit:
            pages.append(cur)
            cur, used = [], 0
        cur.append(ln)
        used += ln["h"]
    if cur:
        pages.append(cur)
    return pages


def build_pages(r, notes=False):
    """쪽 하나 = (종류, 자료) 묶음.

    notes=False(기본): 오답·미표기만, 한 쪽 2줄로 크게. 해설·복습 쪽 없음.
    notes=True       : 모든 문항 3줄씩 + 문항별 해설 + 복습할 부분.
    """
    if r.illegible:
        return [("msg", {"title": "판독 불가", "color": YELLOW,
                         "body": "사진이 흐리거나 기울었습니다. 다시 찍어 주세요."})]
    pages = [("summary", r)]

    if notes:
        per, nsize, sizes = 3, 16, (18, 15)
        items = r.items
    else:
        per, nsize, sizes = 2, 18, (26, 22, 18)
        items = [i for i in r.items if not i.ok]
    row_h = BODY_H // per
    nf = font(nsize, True)
    left_w = max([tw(f"{i.no}번", nf) for i in items] + [0]) + 8
    room = W - PAD * 2 - 4 - left_w

    def detail_pages(it):
        calc = bool(it.calc and not it.ok)
        if calc:
            # 계산 문항: 내 답은 머리줄로 올리고, 본문은 정답(크게) + 풀이식
            lines = _answer_lines("정답", it.answer, GREEN)
            if lines[0]["size"] > 18:
                lines = [dict(lines[0], size=18, h=24)]
            for size, h in ((15, 19), (13, 16), (11, 14)):
                cl = wrap_calc(it.calc, font(size, True), W - PAD * 2 - LABEL_W)
                if sum(l["h"] for l in lines) + h * len(cl) <= BODY_H or size == 11:
                    break
            for k, t in enumerate(cl):
                lines.append(dict(label="식" if k == 0 else "", text=t, col=FG,
                                  size=size, bold=True, h=h))
        else:
            lines = ([] if it.blank else _answer_lines("내 답", it.mine, RED))
            lines += _answer_lines("정답", it.answer, GREEN)
        if notes and it.note:
            for t in wrap(it.note, font(13), W - PAD * 2):
                lines.append(dict(label=None, text=t, col=FG, size=13,
                                  bold=False, h=16))
        chunks = _pack(lines)
        mine = it.mine if calc and not it.blank else ""
        return [("detail", {"item": it, "lines": ch, "part": (n + 1, len(chunks)),
                            "mine": mine})
                for n, ch in enumerate(chunks)]

    # 문항 순서대로: 일반 문항은 목록 쪽(한 쪽 per줄), 계산 문항(틀림·미표기)은
    # 정답과 풀이식을 한 쪽에 크게. 해설이 켜져 있으면 해설 쪽은 목록 뒤에 모음.
    seq, rows, later = [], [], []

    def flush():
        for k in range(0, len(rows), per):
            seq.append(("list", {"rows": rows[k:k + per], "h": row_h, "nsize": nsize}))
        rows.clear()

    for it in items:
        if it.calc and not it.ok:
            flush()
            seq.extend(detail_pages(it))
            continue
        right = (it.answer if it.blank else
                 it.mine if it.ok else f"{it.mine}→{it.answer}")
        size = next((z for z in sizes if tw(right, font(z, True)) <= room), 0)
        if size:
            rows.append((it, right, size))
        elif it.ok:
            rows.append((it, fit(right, font(sizes[-1], True), room), sizes[-1]))
        else:                                # 한 줄에 안 들어가면 그 자리에서 크게 한 쪽
            flush()
            seq.extend(detail_pages(it))
            continue
        if not it.ok and notes and it.note:
            later.append(it)
    flush()

    if not seq:
        pages.append(("msg", {"title": "모두 정답", "color": GREEN,
                              "body": "틀린 문항이 없습니다."}))
    pages.extend(seq)
    for it in later:
        pages.extend(detail_pages(it))

    if r.shot and not r.shot.startswith("좋음"):
        tip = {"멀리서": "더 가까이 찍어 주세요", "기울어짐": "정면 위에서 찍어 주세요",
               "흐림": "흔들리지 않게 다시 찍어 주세요", "어두움": "밝은 곳에서 찍어 주세요",
               "잘림": "시험지 전체가 들어오게 찍어 주세요"}
        key = next((k for k in tip if r.shot.startswith(k)), "")
        pages.append(("msg", {"title": "촬영 " + (key or "확인"), "color": YELLOW,
                              "body": (tip.get(key, "") + " · " + r.shot).strip(" ·")}))

    if notes and r.weak:
        ww = wrap(r.weak, font(13), W - PAD * 2)
        for k in range(0, len(ww), ROWS):
            pages.append(("weak", {"lines": ww[k:k + ROWS]}))
    return pages


# ---------------------------------------------------------------- 그리기
def _head(d, title, color=FG, page=None):
    d.rectangle([0, 0, W - 1, ROW_H - 1], fill=HEAD_BG)
    d.line([0, ROW_H - 1, W - 1, ROW_H - 1], fill=LINE)
    d.text((PAD, ROW_H / 2), title, font=font(12, True), fill=color, anchor="lm")
    if page:
        s = f"{page[0]}/{page[1]}"
        d.text((W - PAD, ROW_H / 2), s, font=font(10), fill=DIM, anchor="rm")


def _row_y(i):
    return ROW_H + i * ROW_H


def draw_summary(d, r, page):
    _head(d, fit(r.who, font(12, True), 110) if r.who else "채점 결과", page=page)
    wrong = r.graded - r.correct
    big = font(36, True)
    s = f"{r.correct}"
    base = 56
    d.text((PAD, base), s, font=big, fill=FG, anchor="ls")
    x = PAD + tw(s, big) + 2
    d.text((x, base), f"/{r.graded}", font=font(16, True), fill=DIM, anchor="ls")
    # 오른쪽 숫자 칸: 이름은 흐리게, 숫자는 굵고 크게
    rx = 100
    for y, label, n, col in ((28, "오답", wrong, RED),
                             (46, "미표기", r.unmarked, YELLOW)):
        d.text((rx, y), label, font=font(11), fill=DIM, anchor="lm")
        d.text((W - PAD, y), str(n), font=font(17, True),
               fill=col if n else DIM, anchor="rm")
    # 막대: 맞음 / 틀림 / 미표기
    total = max(1, r.graded + r.unmarked)
    y0, y1 = 66, 75
    x0, span = PAD, W - PAD * 2
    a = round(span * r.correct / total)
    b = round(span * wrong / total)
    d.rectangle([x0, y0, x0 + span - 1, y1],
                fill=YELLOW if r.unmarked else GRAY)
    if a:
        d.rectangle([x0, y0, x0 + a - 1, y1], fill=GREEN)
    if b:
        d.rectangle([x0 + a, y0, x0 + a + b - 1, y1], fill=RED)


def draw_list(d, data, page):
    _head(d, "다시 볼 문항" if data["nsize"] > 16 else "문항", page=page)
    h = data["h"]
    nf = font(data["nsize"], True)
    for i, (it, right, size) in enumerate(data["rows"]):
        y = ROW_H + i * h
        m = y + h / 2
        col = YELLOW if it.blank else GREEN if it.ok else RED
        d.rectangle([0, y + 4, 2, y + h - 4], fill=col)
        d.text((PAD + 3, m), f"{it.label or it.no}번", font=nf, fill=FG, anchor="lm")
        if not it.blank and not it.ok and "→" in right and right != "자세히 ▶":
            mine, ans = right.split("→", 1)
            af = font(size, True)
            ax = W - PAD - tw(ans, af)
            d.text((W - PAD, m), ans, font=af, fill=GREEN, anchor="rm")
            d.text((ax - 1, m), "→", font=af, fill=DIM, anchor="rm")
            d.text((ax - 1 - tw("→", af), m), mine, font=af, fill=RED,
                   anchor="rm")
        else:   # 미표기는 정답만 보이므로 녹색, 맞은 문항도 녹색
            d.text((W - PAD, m), right, font=font(size, True),
                   fill=GREEN if (it.blank or it.ok) else col, anchor="rm")
        if i < len(data["rows"]) - 1:
            d.line([PAD, y + h - 1, W - PAD, y + h - 1], fill=LINE)


def draw_detail(d, data, page):
    it = data["item"]
    p = data["part"]
    kind = "미표기" if it.blank else "정답" if it.ok else "오답"
    title = f"{it.label or it.no}번 {kind}"
    if p[1] > 1:
        title += f" ({p[0]}/{p[1]})"
    if data.get("mine"):
        title = fit(f"{title} · 내 답 {data['mine']}", font(12, True), W - PAD * 2 - 26)
    _head(d, title, color=YELLOW if it.blank else GREEN if it.ok else RED,
          page=page)
    y = ROW_H
    for ln in data["lines"]:
        m = y + ln["h"] / 2
        f = font(ln["size"], ln["bold"])
        if ln["label"] is None:
            d.text((PAD, m), ln["text"], font=f, fill=ln["col"], anchor="lm")
        else:
            if ln["label"]:
                d.text((PAD, m), ln["label"], font=font(10), fill=DIM,
                       anchor="lm")
            d.text((PAD + LABEL_W, m), ln["text"], font=f, fill=ln["col"],
                   anchor="lm")
        y += ln["h"]


def draw_weak(d, data, page):
    _head(d, "복습할 부분", color=YELLOW, page=page)
    for i, s in enumerate(data["lines"]):
        d.text((PAD, _row_y(i) + ROW_H / 2), s, font=font(13), fill=FG, anchor="lm")


def draw_msg(d, data, page=None, frame=0):
    _head(d, data["title"], color=data.get("color", FG))
    body = data.get("body", "")
    if data.get("spin"):
        dots = "●" * (frame % 4) + "○" * (3 - frame % 4)
        f = font(14)
        d.text((W / 2, 42), dots, font=f, fill=GREEN, anchor="mm")
        if body:
            d.text((W / 2, 68), fit(body, font(10), W - PAD * 2),
                   font=font(10), fill=DIM, anchor="mm")
        return
    for i, s in enumerate(wrap(body, font(12), W - PAD * 2)[:ROWS]):
        d.text((PAD, _row_y(i) + ROW_H / 2), s, font=font(12), fill=FG, anchor="lm")


def to_rgb565(img):
    r, g, b = img.split()
    r = r.point(lambda v: v & 0xF8)
    g = g.point(lambda v: v & 0xFC)
    b = b.point(lambda v: v & 0xF8)
    return Image.merge("RGB", (r, g, b))


def render(page, index=0, total=1, frame=0):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    kind, data = page
    pg = (index + 1, total) if total > 1 else None
    if kind == "summary":
        draw_summary(d, data, pg)
    elif kind == "list":
        draw_list(d, data, pg)
    elif kind == "detail":
        draw_detail(d, data, pg)
    elif kind == "weak":
        draw_weak(d, data, pg)
    else:
        draw_msg(d, data, pg, frame)
    return to_rgb565(img)


def magnify(img, z, grid=True):
    big = img.resize((W * z, H * z), Image.NEAREST)
    if grid and z >= 4:
        d = ImageDraw.Draw(big)
        c = (10, 10, 10)
        for x in range(0, W * z, z):
            d.line([x, 0, x, H * z], fill=c)
        for y in range(0, H * z, z):
            d.line([0, y, W * z, y], fill=c)
    return big


SAMPLE_BRIEF = """3번 | 내 답: ② | 정답: ④
7번 | 내 답: ① | 정답: ③
12번 | 내 답: 1.5 | 정답: 2.5
15번 | 내 답: 광합성 | 정답: 호흡
18번 | 내 답: 세포막이 물질을 걸러 낸다 | 정답: 세포벽이 모양을 유지한다
9번 | 미표기 | 정답: ⑤
20번 | 미표기 | 정답: 엽록체
점수: 15/20 (미표기 2)
"""

SAMPLE_FULL = """1번 | 내 답: ③ | 정답: ③ | O
해설: 산소는 잎의 기공을 통해 밖으로 나갑니다.
2번 | 내 답: ② | 정답: ④ | X
해설: 뿌리털은 흡수 면적을 넓혀 물을 잘 빨아들입니다. 저장 기능은 뿌리 전체의 역할입니다.
3번 | 내 답: 증산 작용 | 정답: 증산 작용 | O
해설: 잎에서 물이 수증기로 빠져나가는 현상입니다.
4번 | 내 답: 12 | 정답: 18 | X
해설: 가로 3, 세로 6 이므로 넓이는 18입니다. 둘레와 혼동했습니다.
5번 | 미표기 | 정답: 36
해설: 한 변이 6인 정사각형이므로 6×6=36입니다.
점수: 2/4 (미표기 1)
취약 부분: 식물의 뿌리 구조와 기능, 넓이와 둘레 구분
"""
