import base64
import io
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

OUT_DIR = Path.home() / "grade_results"
API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "8000"))
MAX_BYTES = 3_500_000
MAX_SIDE = 1600

COMMON = (
    "You grade a practice sheet that the learner has "
    "already solved. For each numbered question in the "
    "image, read the answer the learner marked or wrote. "
    "Then work out the correct answer yourself and judge "
    "the learner's answer. "
    "If a question has no marked or written answer, "
    "count it as unmarked: do not grade it, but still "
    "solve it and give its correct answer in the "
    "unmarked line format below. Write everything in Korean. "
    "No introductions and no markdown.\n"
)

BRIEF = (
    "List only the questions the learner got wrong, "
    "one line each:\n"
    "<number>\ubc88 | \ub0b4 \ub2f5: <learner answer> | "
    "\uc815\ub2f5: <correct answer>\n"
    "Then each unmarked question, one line each:\n"
    "<number>\ubc88 | \ubbf8\ud45c\uae30 | "
    "\uc815\ub2f5: <correct answer>\n"
    "Then one last line:\n"
    "\uc810\uc218: <correct>/<graded> "
    "(\ubbf8\ud45c\uae30 <unmarked count>)\n"
)

FULL = (
    "One block per graded question:\n"
    "<number>\ubc88 | \ub0b4 \ub2f5: <learner answer> | "
    "\uc815\ub2f5: <correct answer> | <O or X>\n"
    "\ud574\uc124: <two or three sentences explaining why>\n"
    "One block per unmarked question:\n"
    "<number>\ubc88 | \ubbf8\ud45c\uae30 | "
    "\uc815\ub2f5: <correct answer>\n"
    "\ud574\uc124: <two or three sentences explaining why>\n"
    "Then a last block:\n"
    "\uc810\uc218: <correct>/<graded> "
    "(\ubbf8\ud45c\uae30 <unmarked count>)\n"
    "\ucde8\uc57d \ubd80\ubd84: "
    "<topics the learner should review>\n"
)

TAIL = (
    "If the image is illegible, output exactly: "
    "\ud310\ub3c5\ubd88\uac00"
)

USER_PROMPT = "Grade this solved practice sheet as instructed."

TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".png": "image/png",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
}
CONVERT = (".bmp", ".tif", ".tiff", ".heic", ".heif")   # 사진 형식이지만 jpeg 로 바꿔 보냄


def load_image(path: Path) -> tuple[str, str]:
    ext = path.suffix.lower()
    media = TYPES.get(ext)
    raw = path.read_bytes()
    if ext in CONVERT:
        if ext in (".heic", ".heif"):
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError as exc:
                raise RuntimeError("install pillow-heif for heic photos") from exc
        return base64.b64encode(shrink(raw)).decode("ascii"), "image/jpeg"
    if not media:
        raise RuntimeError("unsupported image type")
    if media == "application/pdf":
        return base64.b64encode(raw).decode("ascii"), media
    if len(raw) > MAX_BYTES:
        raw = shrink(raw)
        media = "image/jpeg"
    return base64.b64encode(raw).decode("ascii"), media


def shrink(raw: bytes) -> bytes:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError(
            "image too large; install Pillow to shrink it"
        ) from exc
    with Image.open(io.BytesIO(raw)) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        out = b""
        for quality in (85, 70, 55):
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=quality)
            out = buf.getvalue()
            if len(out) <= MAX_BYTES:
                break
        return out


def grade(path: Path, full: bool) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    b64_data, media = load_image(path)
    system = COMMON + (FULL if full else BRIEF) + TAIL
    image_block = {
        "type": "document" if media == "application/pdf" else "image",
        "source": {
            "type": "base64",
            "media_type": media,
            "data": b64_data,
        },
    }
    text_block = {"type": "text", "text": USER_PROMPT}
    payload = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        # 하이쿠 5.5 는 생각이 기본으로 켜져 최대 길이를 다 써 버릴 수 있어 끈다
        "thinking": {"type": "disabled"},
        "system": system,
        "messages": [
            {
                "role": "user",
                "content": [image_block, text_block],
            }
        ],
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    parts = []
    for block in body.get("content", []):
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts).strip()


def main() -> None:
    args = sys.argv[1:]
    full = "-v" in args
    photos = [a for a in args if a != "-v"]
    if not photos:
        print("usage: python3 grade.py [-v] <photo> ...")
        sys.exit(1)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for arg in photos:
        path = Path(arg).expanduser()
        if not path.is_file():
            print(f"[SKIP] not found: {path}")
            continue
        print(f"[GRADE] {path.name}")
        started = time.time()
        try:
            result = grade(path, full)
        except Exception as exc:
            print(f"[ERR] {exc}", file=sys.stderr)
            continue
        out = OUT_DIR / f"{stamp}_{path.stem}.txt"
        out.write_text(result + "\n", encoding="utf-8")
        print(result)
        took = time.time() - started
        print(f"[SAVED] {out} ({took:.1f}s)")
        print()


if __name__ == "__main__":
    main()
