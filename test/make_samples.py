# -*- coding: utf-8 -*-
"""
채점 정확도 시험용 답안지 만들기.

과목별 문제(직접 작성, 각 시험 유형을 본뜸)에 학습자 답을 표시한 답안지 그림을 만들고,
정답표(key.json)를 함께 남긴다. 사진처럼 기울기·그림자·흐림·저해상도를 섞는다.
실행: python3 test/make_samples.py  →  test/samples/
"""
import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parent / "samples"
SANS = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
SERIF = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"
BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
KR = 1  # 글꼴 묶음 안의 한국어 번호

C = "①②③④⑤"

# (번호, 문제, 보기 또는 None(단답), 정답, 허용 답)
SETS = {
    "01_기초수학": ("S-OJT 기초수학 평가", [
        ("3x + 5 = 20 일 때 x 의 값은?", ["3", "4", "5", "6"], 3),
        ("원가 8,000원 제품에 원가의 25% 이익을 붙인 판매가는?", ["9,000원", "10,000원", "10,500원", "12,000원"], 2),
        ("가로 12m, 세로 7.5m 인 직사각형의 넓이(㎡)는?", None, "90"),
        ("1부터 10까지 자연수의 합은?", None, "55"),
        ("정가 50,000원에서 20% 할인한 뒤 다시 10% 할인한 가격은?", ["35,000원", "36,000원", "40,000원", "45,000원"], 2),
        ("2의 5제곱은?", ["10", "16", "25", "32"], 4),
    ]),
    "02_세무": ("세무 기초 (세무사 1차 유형)", [
        ("우리나라 부가가치세 일반 세율은?", ["5%", "10%", "12%", "15%"], 2),
        ("공급가액이 3,000,000원일 때 부가가치세액(원)은?", None, "300000"),
        ("일반과세자의 부가가치세 제1기 과세기간은?", ["1.1.~3.31.", "1.1.~6.30.", "1.1.~12.31.", "7.1.~12.31."], 2),
        ("다음 중 부가가치세 면세 대상은?", ["가공되지 않은 쌀", "휴대전화", "승용차", "가전제품"], 1),
        ("거주자 종합소득세의 과세기간은?", ["1.1.~12.31.", "3.1.~다음 해 2.28.", "4.1.~다음 해 3.31.", "7.1.~다음 해 6.30."], 1),
        ("법인세 신고기한은 사업연도 종료일이 속하는 달의 말일부터 몇 개월 이내인가?", ["1개월", "2개월", "3개월", "6개월"], 3),
    ]),
    "03_회계": ("회계원리 (회계사·전산회계 유형)", [
        ("회계등식: 자산 = 부채 + ( )", ["수익", "비용", "자본", "이익잉여금"], 3),
        ("취득원가 10,000,000원, 잔존가치 0원, 내용연수 5년인 기계의 정액법 연간 감가상각비(원)는?", None, "2000000"),
        ("외상매출금의 분류는?", ["유동자산", "비유동자산", "유동부채", "자본"], 1),
        ("매출액 5,000,000원, 매출원가 3,000,000원일 때 매출총이익(원)은?", None, "2000000"),
        ("다음 중 차변에 기록하는 것은?", ["부채의 증가", "자본의 증가", "자산의 증가", "수익의 발생"], 3),
        ("먼저 매입한 재고를 먼저 출고한 것으로 보는 단가 결정 방법은?", ["후입선출법", "선입선출법", "이동평균법", "총평균법"], 2),
    ]),
    "04_SCM물류": ("물류·공급망관리 (물류관리사 유형)", [
        ("공급자가 고객의 재고를 직접 관리하고 보충하는 방식은?", ["JIT", "VMI", "EOQ", "ABC"], 2),
        ("연간수요 2,000개, 1회 주문비 50원, 단위당 연간 보관비 2원일 때 경제적 주문량(개, 소수점 버림)은?", None, "316"),
        ("공급망 상류로 갈수록 수요 변동이 커지는 현상은?", ["채찍효과", "규모의 경제", "파레토 법칙", "롱테일"], 1),
        ("20피트 컨테이너 1개를 나타내는 단위는?", ["TEU", "FEU", "CBM", "RT"], 1),
        ("ABC 재고관리에서 A그룹의 일반적인 특징은?", ["품목 수가 많고 금액이 작다", "품목 수가 적고 금액이 크다", "품목 수와 금액이 모두 크다", "관리가 필요 없다"], 2),
        ("하루 평균 판매 40개, 조달기간 5일, 안전재고 50개일 때 재주문점(개)은?", None, "250"),
    ]),
    "05_부동산": ("부동산학 (공인중개사 유형)", [
        ("공인중개사법상 중개대상물이 아닌 것은?", ["토지", "건축물", "입목", "금전채권"], 4),
        ("1평은 약 몇 ㎡ 인가?", ["1.65", "3.3058", "10", "33"], 2),
        ("전용면적 84㎡는 약 몇 평인가? (소수 첫째 자리까지)", None, "25.4"),
        ("주택임대차보호법상 대항력의 요건은?", ["계약서 작성", "주택의 인도와 주민등록", "확정일자", "차임 지급"], 2),
        ("건폐율의 정의로 옳은 것은?", ["대지면적에 대한 건축면적의 비율", "대지면적에 대한 연면적의 비율", "연면적에 대한 건축면적의 비율", "건축면적에 대한 대지면적의 비율"], 1),
        ("대지 200㎡, 연면적 500㎡일 때 용적률(%)은?", None, "250"),
    ]),
    "06_관세": ("관세법 (관세사 유형)", [
        ("수입물품 과세가격 결정의 원칙적 방법은?", ["해당 물품의 거래가격", "동종물품의 거래가격", "국내판매가격 기초", "산정가격"], 1),
        ("과세가격 1,000,000원, 관세율 8%일 때 관세액(원)은?", None, "80000"),
        ("품목분류(HS) 코드의 국제 공통 자리수는?", ["4자리", "6자리", "8자리", "10자리"], 2),
        ("다음 중 보세구역이 아닌 것은?", ["지정장치장", "보세창고", "보세공장", "일반창고"], 4),
        ("관세의 납세의무자는 원칙적으로 누구인가?", ["수입화주", "수출자", "운송인", "세관장"], 1),
        ("수입물품에 관세를 부과하는 기준이 되는 것은?", ["수입신고 당시의 성질과 수량", "선적 당시 가격", "도착 후 1년 평균가", "판매 당시 가격"], 1),
    ]),
    "07_건축": ("건축시공 (산업기사 유형)", [
        ("콘크리트 압축강도 시험의 표준 재령은?", ["7일", "14일", "28일", "90일"], 3),
        ("철근콘크리트에서 철근이 주로 부담하는 힘은?", ["압축력", "인장력", "전단력만", "비틀림만"], 2),
        ("축척 1:100 도면에서 50mm는 실제 몇 m 인가?", None, "5"),
        ("표준형 벽돌의 규격(mm)은?", ["190×90×57", "210×100×60", "200×100×50", "230×110×65"], 1),
        ("시멘트 분말도가 클수록 나타나는 현상은?", ["초기강도가 커진다", "수화열이 작아진다", "응결이 느려진다", "강도 발현이 늦다"], 1),
        ("4m×5m 바닥에 300×300mm 타일을 붙일 때 필요한 장수(할증 없이, 올림)는?", None, "223", ["222"]),
    ]),
}

