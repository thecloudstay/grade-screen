# -*- coding: utf-8 -*-
"""
ESP32-S3 0.96인치(160x80) 채점 화면 시뮬레이터.
두 번 눌러 실행(명령창 없이 뜸).

- 사진 채점 : 사진을 골라 grade.py 로 채점 -> 화면에 표시
- 해설 보기 : 기본은 꺼짐(오답·미표기만 크게). 켜면 모든 문항 + 해설
- 결과 열기 : grade_results 폴더의 결과 글 파일 표시
- 새 결과 자동 표시 : 명령창에서 grade.py 를 돌려도 바로 화면에 뜸
- 택트 스위치 : ◀ 짧게 이전·길게 첫 쪽 / ▶ 짧게 다음·길게 해설 켜기·끄기
- 모듈 : USB 로 꽂으면 자동 인식, 같은 화면을 모듈에 보내고 모듈 스위치로 넘김
- 화면 왼쪽/오른쪽 누르기, ◀ ▶ 단추, 자판 ← →, 마우스 휠 로도 넘김
"""
import os
import queue
import re
import subprocess
import sys
import threading
import time
import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
RESULT_DIR = Path.home() / "grade_results"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
PORT = 8765
PHONE_DIR = RESULT_DIR / "phone_inbox"
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


SETUP_SH = r"""#!/data/data/com.termux/files/usr/bin/bash
# 휴대폰 Download/exp_inbox 에 사진이 저장되면 PC 시뮬레이터로 보내는 감시기 설치
echo "__SERVER__" > ~/.exp_server
if [ ! -d ~/storage/downloads ]; then
  echo "[1/3] 저장공간 권한 창이 뜨면 '허용'을 눌러 주세요"
  termux-setup-storage
  for i in $(seq 1 60); do [ -d ~/storage/downloads ] && break; sleep 1; done
fi
[ -d ~/storage/downloads ] || { echo "저장공간 권한이 없습니다. termux-setup-storage 후 다시 실행"; exit 1; }
mkdir -p ~/storage/downloads/exp_inbox
echo "[2/3] 감시기 설치"
cat > ~/exp_watch.sh <<'WATCH'
#!/data/data/com.termux/files/usr/bin/bash
INBOX=~/storage/downloads/exp_inbox
SENT=~/.exp_sent
touch "$SENT"
termux-wake-lock 2>/dev/null
shopt -s nullglob nocaseglob
while true; do
  SERVER="$(cat ~/.exp_server)"
  for f in "$INBOX"/*.jpg "$INBOX"/*.jpeg "$INBOX"/*.png "$INBOX"/*.webp; do
    name="$(basename "$f")"
    s1=$(stat -c %s "$f")
    key="$name|$s1"
    grep -qxF "$key" "$SENT" && continue
    sleep 1
    s2=$(stat -c %s "$f")
    [ "$s1" = "$s2" ] || continue
    if curl -sf -m 120 --data-binary @"$f"         -H "Content-Type: application/octet-stream"         -H "X-Name: $name" "$SERVER/upload" >/dev/null; then
      echo "$key" >> "$SENT"
      echo "$(date '+%H:%M:%S') 보냄 $name"
    fi
  done
  sleep 2
done
WATCH
chmod +x ~/exp_watch.sh
grep -q exp_watch ~/.bashrc 2>/dev/null || cat >> ~/.bashrc <<'RC'
pgrep -f exp_watch.sh >/dev/null || (nohup bash ~/exp_watch.sh >> ~/exp_watch.log 2>&1 &)
RC
mkdir -p ~/.termux/boot
printf '#!/data/data/com.termux/files/usr/bin/bash
nohup bash ~/exp_watch.sh >> ~/exp_watch.log 2>&1 &
' > ~/.termux/boot/exp_watch
chmod +x ~/.termux/boot/exp_watch
pkill -f exp_watch.sh 2>/dev/null
nohup bash ~/exp_watch.sh >> ~/exp_watch.log 2>&1 &
sleep 1
echo "[3/3] 완료. 감시 중: Download/exp_inbox -> __SERVER__"
curl -sf -m 5 "__SERVER__/ping" >/dev/null && echo "PC 연결 확인됨" || echo "PC 연결 실패: 같은 와이파이인지, PC 방화벽 허용했는지 확인"
"""


