"""채점일꾼 — 대표 컴퓨터에서 창 없이 돌며 정액 구독 클로드로 채점한다.

흐름: 중계기 대기열에 사진이 들어오면 받아서 → 이 컴퓨터의 클로드(명령줄, 구독 로그인)로 채점 → 결과를 올림.
컴퓨터가 꺼져 있거나 이 일꾼이 멈추면 중계기가 알아서 클로드 키(토큰 소모형)로 채점한다.

자동 전환(대표 결정 2026-11-19, 위험 관리):
- 일꾼이 25초마다 「살아 있음」을 알린다. 45초 넘게 소식이 없으면 중계기는 곧장 토큰 소모형으로.
- 구독 사용 한도에 걸리거나 클로드가 연달아 실패하면 일꾼이 10분 동안 스스로 물러난다
  (그동안 「쉬는 중」으로 알려 새 사진은 기다림 없이 토큰 소모형으로 감) → 10분 뒤 저절로 다시 구독형.
- 일꾼이 사진을 받고도 80초 안에 결과를 못 내면 중계기가 토큰 소모형으로 넘긴다.
- 반대로 토큰 소모형이 끊기면(충전금 소진·키 문제 등) 컴퓨터가 켜져 있는 한, 쉬는 중이어도
  「되살림」 일로 받아 구독형으로 채점한다.

기록: %USERPROFILE%\\grade_results\\채점일꾼_기록.txt
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = Path.home() / "grade_results" / "채점일꾼_기록.txt"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
       "image/gif": ".gif", "application/pdf": ".pdf"}
LIMIT_WORDS = ("usage limit", "rate limit", "limit reached", "한도", "quota", "overloaded")


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%m-%d %H:%M:%S ") + msg + "\n")
    try:   # 기록이 너무 커지지 않게 뒤 2천 줄만
        lines = LOG.read_text(encoding="utf-8").splitlines()
        if len(lines) > 3000:
            LOG.write_text("\n".join(lines[-2000:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def config():
    return json.loads((HERE / "설정.json").read_text(encoding="utf-8"))


def relay_base(cfg):
    for r in cfg.get("relays", []):
        u = r if isinstance(r, str) else r.get("url", "")
        if "supabase" in u:
            return u.rstrip("/")
    raise RuntimeError("설정.json 에 슈퍼베이스 중계 주소가 없음")


def post(url, token, body, timeout, standby=False):
    h = {"content-type": "application/json", "x-device-token": token, "x-device-id": "pc-worker"}
    if standby:
        h["x-worker-standby"] = "1"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def find_claude():
    for name in ("claude", "claude.cmd", "claude.exe"):
        p = shutil.which(name)
        if p:
            return p
    for p in (Path.home() / ".local" / "bin" / "claude.exe",
              Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd"):
        if p.exists():
            return str(p)
    return None


def clean(text):
    """앞뒤 군말을 떼고 채점 형식만 남긴다."""
    lines = text.strip().splitlines()
    for i, ln in enumerate(lines):
        s = ln.strip().lstrip("#*` ")
        if s.startswith("수험번호") or s.startswith("판독불가") or s.startswith("점수"):
            return "\n".join(l.rstrip() for l in lines[i:]).strip().strip("`").strip()
    return text.strip()


def grade_with_subscription(claude, job):
    data = base64.b64decode(job["img_b64"])
    work = Path(tempfile.mkdtemp(prefix="grade_"))
    f = work / ("sheet" + EXT.get(job.get("media", ""), ".jpg"))
    f.write_bytes(data)
    prompt = (job["system"] + "\n\n"
              f"채점할 답안지 파일: {f}\n"
              "Read 도구로 이 파일을 열어 보고, 위 형식 그대로만 출력하라. 인사·설명·코드 상자 없이 첫 줄은 수험번호 줄.")
    args = [claude, "-p", "--model", job.get("model") or "sonnet",
            "--allowedTools", "Read", "--output-format", "text"]
    if claude.lower().endswith(".cmd"):
        args = ["cmd", "/c"] + args
    try:
        r = subprocess.run(args, input=prompt.encode("utf-8"), capture_output=True, cwd=str(work),
                           timeout=75, creationflags=NO_WINDOW)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    out = r.stdout.decode("utf-8", "replace")
    err = r.stderr.decode("utf-8", "replace")
    if r.returncode != 0 or not out.strip():
        raise RuntimeError((err or out or f"종료 코드 {r.returncode}").strip()[:300])
    return clean(out)


def main():
    if "--once" in sys.argv:   # 설치 확인용: 클로드가 있는지만 보고 끝
        print(find_claude() or "")
        return
    import socket
    global _lock
    _lock = socket.socket()
    try:   # 하나만 돌게(설치 때와 로그인 때 겹쳐 켜져도)
        _lock.bind(("127.0.0.1", 8766))
    except OSError:
        return
    log("시작")
    fails, pause_until = 0, 0.0
    while True:
        try:
            standby = time.time() < pause_until
            cfg = config()
            base, token = relay_base(cfg), cfg.get("token", "")
            claude = find_claude()
            if not claude:
                log("클로드 명령줄 도구를 못 찾음 → 10분 뒤 다시 (그동안 토큰 소모형)")
                time.sleep(600)
                continue
            # 쉬는 중에도 「켜져 있음」은 알린다 → 토큰 소모형이 끊기면 되살림 일은 맡는다
            job = post(base + "/worker/next", token, {}, timeout=40, standby=standby)
            if not job.get("id"):
                continue
            t0 = time.time()
            try:
                text = grade_with_subscription(claude, job)
                post(base + "/worker/result", token,
                     {"id": job["id"], "ok": True, "text": text, "model": "구독 " + job.get("model", "")}, timeout=20)
                log(f"채점 {job['id']} 완료 {time.time() - t0:.0f}초")
                fails = 0
            except Exception as e:  # 실패는 바로 알려 중계기가 곧장 토큰 소모형으로 넘기게
                msg = str(e)
                post(base + "/worker/result", token, {"id": job["id"], "ok": False, "error": msg}, timeout=20)
                fails += 1
                limited = any(w in msg.lower() for w in LIMIT_WORDS)
                log(f"채점 {job['id']} 실패({fails}회): {msg[:150]}")
                if limited or fails >= 2:
                    pause_until = time.time() + 600
                    fails = 0
                    log("구독 쪽 문제로 10분 물러남 → 그동안 토큰 소모형, 10분 뒤 자동 복귀")
        except Exception as e:   # 인터넷 끊김 등: 잠깐 쉬었다 다시
            log(f"연결 문제: {str(e)[:120]}")
            time.sleep(10)


if __name__ == "__main__":
    main()