# 사진 상태(어려움 정도): 깨끗한 스캔 → 휴대폰 사진
STYLES = {
    "01_기초수학": dict(rot=0.0, shadow=0.0, blur=0.0, scale=1.0, name="깨끗한 스캔"),
    "02_세무": dict(rot=1.5, shadow=0.25, blur=0.6, scale=0.9, name="약간 기운 사진"),
    "03_회계": dict(rot=-2.5, shadow=0.35, blur=0.8, scale=0.8, name="그림자 진 사진"),
    "04_SCM물류": dict(rot=3.5, shadow=0.2, blur=1.0, scale=0.7, name="기울고 흐린 사진"),
    "05_부동산": dict(rot=-1.0, shadow=0.45, blur=0.5, scale=0.6, name="어둡고 작은 사진"),
    "06_관세": dict(rot=0.8, shadow=0.15, blur=1.4, scale=0.75, name="많이 흐린 사진"),
    "07_건축": dict(rot=-4.0, shadow=0.3, blur=0.7, scale=0.85, name="많이 기운 사진"),
}

STUDENTS = ["김민수", "이서연", "박지훈", "최유진", "정하늘", "강도윤", "윤서아"]


def f(path, size):
    return ImageFont.truetype(path, size, index=KR)


def wrap(d, text, font, width):
    lines, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=font) > width:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def hand(img, xy, text, size, color=(25, 55, 170)):
    """손글씨 흉내: 글자마다 조금씩 기울이고 위아래로 흔든다."""
    x, y = xy
    rnd = random.Random(text + str(xy))
    for ch in text:
        g = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
        gd = ImageDraw.Draw(g)
        gd.text((size // 2, size // 3), ch, font=f(SERIF, size), fill=color + (255,))
        g = g.rotate(rnd.uniform(-9, 9), resample=Image.BICUBIC)
        img.paste(g, (int(x - size // 2), int(y + rnd.uniform(-4, 4) - size // 3)), g)
        x += f(SERIF, size).getlength(ch) * rnd.uniform(0.95, 1.12)
    return x


def make_sheet(key, title, qs, seed):
    rnd = random.Random(seed)
    W, H = 1240, 1754
    img = Image.new("RGB", (W, H), (252, 252, 248))
    d = ImageDraw.Draw(img)
    d.text((80, 70), title, font=f(BOLD, 40), fill=(20, 20, 20))
    exam_no = f"2026-{seed:04d}"
    name = STUDENTS[(seed // 7) % len(STUDENTS)]
    d.text((80, 140), "수험번호", font=f(SANS, 24), fill=(60, 60, 60))
    d.text((620, 140), "성명", font=f(SANS, 24), fill=(60, 60, 60))
    d.line([(190, 172), (560, 172)], fill=(120, 120, 120), width=1)
    d.line([(690, 172), (1000, 172)], fill=(120, 120, 120), width=1)
    hand(img, (210, 128), exam_no, 30)
    hand(img, (710, 128), name, 32)
    d.line([(80, 200), (W - 80, 200)], fill=(40, 40, 40), width=2)

    y = 240
    items = []
    # 학습자 답 정하기: 맞음 60%, 틀림 25%, 미표기 15% (과목마다 최소 1개씩 섞음)
    plan = ["O", "O", "O", "X", "X", "-"]
    rnd.shuffle(plan)
    for i, q in enumerate(qs, 1):
        text, choices, ans = q[0], q[1], q[2]
        alts = q[3] if len(q) > 3 else []
        mark = plan[i - 1]
        for k, line in enumerate(wrap(d, f"{i}. {text}", f(SANS, 27), W - 200)):
            d.text((80 if k == 0 else 112, y), line, font=f(SANS, 27), fill=(25, 25, 25))
            y += 40
        y += 6
        if choices:
            correct = C[ans - 1]
            if mark == "O":
                mine = correct
            elif mark == "X":
                mine = C[rnd.choice([n for n in range(len(choices)) if n != ans - 1])]
            else:
                mine = ""
            x = 112
            pos = {}
            for n, ch in enumerate(choices):
                label = f"{C[n]} {ch}"
                w = d.textlength(label, font=f(SANS, 25))
                if x + w > W - 100:
                    x = 112
                    y += 42
                pos[C[n]] = (x, y)
                d.text((x, y), label, font=f(SANS, 25), fill=(35, 35, 35))
                x += w + 46
            if mine:
                cx, cy = pos[mine]
                d.ellipse([cx - 9, cy - 4, cx + 33, cy + 38], outline=(200, 30, 40), width=4)
            y += 58
            items.append(dict(no=i, mark=mark, mine=mine, answer=correct, alts=[]))
        else:
            d.text((112, y), "답 :", font=f(SANS, 25), fill=(35, 35, 35))
            d.line([(170, y + 36), (520, y + 36)], fill=(120, 120, 120), width=1)
            if mark == "O":
                mine = ans
            elif mark == "X":
                v = float(ans)
                mine = str(int(v * rnd.choice([0.5, 1.2, 2, 10])) if v >= 10 else round(v + 1.5, 1))
            else:
                mine = ""
            if mine:
                shown = f"{int(mine):,}" if mine.isdigit() and len(mine) > 3 else mine
                hand(img, (190, y - 6), shown, 34)
            y += 66
            items.append(dict(no=i, mark=mark, mine=mine, answer=ans, alts=alts))
        y += 14
    return img, dict(exam_no=exam_no, name=name, items=items)


def photo(img, st, seed):
    rnd = random.Random(seed)
    W, H = img.size
    # 그림자: 한쪽 모서리부터 어두워지게
    if st["shadow"]:
        mask = Image.linear_gradient("L").resize((W, H))
        mask = mask.rotate(rnd.choice([0, 90, 180, 270]), expand=False).resize((W, H))
        dark = Image.new("RGB", (W, H), (60, 55, 50))
        img = Image.composite(dark, img, mask.point(lambda v: int(v * st["shadow"])))
    if st["rot"]:
        img = img.rotate(st["rot"], resample=Image.BICUBIC, expand=True, fillcolor=(120, 110, 100))
    if st["blur"]:
        img = img.filter(ImageFilter.GaussianBlur(st["blur"]))
    if st["scale"] != 1.0:
        img = img.resize((int(img.width * st["scale"]), int(img.height * st["scale"])), Image.LANCZOS)
    return img


def _coeffs(dst, src):
    """원근 변환 계수(대각선에서 찍은 것처럼)."""
    import numpy as np
    A, B = [], []
    for (x, y), (u, v) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); B.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); B.append(v)
    return list(np.linalg.solve(np.array(A, float), np.array(B, float)))


def scene(img, kind, seed):
    """책상 위 종이를 여러 거리·각도에서 찍은 사진 흉내."""
    rnd = random.Random(seed)
    W, H = img.size
    if kind == "대각선":          # 옆에서 비스듬히: 사다리꼴
        BW, BH = 1600, 1500
        dst = [(260, 160), (1380, 260), (1500, 1420), (120, 1330)]
    elif kind == "멀리서":        # 멀리서: 종이가 작고 주변 물건이 많이 보임
        BW, BH = 2000, 2000
        dst = [(700, 620), (1300, 640), (1290, 1480), (690, 1460)]
    elif kind == "가까이":        # 가까이: 종이가 화면을 넘침(가장자리 잘림 없이 크게)
        BW, BH = 1300, 1700
        dst = [(-20, -30), (1320, -10), (1310, 1740), (-30, 1720)]
    else:                          # 위에서 비틀어: 회전된 사다리꼴
        BW, BH = 1700, 1800
        dst = [(380, 120), (1520, 360), (1300, 1720), (150, 1460)]
    src = [(0, 0), (W, 0), (W, H), (0, H)]
    bg = Image.new("RGB", (BW, BH), (96, 78, 60))   # 나무 책상 색
    bd = ImageDraw.Draw(bg)
    for _ in range(40):                              # 책상 결·잡동사니
        x, y = rnd.randrange(BW), rnd.randrange(BH)
        bd.line([(x, y), (x + rnd.randrange(-300, 300), y + rnd.randrange(-20, 20))],
                fill=(110 + rnd.randrange(30), 90, 70), width=rnd.randrange(2, 6))
    bd.rectangle([60, BH - 260, 420, BH - 60], fill=(200, 200, 205))      # 계산기
    bd.ellipse([BW - 360, 80, BW - 80, 360], fill=(230, 230, 225))       # 컵
    paper = img.transform((BW, BH), Image.PERSPECTIVE, _coeffs(dst, src), Image.BICUBIC,
                          fillcolor=None)
    mask = Image.new("L", (W, H), 255).transform((BW, BH), Image.PERSPECTIVE,
                                                  _coeffs(dst, src), Image.BICUBIC)
    bg.paste(paper, (0, 0), mask)
    # 조명 얼룩 + 약한 흐림
    light = Image.radial_gradient("L").resize((BW, BH)).point(lambda v: int(v * 0.35))
    bg = Image.composite(Image.new("RGB", (BW, BH), (40, 35, 30)), bg, light)
    return bg.filter(ImageFilter.GaussianBlur(0.8))


SCENES = {
    "11_대각선_회계.jpg": ("03_회계", "대각선"),
    "12_멀리서_관세.jpg": ("06_관세", "멀리서"),
    "13_가까이_수학.jpg": ("01_기초수학", "가까이"),
    "14_비틀어_부동산.jpg": ("05_부동산", "비틀어"),
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    keys = {}
    pages = []
    clean = {}
    for n, (key, (title, qs)) in enumerate(SETS.items(), 1):
        img, k = make_sheet(key, title, qs, n * 7)
        st = STYLES[key]
        out = photo(img, st, n)
        fn = f"{key}.jpg"
        out.save(OUT / fn, quality=82)
        k.update(title=title, condition=st["name"], file=fn)
        keys[fn] = k
        if key in ("02_세무", "03_회계"):
            pages.append(img)
        clean[key] = (img, k)
    # 피디에프 형식 시험: 세무·회계 두 쪽을 한 파일로(깨끗한 문서)
    pdf = "08_피디에프_세무회계.pdf"
    pages[0].save(OUT / pdf, save_all=True, append_images=pages[1:], resolution=150)
    keys[pdf] = dict(title="피디에프 두 쪽(세무+회계)", condition="문서 파일",
                     file=pdf, items=keys["02_세무.jpg"]["items"],
                     items_page2=keys["03_회계.jpg"]["items"],
                     exam_no=keys["02_세무.jpg"]["exam_no"], name=keys["02_세무.jpg"]["name"])
    for fn, (src_key, kind) in SCENES.items():
        img, k = clean[src_key]
        scene(img, kind, len(fn)).save(OUT / fn, quality=80)
        keys[fn] = dict(k, file=fn, condition=f"{kind}에서 찍은 사진(책상 배경)")
    (OUT / "key.json").write_text(json.dumps(keys, ensure_ascii=False, indent=1), encoding="utf-8")
    print("만든 답안지:", len(keys))


if __name__ == "__main__":
    main()