def ensure(mod, pkg):
    """꾸러미가 없으면 창 없이 설치."""
    try:
        __import__(mod)
        return True
    except ImportError:
        pass
    py = re.sub(r"pythonw(\.exe)?$", r"python\1", sys.executable, flags=re.I)
    try:
        subprocess.run([py, "-m", "pip", "install", "--user", pkg],
                       creationflags=NO_WINDOW, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=300)
        import importlib
        import site
        importlib.invalidate_caches()
        try:
            sys.path.append(site.getusersitepackages())
        except Exception:
            pass
        __import__(mod)
        return True
    except Exception:
        return False


def ensure_pillow():
    return ensure("PIL", "Pillow")


import tkinter as tk
from tkinter import filedialog, messagebox

if not ensure_pillow():
    r = tk.Tk(); r.withdraw()
    messagebox.showerror("시뮬레이터", "그림 처리 꾸러미(Pillow)를 설치하지 못했습니다.\n"
                         "명령창에서  pip install Pillow  를 한 번 실행해 주세요.")
    sys.exit(1)

from PIL import ImageTk  # noqa: E402
import screen as S  # noqa: E402

UI_FONT = ("맑은 고딕", 10)
PCB = "#15171a"
PCB_EDGE = "#2a2d31"


def korean_error(exc):
    msg = str(exc)
    table = [
        ("ANTHROPIC_API_KEY", "인증 열쇠(ANTHROPIC_API_KEY)가 설정되지 않았습니다."),
        ("401", "인증 열쇠가 맞지 않습니다."),
        ("429", "요청이 많아 잠시 막혔습니다. 조금 뒤 다시 하세요."),
        ("timed out", "응답 시간이 초과되었습니다."),
        ("urlopen", "인터넷 연결을 확인해 주세요."),
        ("unsupported image", "jpg, png, webp 사진만 됩니다."),
        ("Pillow", "사진이 너무 큽니다."),
    ]
    for key, ko in table:
        if key in msg:
            return ko
    return msg[:80]


