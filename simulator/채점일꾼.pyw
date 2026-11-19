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
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = Path.home() / "grade_results" / "채점일꾼_기록.txt"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
       "image/gif": ".gif", "application/pdf": ".pdf"}
LIMIT_WORDS = ("usage limit", "rate limit", "limit reached", "한도", "quota", "overloaded")
AUTH_WORDS = ("login", "log in", "authentication", "unauthorized", "oauth", "credit balance")
STATUS = Path.home() / "grade_results" / "채점_점검상태.txt"
LAST_SYSTEM = Path.home() / "grade_results" / "채점_지시문_최신.txt"


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


CONFIG_URL = "https://raw.githubusercontent.com/thecloudstay/grade-screen/main/relay/config.json"
_cfg = {"at": 0, "q": {}}


def queue_cfg():
    """중계기와 같은 설정 파일(깃허브)을 5분마다 읽어 모델·노력 수준·시간 한도를 맞춘다."""
    if time.time() - _cfg["at"] > 300:
        try:
            with urllib.request.urlopen(CONFIG_URL, timeout=5) as r:
                _cfg["q"] = json.loads(r.read().decode("utf-8")).get("queue", {})
        except Exception:
            pass
        _cfg["at"] = time.time()
    return _cfg["q"]


def _run(args, data, cwd, timeout):
    if args[0].lower().endswith(".cmd"):
        args = ["cmd", "/c"] + args
    return subprocess.run(args, input=data, capture_output=True, cwd=cwd,
                          timeout=timeout, creationflags=NO_WINDOW)


def grade_with_subscription(claude, job):
    """빠른 길: 도구·확장·설정 없이 사진을 바로 넘긴다(읽기 도구 왕복이 없어 한 번에 끝남).
    실패하면 예전 길(읽기 도구로 파일 열기)로 한 번 더."""
    try:   # 중계기에 닿지 않을 때 시뮬레이터가 쓸 최신 지시문 보관
        LAST_SYSTEM.write_text(job["system"], encoding="utf-8")
    except OSError:
        pass
    q = queue_cfg()
    model = q.get("worker_model") or job.get("model") or "sonnet"
    effort = q.get("worker_effort", "medium")
    limit = int(q.get("worker_timeout", 115))
    media = job.get("media") or "image/jpeg"
    work = Path(tempfile.mkdtemp(prefix="grade_"))
    try:
        sysf = work / "system.txt"
        sysf.write_text(job["system"], encoding="utf-8")
        block = ({"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": job["img_b64"]}}
                 if media == "application/pdf" else
                 {"type": "image", "source": {"type": "base64", "media_type": media, "data": job["img_b64"]}})
        msg = {"type": "user", "message": {"role": "user", "content": [
            block, {"type": "text", "text": "Grade this solved practice sheet as instructed."}]}}
        args = [claude, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                "--model", model, "--tools", "", "--strict-mcp-config", "--setting-sources", "",
                "--disable-slash-commands", "--system-prompt-file", str(sysf)]
        if effort:
            args += ["--effort", effort]
        r = _run(args, (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"), str(work), limit)
        result, err = "", ""
        for line in r.stdout.decode("utf-8", "replace").splitlines():
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if j.get("type") == "result":
                if j.get("is_error"):
                    err = str(j.get("result") or j.get("subtype"))
                else:
                    result = j.get("result") or ""
        if result.strip():
            return clean(result)
        raise RuntimeError(err or r.stderr.decode("utf-8", "replace")[:300] or f"종료 코드 {r.returncode}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def status(state, detail=""):
    try:
        STATUS.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{state}\t{detail}\n", encoding="utf-8")
    except OSError:
        pass


def selftest_loop():
    """전체 길 자가 점검: 시험 사진 한 장을 실제 중계기로 보내 「구독」 경로로 결과가 오는지 확인.
    켤 때(1분 뒤) 한 번, 이후 6시간마다. 결과는 채점_점검상태.txt 와 기록에 남김."""
    time.sleep(60)
    while True:
        try:
            cfg = config()
            sample = HERE / "시험샘플" / "01_기초수학.jpg"
            if sample.exists():
                url = relay_base(cfg)
                req = urllib.request.Request(url, data=sample.read_bytes(), method="POST", headers={
                    "content-type": "image/jpeg", "x-device-token": cfg.get("token", ""),
                    "x-device-id": "selftest"})
                t0 = time.time()
                try:
                    with urllib.request.urlopen(req, timeout=180) as r:
                        body = r.read().decode("utf-8", "replace")
                        route = urllib.parse.unquote(r.headers.get("x-grade-route", ""))
                except urllib.error.HTTPError as e:
                    body, route = e.read().decode("utf-8", "replace"), ""
                sec = time.time() - t0
                ok = "점수" in body and "구독" in route
                status("정상" if ok else "이상", f"{sec:.0f}초 · 경로 {route or '-'} · {body.strip()[:80]}")
                log(f"자가 점검 {'정상' if ok else '이상'} {sec:.0f}초 경로={route or '-'}")
        except Exception as e:
            status("이상", f"점검 실패: {str(e)[:100]}")
            log(f"자가 점검 실패: {str(e)[:100]}")
        time.sleep(6 * 3600)


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
    import threading
    threading.Thread(target=selftest_loop, daemon=True).start()
    fails, pause_until = 0, 0.0
    me = Path(__file__).resolve()
    born = me.stat().st_mtime
    while True:
        try:
            # 이 파일이 새 판으로 바뀌면 스스로 다시 켠다(대표 손 없이 고친 판 반영)
            if me.stat().st_mtime != born:
                log("새 판 감지 → 다시 켬")
                _lock.close()
                subprocess.Popen([sys.executable, str(me)], creationflags=NO_WINDOW, close_fds=True)
                return
            standby = time.time() < pause_until
            cfg = config()
            base, token = relay_base(cfg), cfg.get("token", "")
            claude = find_claude()
            if not claude:
                log("클로드 명령줄 도구를 못 찾음 → 1분 뒤 다시 (그동안 토큰 소모형)")
                time.sleep(60)
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
                if any(w in msg.lower() for w in AUTH_WORDS):
                    log("클로드 로그인 풀림 의심 → 채점일꾼_설치.pyw 를 다시 눌러 로그인 필요")
                    status("로그인 필요", msg[:120])
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
