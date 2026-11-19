"""채점일꾼 설치 — 두 번 누르면 끝.

1) 이 컴퓨터에 클로드 명령줄 도구가 없으면 설치 창을 띄운다(처음 한 번, 구독 계정 로그인).
2) 있으면 로그인 상태를 확인하고, 컴퓨터를 켤 때마다 채점일꾼이 창 없이 자동으로 켜지게 등록한 뒤 바로 켠다.
"""
import importlib.util
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

HERE = Path(__file__).resolve().parent
WORKER = HERE / "채점일꾼.pyw"
NO_WINDOW = 0x08000000


def load_worker():
    from importlib.machinery import SourceFileLoader   # .pyw 는 확장자로 못 알아봐 직접 지정
    spec = importlib.util.spec_from_file_location("worker", WORKER,
                                                  loader=SourceFileLoader("worker", str(WORKER)))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def pythonw():
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def main():
    root = tk.Tk()
    root.withdraw()
    W = load_worker()
    claude = W.find_claude()
    if not claude:
        messagebox.showinfo("채점일꾼 설치",
                            "이 컴퓨터에 클로드 명령줄 도구가 없어 설치 창을 엽니다.\n\n"
                            "1. 설치가 끝나면 같은 창에서 클로드가 켜집니다.\n"
                            "2. 로그인 방법을 고르라고 하면 「구독 계정(Claude 계정)」을 고르고 브라우저에서 승인합니다.\n"
                            "3. 로그인이 끝나면 창을 닫고 이 파일을 다시 두 번 눌러 주세요.")
        cmd = ("irm https://claude.ai/install.ps1 | iex; "
               "$env:Path += ';' + $env:USERPROFILE + '\\.local\\bin'; claude")
        subprocess.Popen(["powershell", "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", cmd])
        return

    # 로그인 확인: 짧은 질문 하나
    args = [claude, "-p", "--output-format", "text"]
    if claude.lower().endswith(".cmd"):
        args = ["cmd", "/c"] + args
    try:
        r = subprocess.run(args, input="숫자 1만 답하라".encode("utf-8"), capture_output=True,
                           timeout=90, creationflags=NO_WINDOW)
        ok = r.returncode == 0 and r.stdout.strip()
        why = (r.stderr or r.stdout).decode("utf-8", "replace")[:200]
    except Exception as e:
        ok, why = False, str(e)
    if not ok:
        messagebox.showinfo("채점일꾼 설치",
                            "클로드 로그인이 필요합니다. 창이 열리면 「구독 계정」으로 로그인한 뒤\n"
                            "창을 닫고 이 파일을 다시 두 번 눌러 주세요.\n\n(" + why.strip() + ")")
        subprocess.Popen(["powershell", "-NoExit", "-Command", f"& '{claude}'"])
        return

    # 컴퓨터 켤 때마다 자동 실행 등록 + 지금 켜기 (창 없이)
    tr = f'"{pythonw()}" "{WORKER}"'
    subprocess.run(["schtasks", "/create", "/tn", "채점일꾼", "/sc", "onlogon", "/rl", "limited",
                    "/f", "/tr", tr], capture_output=True, creationflags=NO_WINDOW)
    subprocess.Popen([pythonw(), str(WORKER)], creationflags=NO_WINDOW,
                     cwd=str(HERE), close_fds=True)
    messagebox.showinfo("채점일꾼 설치",
                        "설치 끝.\n\n- 지금부터 채점은 이 컴퓨터의 구독 클로드로 합니다(추가 비용 없음).\n"
                        "- 컴퓨터를 켤 때마다 창 없이 자동으로 켜집니다.\n"
                        "- 컴퓨터가 꺼져 있으면 클로드 키로 자동 전환, 켜지면 다시 구독으로 돌아옵니다.\n"
                        f"- 기록: {Path.home() / 'grade_results' / '채점일꾼_기록.txt'}")


if __name__ == "__main__":
    main()