class App:
    def __init__(self, root):
        self.root = root
        root.title("채점 화면 시뮬레이터 — ESP32-S3 0.96인치 160×80")
        root.configure(bg="#0e0f10")
        self.zoom = tk.IntVar(value=5)
        self.full = tk.BooleanVar(value=False)
        self.watch = tk.BooleanVar(value=True)
        self.grid = tk.BooleanVar(value=True)
        self.pages = [("msg", {"title": "대기 중",
                               "body": "사진 채점 또는 결과 열기를 눌러 주세요."})]
        self.idx = 0
        self.frame = 0
        self.busy = False
        self.ver = 0
        self.text = ""
        self._web_cache = {}
        self.q = queue.Queue()
        self.press_t = 0
        self.last_seen = self._newest_mtime()
        self.jobs = queue.Queue()
        self.ip = lan_ip()
        self.phone_state = "휴대폰 대기 준비 중"
        self._start_server()
        threading.Thread(target=self._worker, daemon=True).start()
        self.usb_state = ""
        self.mod_state = "모듈 없음"
        self.ser = None
        self.ser_lock = threading.Lock()
        threading.Thread(target=self._module_watch, daemon=True).start()
        if os.name == "nt":
            threading.Thread(target=self._usb_watch, daemon=True).start()
        self._build()
        self._load_newest(initial=True)
        self._tick()

    # ------------------------------------------------------------ 화면 구성
    def _build(self):
        bar = tk.Frame(self.root, bg="#0e0f10")
        bar.pack(fill="x", padx=12, pady=(10, 4))
        def btn(text, cmd):
            b = tk.Button(bar, text=text, command=cmd, font=UI_FONT, bd=0,
                          bg="#24272b", fg="#e8e8e8", activebackground="#33373c",
                          activeforeground="#ffffff", padx=12, pady=4)
            b.pack(side="left", padx=(0, 6))
            return b
        btn("◀ 이전", lambda: self.step(-1))
        btn("다음 ▶", lambda: self.step(1))
        btn("사진 채점", self.pick_photo)
        btn("결과 열기", self.open_result)
        btn("예시", self.sample)
        def chk(text, var, cmd=None):
            tk.Checkbutton(bar, text=text, variable=var, command=cmd or self.redraw,
                           font=UI_FONT, bg="#0e0f10", fg="#c8c8c8",
                           selectcolor="#24272b", activebackground="#0e0f10",
                           activeforeground="#ffffff").pack(side="left", padx=4)
        chk("해설 보기", self.full, self.toggle_notes)
        chk("새 결과 자동 표시", self.watch, lambda: None)
        chk("화소 격자", self.grid)
        tk.Label(bar, text="확대", font=UI_FONT, bg="#0e0f10",
                 fg="#c8c8c8").pack(side="left", padx=(10, 2))
        tk.Spinbox(bar, from_=2, to=8, width=3, textvariable=self.zoom,
                   command=self.relayout, font=UI_FONT).pack(side="left")

        self.cv = tk.Canvas(self.root, bg="#0e0f10", highlightthickness=0)
        self.cv.pack(padx=12, pady=6)
        self.status = tk.Label(self.root, text="", font=UI_FONT, anchor="w",
                               bg="#0e0f10", fg="#8a8f88")
        self.status.pack(fill="x", padx=14, pady=(0, 10))

        r = self.root
        r.bind("<Right>", lambda e: self.step(1))
        r.bind("<space>", lambda e: self.step(1))
        r.bind("<Left>", lambda e: self.step(-1))
        r.bind("<Home>", lambda e: self.go(0))
        r.bind("<Prior>", lambda e: self.step(-1))
        r.bind("<Next>", lambda e: self.step(1))
        r.bind("<MouseWheel>", lambda e: self.step(-1 if e.delta > 0 else 1))
        self.relayout()

    def relayout(self):
        z = max(2, min(8, int(self.zoom.get() or 5)))
        sw, sh = S.W * z, S.H * z
        m = 6 * z                         # 기판 여백
        usb_w, usb_h = 14 * z, 18 * z     # 타입C 단자
        cw = m + sw + m + 22 * z + usb_w
        ch = m + sh + m
        sw_area = 26 * z                  # 아래 택트 스위치 줄
        self.cv.config(width=cw + 20, height=ch + sw_area + 20)
        self.cv.delete("all")
        ox, oy = 10, 10
        self.screen_xy = (ox + m, oy + m)
        # 기판
        self._round(ox, oy, ox + cw - usb_w + 2 * z, oy + ch, 3 * z,
                    fill=PCB, outline=PCB_EDGE)
        # 화면 테두리(유리)
        self._round(ox + m - 2 * z, oy + m - 2 * z, ox + m + sw + 2 * z,
                    oy + m + sh + 2 * z, 2 * z, fill="#050505", outline="#33363a")
        # 타입C 단자
        ux = ox + cw - usb_w
        uy = oy + (ch - usb_h) / 2
        self._round(ux, uy, ux + usb_w, uy + usb_h, 3 * z,
                    fill="#9aa0a6", outline="#c4c8cc")
        self._round(ux + 3 * z, uy + 5 * z, ux + usb_w, uy + usb_h - 5 * z,
                    2 * z, fill="#3b3f44", outline="")
        # 택트 스위치 2개(소형 6×6). 화면 아래 좌우에 배치
        by = oy + ch + 11 * z
        r = 5 * z
        hint_f = ("맑은 고딕", max(8, z + 3))
        for key, bx, hint in (("prev", ox + m + sw * 0.25, "◀  짧게 이전 · 길게 처음"),
                              ("next", ox + m + sw * 0.75, "▶  짧게 다음 · 길게 해설")):
            tag = "sw_" + key
            self.cv.create_rectangle(bx - r - z, by - r - z, bx + r + z, by + r + z,
                                     fill="#c9ccd0", outline="#7c8086", tags=tag)
            for cx, cy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                self.cv.create_oval(bx + cx * (r - z / 2) - z / 2,
                                    by + cy * (r - z / 2) - z / 2,
                                    bx + cx * (r - z / 2) + z / 2,
                                    by + cy * (r - z / 2) + z / 2,
                                    fill="#8d9197", outline="", tags=tag)
            self.cv.create_oval(bx - r + 2 * z, by - r + 2 * z, bx + r - 2 * z,
                                by + r - 2 * z, fill="#202225", outline="#0b0b0c",
                                tags=(tag, "cap_" + key))
            self.cv.create_text(bx, by + r + 5 * z, text=hint, fill="#8a8f88",
                                font=hint_f)
            self.cv.tag_bind(tag, "<ButtonPress-1>",
                             lambda e, k=key: self._press(k))
            self.cv.tag_bind(tag, "<ButtonRelease-1>",
                             lambda e, k=key: self._release(k))
        self.img_id = self.cv.create_image(*self.screen_xy, anchor="nw")
        # 화면 왼쪽 절반 누르면 이전, 오른쪽 절반 누르면 다음
        sx = self.screen_xy[0]
        self.cv.tag_bind(self.img_id, "<Button-1>",
                         lambda e: self.step(-1 if e.x < sx + sw / 2 else 1))

        # 실제 크기 대비 배율(화면 유효 면적 가로 21.7mm)
        try:
            dpi = self.root.winfo_fpixels("1i")
            self.ratio = sw / (21.7 / 25.4 * dpi)
        except Exception:
            self.ratio = 0
        self.redraw()

    def _round(self, x0, y0, x1, y1, r, **kw):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
               x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return self.cv.create_polygon(pts, smooth=True, **kw)

    # ------------------------------------------------------------ 그리기
    def redraw(self):
        z = max(2, min(8, int(self.zoom.get() or 5)))
        page = self.pages[self.idx]
        img = S.render(page, self.idx, len(self.pages), self.frame)
        self._send_frame(img)
        self.tk_img = ImageTk.PhotoImage(S.magnify(img, z, self.grid.get()))
        self.cv.itemconfig(self.img_id, image=self.tk_img)
        info = f"{self.idx + 1} / {len(self.pages)} 쪽"
        if self.ratio:
            info += f"   ·   실제 화면의 약 {self.ratio:.1f}배 크기"
        if getattr(self, "src", ""):
            info += f"   ·   {self.src}"
        info += f"   ·   {self.mod_state}"
        if self.usb_state:
            info += f"   ·   {self.usb_state}"
        self.status.config(text=info)

    def step(self, d):
        if self.busy:
            return
        self.idx = (self.idx + d) % len(self.pages)
        self.redraw()

    def go(self, i):
        if self.busy:
            return
        self.idx = i
        self.redraw()

    def _press(self, key):
        self.press_t = time.time()
        self.cv.itemconfig("cap_" + key, fill="#4a4d52")

    def _release(self, key):
        # 택트 스위치 2개 규칙(모듈과 동일)
        #  ◀ 짧게 = 이전 / 길게(0.8초) = 첫 쪽(점수)
        #  ▶ 짧게 = 다음 / 길게(0.8초) = 해설 켜기·끄기
        self.cv.itemconfig("cap_" + key, fill="#202225")
        long_ = time.time() - self.press_t >= 0.8
        self.button(key, long_)

    def button(self, key, long_=False):
        if key == "prev":
            self.go(0) if long_ else self.step(-1)
        elif long_:
            self.full.set(not self.full.get())
            self.toggle_notes()
        else:
            self.step(1)

    # ------------------------------------------------------------ 결과 표시
    def show_text(self, text, src=""):
        self.busy = False
        self.ver += 1
        self.text = text
        self.pages = S.build_pages(S.parse(text), self.full.get())
        self.idx = 0
        self.src = src
        self.redraw()

    def toggle_notes(self):
        """해설 켜고 끄기: 다시 채점하지 않고 화면만 다시 짠다."""
        if self.busy or not getattr(self, "text", ""):
            return
        self.pages = S.build_pages(S.parse(self.text), self.full.get())
        self.idx = min(self.idx, len(self.pages) - 1)
        self.redraw()

    def show_msg(self, title, body="", color=S.FG, spin=False):
        self.ver += 1
        self.text = ""
        self.pages = [("msg", {"title": title, "body": body,
                               "color": color, "spin": spin})]
        self.idx = 0
        self.redraw()

    def sample(self):
        self._sample_flip = not getattr(self, "_sample_flip", False)
        text = S.SAMPLE_FULL if self._sample_flip else S.SAMPLE_BRIEF
        self.show_text(text, "예시 " + ("(해설 포함)" if self._sample_flip else "(짧게)"))

    def open_result(self):
        RESULT_DIR.mkdir(parents=True, exist_ok=True)
        p = filedialog.askopenfilename(initialdir=str(RESULT_DIR),
                                       title="채점 결과 파일 열기",
                                       filetypes=[("글 파일", "*.txt"), ("모든 파일", "*.*")])
        if p:
            self.show_text(Path(p).read_text(encoding="utf-8"), Path(p).name)

    def pick_photo(self):
        if self.busy:
            return
        p = filedialog.askopenfilename(
            title="채점할 사진 고르기",
            filetypes=[("사진", "*.jpg *.jpeg *.png *.webp"), ("모든 파일", "*.*")])
        if not p:
            return
        self.jobs.put(Path(p))

    def _worker(self):
        while True:
            path = self.jobs.get()
            self.q.put(("start", path.name, None))
            try:
                import grade as G
                text = G.grade(path, True)
                RESULT_DIR.mkdir(parents=True, exist_ok=True)
                out = RESULT_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}_{path.stem}.txt"
                out.write_text(text + "\n", encoding="utf-8")
                self.q.put(("ok", text, out))
            except Exception as exc:
                self.q.put(("err", korean_error(exc), None))

    # ------------------------------------------------------------ 휴대폰 수신
    def _start_server(self):
        app = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="text/plain; charset=utf-8"):
                data = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    self._send(200, (HERE / "phone.html").read_text(encoding="utf-8"),
                               "text/html; charset=utf-8")
                elif self.path.startswith("/state"):
                    self._send(200, json.dumps(app.web_state()),
                               "application/json")
                elif self.path.startswith("/page"):
                    from urllib.parse import urlparse, parse_qs
                    q = parse_qs(urlparse(self.path).query)
                    png = app.web_page(int(q.get("i", ["0"])[0]),
                                       q.get("n", ["0"])[0] == "1",
                                       int(q.get("f", ["0"])[0]))
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(png)))
                    self.end_headers()
                    self.wfile.write(png)
                elif self.path.startswith("/setup"):
                    self._send(200, SETUP_SH.replace(
                        "__SERVER__", f"http://{app.ip}:{PORT}"))
                elif self.path.startswith("/ping"):
                    self._send(200, "ok")
                else:
                    self._send(404, "no")

            def do_POST(self):
                if not self.path.startswith("/upload"):
                    return self._send(404, "no")
                n = int(self.headers.get("Content-Length", 0))
                raw = self.headers.get("X-Name", "photo.jpg")
                try:
                    name = raw.encode("latin-1").decode("utf-8")
                except Exception:
                    name = raw
                name = Path(name).name or "photo.jpg"
                if not name.lower().endswith(IMG_EXT) or not 0 < n < 60_000_000:
                    return self._send(400, "bad")
                data = self.rfile.read(n)
                PHONE_DIR.mkdir(parents=True, exist_ok=True)
                dest = PHONE_DIR / name
                dest.write_bytes(data)
                app.q.put(("phone", name, None))
                app.jobs.put(dest)
                self._send(200, "ok")

        try:
            srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
        except OSError:
            self.phone_state = f"휴대폰 수신 불가(포트 {PORT} 사용 중)"
            return
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.phone_state = f"휴대폰 화면 http://{self.ip}:{PORT}/"

    # ------------------------------------------------------------ USB 연결 휴대폰
    def _ps(self, *args, timeout=90):
        ps1 = HERE / "mtp_inbox.ps1"
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
             "Bypass", "-WindowStyle", "Hidden", "-File", str(ps1), *args],
            capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
        return r.stdout.decode("utf-8", "replace").splitlines()

    def _usb_watch(self):
        seen_file = RESULT_DIR / "usb_seen.txt"
        RESULT_DIR.mkdir(parents=True, exist_ok=True)
        try:
            seen = set(seen_file.read_text(encoding="utf-8").splitlines())
        except OSError:
            seen = set()
        USB_DIR = RESULT_DIR / "usb_inbox"
        USB_DIR.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                lines = self._ps("list", timeout=30)
                dev = next((l.split("\t", 1)[1] for l in lines
                            if l.startswith("DEV\t")), "")
                self.usb_state = f"USB 연결: {dev}" if dev else ""
                for l in lines:
                    if not l.startswith("F\t"):
                        continue
                    _, name, size = (l.split("\t") + ["", ""])[:3]
                    key = f"{name}|{size}"
                    if key in seen:
                        continue
                    out = self._ps("copy", name, str(USB_DIR), timeout=120)
                    hit = next((l2.split("\t", 1)[1] for l2 in out
                                if l2.startswith("OK\t")), "")
                    if not hit:
                        continue
                    seen.add(key)
                    with open(seen_file, "a", encoding="utf-8") as fh:
                        fh.write(key + "\n")
                    path = Path(hit)
                    if path.suffix.lower() in IMG_EXT:
                        self.q.put(("phone", f"USB {path.name}", None))
                        self.jobs.put(path)
            except Exception:
                pass
            time.sleep(3)

    # ------------------------------------------------------------ 실물 모듈(USB)
    # 규약: 컴퓨터 -> 모듈  A5 5A + 160x80 RGB565(작은 끝 바이트 순서) 25600바이트
    #       모듈 -> 컴퓨터  한 글자 명령  N 다음 / P 이전 / F 첫 쪽 / T 해설 / H 연결
    def _send_frame(self, img):
        ser = self.ser
        if not ser:
            return
        px = img.load()
        out = bytearray(b"\xA5\x5A")
        for y in range(S.H):
            for x in range(S.W):
                r, g, b = px[x, y][:3]
                v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                out += bytes((v & 0xFF, v >> 8))
        try:
            with self.ser_lock:
                ser.write(out)
        except Exception:
            self.ser = None

    def _module_watch(self):
        if not ensure("serial", "pyserial"):
            self.mod_state = "모듈 연결 꾸러미 설치 실패"
            return
        import serial
        from serial.tools import list_ports
        while True:
            port = next((p.device for p in list_ports.comports()
                         if p.vid == 0x303A), None)   # 에스프레시프 USB
            if not port:
                self.mod_state = "모듈 없음"
                time.sleep(2)
                continue
            try:
                ser = serial.Serial(port, 921600, timeout=0.2, write_timeout=2)
            except Exception:
                self.mod_state = f"모듈 포트 열기 실패({port})"
                time.sleep(3)
                continue
            self.ser = ser
            self.mod_state = f"모듈 연결됨({port})"
            self.q.put(("mod", "H", None))
            try:
                while self.ser is ser:
                    c = ser.read(1)
                    if c and c in b"NPFTH":
                        self.q.put(("mod", c.decode(), None))
            except Exception:
                pass
            try:
                ser.close()
            except Exception:
                pass
            self.ser = None
            self.mod_state = "모듈 없음"

    # ------------------------------------------------------------ 휴대폰 화면
    def _web_pages(self, notes):
        if not self.text:
            return self.pages
        key = (self.ver, notes)
        if key not in self._web_cache:
            self._web_cache = {key: S.build_pages(S.parse(self.text), notes)}
        return self._web_cache[key]

    def web_state(self):
        return {"v": self.ver, "busy": self.busy,
                "n0": len(self._web_pages(False)),
                "n1": len(self._web_pages(True))}

    def web_page(self, i, notes, frame):
        import io
        pages = self._web_pages(notes)
        i = max(0, min(i, len(pages) - 1))
        img = S.render(pages[i], i, len(pages), frame)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def phone_url(self):
        return f"http://{self.ip}:{PORT}/"

    def _push_shortcut(self):
        """휴대폰 Download 폴더에 '채점화면_열기.html' 바로가기를 넣는다."""
        html = ('<!doctype html><meta charset="utf-8">'
                f'<meta http-equiv="refresh" content="0;url={self.phone_url()}">'
                f'<a href="{self.phone_url()}">채점 화면 열기</a>')
        tmp = RESULT_DIR / "shortcut"
        tmp.mkdir(parents=True, exist_ok=True)
        f = tmp / "채점화면_열기.html"
        f.write_text(html, encoding="utf-8")
        out = self._ps("push", "", str(f), timeout=60)
        return any(l.startswith("PUSHED") for l in out)

    def phone_cmd(self):
        return (f"pkg install -y curl && "
                f"curl -s http://{self.ip}:{PORT}/setup | bash")

    def phone_help(self):
        cmd = self.phone_cmd()
        self.root.clipboard_clear()
        self.root.clipboard_append(cmd)
        w = tk.Toplevel(self.root)
        w.title("휴대폰 연결")
        w.configure(bg="#0e0f10")
        txt = (f"[휴대폰에서 화면 보기]\n"
               f"휴대폰 인터넷 창에서  {self.phone_url()}  열기\n"
               f"(USB 로 연결되어 있으면 Download 폴더의 '채점화면_열기.html' 을 눌러도 됨)\n\n"
               "[휴대폰 사진을 와이파이로 보내기 — USB 없을 때]\n"
               "1. 휴대폰과 이 컴퓨터를 같은 와이파이에 연결\n\n"
               "2. 휴대폰 터묵스(Termux)를 열고 아래 한 줄을 붙여넣어 실행\n"
               "    (이미 복사되어 있습니다. 카톡 등으로 휴대폰에 보내 붙여넣기)\n\n"
               "3. 저장공간 권한 창이 뜨면 '허용'\n\n"
               "4. 이후 Download/exp_inbox 에 사진을 저장하면 자동 채점되어 화면에 뜹니다")
        tk.Label(w, text=txt, justify="left", font=UI_FONT, bg="#0e0f10",
                 fg="#d8d8d8").pack(padx=18, pady=(16, 8), anchor="w")
        e = tk.Entry(w, font=("Consolas", 11), width=len(cmd) + 2)
        e.insert(0, cmd)
        e.pack(padx=18, pady=(0, 16))
        e.select_range(0, "end")

    # ------------------------------------------------------------ 반복 확인
    def _newest(self):
        try:
            files = list(RESULT_DIR.glob("*.txt"))
        except Exception:
            return None
        return max(files, key=lambda f: f.stat().st_mtime) if files else None

    def _newest_mtime(self):
        f = self._newest()
        return f.stat().st_mtime if f else 0

    def _load_newest(self, initial=False):
        f = self._newest()
        if not f:
            return
        mt = f.stat().st_mtime
        if initial or mt > self.last_seen:
            self.last_seen = mt
            try:
                self.show_text(f.read_text(encoding="utf-8"), f.name)
            except Exception:
                pass

    def _tick(self):
        try:
            kind, payload, out = self.q.get_nowait()
            if kind == "mod":
                if payload == "N":
                    self.button("next")
                elif payload == "P":
                    self.button("prev")
                elif payload == "F":
                    self.button("prev", True)
                elif payload == "T":
                    self.button("next", True)
                else:
                    self.redraw()           # 연결 직후 현재 화면 보내기
            elif kind == "start":
                self.busy = True
                self.show_msg("채점 중", payload, color=S.GREEN, spin=True)
            elif kind == "phone":
                self.phone_state = f"휴대폰에서 받음: {payload}"
                self.status.config(text=self.phone_state)
                self.usb_state = ""
            elif kind == "ok":
                self.last_seen = out.stat().st_mtime
                self.show_text(payload, out.name)
            else:
                self.busy = False
                self.show_msg("오류", payload, color=S.RED)
        except queue.Empty:
            pass
        if self.busy:
            self.frame += 1
            if self.frame % 3 == 0:
                self.redraw()
        elif self.watch.get() and self.frame % 20 == 0:
            self._load_newest()
        if not self.busy:
            self.frame += 1
        self.root.after(100, self._tick)


if __name__ == "__main__":
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.0)
    except Exception:
        pass
    App(root)
    root.mainloop()
