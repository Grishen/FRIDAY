"""Advanced multi-modal vision toolkit for the assistant.

Capabilities
============

Sources (capture an image / video / document):
- ``take_screenshot()``                 — full screen → PNG.
- ``capture_webcam()``                  — single frame from default camera.
- ``capture_webcam_burst(n, interval)`` — multi-frame burst (motion analysis).
- ``capture_clipboard_image()``         — pull an image from system clipboard.
- ``fetch_url_to_temp(url)``            — download an image/PDF from a URL.
- ``find_recent_image(max_age_hours)``  — newest image in common drop-zones.

Analysis (run a vision model over one or more images):
- ``analyze_image(path, mode, prompt)`` — single image, multiple modes:
       ``describe`` (default), ``ocr``, ``objects``, ``structured``,
       ``read_aloud``, ``code``, ``ui``.
- ``analyze_images(paths, mode, prompt)`` — multi-image (compare, diff, narrate).
- ``analyze_pdf(path, prompt, pages)``  — rasterize PDF pages → vision.
- ``analyze_target(target, prompt, mode)`` — smart router for `path|url|screen|
   camera|clipboard|last|download|pdf:...`.

Specialized wrappers (backwards-compatible with earlier callers):
- ``describe_image``, ``describe_screen``, ``describe_webcam``,
  ``describe_clipboard_image``, ``ask_about_last_image``.
- ``describe_webcam_motion(prompt)``    — burst → describe action.
- ``extract_text_from_image(path)``     — OCR convenience (string).
- ``detect_objects(path)``              — list[{label, confidence, bbox}].
- ``structured_analysis(path)``         — full JSON breakdown.
- ``compare_images([a, b], prompt)``    — side-by-side compare.

Annotation & generation:
- ``annotate_image(path, boxes)``       — render bboxes onto a copy.
- ``generate_image(prompt, size, ...)`` — text → image (DALL·E / gpt-image-1).

Memory / continuity:
- ``image_history()``                   — last N images (path, kind, ts, label).
- ``get_last_image()``                  — most recent (path, kind).
- ``remember_last_image(path, kind)``   — manual record.

Environment knobs
=================
- ``OPENAI_API_KEY``                  — required for vision + generation.
- ``OPENAI_VISION_MODEL``             — defaults to ``OPENAI_CHAT_MODEL`` (e.g. gpt-4o, gpt-4o-mini).
- ``OPENAI_IMAGE_GEN_MODEL``          — defaults to ``gpt-image-1``.
- ``JARVIS_VISION_MAX_PIXELS``        — downscale ceiling per image (default ~4MP).
- ``JARVIS_VISION_HISTORY``           — history depth (default 8).
- ``JARVIS_WEBCAM_INDEX``             — non-default camera (default 0).
- ``JARVIS_WEBCAM_DEVICE``            — ffmpeg device override (Linux/Windows).
- ``JARVIS_VISION_RECENT_HOURS``      — max age for `find_recent_image` (default 24).

Optional dependencies (each missing is handled gracefully):
- ``pip install Pillow``                — preprocessing, EXIF, annotate, clipboard.
- ``pip install pillow-heif``           — HEIC support (macOS Live Photos, iPhone).
- ``pip install pymupdf``               — PDF rasterization.
- ``pip install opencv-python``         — webcam fallback.
- ``brew install imagesnap pngpaste``   — best webcam + clipboard on macOS.
- ``brew install tesseract`` + ``pip install pytesseract`` — local OCR fallback.
"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from collections import deque
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

# --------------------------------------------------------------------------- #
# Config helpers
# --------------------------------------------------------------------------- #


def _vision_model() -> str:
    raw = os.environ.get("OPENAI_VISION_MODEL", "").strip()
    if raw:
        return raw
    return os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"


def _image_gen_model() -> str:
    return os.environ.get("OPENAI_IMAGE_GEN_MODEL", "gpt-image-1").strip() or "gpt-image-1"


def _max_pixels() -> int:
    try:
        return max(256 * 256, int(os.environ.get("JARVIS_VISION_MAX_PIXELS", str(4 * 1024 * 1024))))
    except (TypeError, ValueError):
        return 4 * 1024 * 1024


def _history_depth() -> int:
    try:
        return max(2, int(os.environ.get("JARVIS_VISION_HISTORY", "8")))
    except (TypeError, ValueError):
        return 8


def _webcam_index() -> int:
    try:
        return int(os.environ.get("JARVIS_WEBCAM_INDEX", "0"))
    except (TypeError, ValueError):
        return 0


def _has_pillow() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def _ensure_pillow_heif() -> None:
    """Register HEIC opener with Pillow if pillow-heif is installed."""
    try:
        import pillow_heif  # type: ignore

        pillow_heif.register_heif_opener()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Path & MIME helpers
# --------------------------------------------------------------------------- #


def _expand_user_path(image_path: str) -> str:
    p = os.path.expanduser((image_path or "").strip().strip('"').strip("'"))
    if not p:
        return p
    if not os.path.isabs(p):
        p = os.path.abspath(p)
    return p


def _guess_mime(path: str) -> str:
    mt, _ = mimetypes.guess_type(path)
    if mt and mt.startswith("image/"):
        return mt
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".heic": "image/heic",
        ".heif": "image/heic",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }.get(Path(path).suffix.lower(), "image/png")


def _looks_like_url(s: str) -> bool:
    if not s:
        return False
    s = s.strip()
    return s.startswith(("http://", "https://"))


# --------------------------------------------------------------------------- #
# Image preprocessing (rotate, resize, HEIC → PNG, EXIF metadata)
# --------------------------------------------------------------------------- #


def _heic_to_png_sips(src: str, dst: str) -> bool:
    """Fallback HEIC → PNG via macOS sips (no Pillow plugin required)."""
    if sys.platform != "darwin":
        return False
    sips = shutil.which("sips")
    if not sips:
        return False
    try:
        subprocess.run(
            [sips, "-s", "format", "png", src, "--out", dst],
            check=True, capture_output=True, text=True, timeout=15,
        )
        return os.path.isfile(dst) and os.path.getsize(dst) > 0
    except Exception:
        return False


def _prepare_image_bytes(path: str) -> tuple[Optional[bytes], str, dict]:
    """
    Load an image, auto-rotate via EXIF, downscale to fit ``_max_pixels()``,
    convert HEIC → PNG. Returns (bytes, mime, meta) where meta carries:
        { 'width', 'height', 'original_format', 'exif' }
    On failure, returns (None, '', {'error': ...}).
    """
    resolved = _expand_user_path(path)
    if not resolved or not os.path.isfile(resolved):
        return None, "", {"error": f"file not found: {path}"}

    if not _has_pillow():
        # Fallback: read raw bytes, infer MIME by extension, no preprocessing.
        try:
            with open(resolved, "rb") as f:
                data = f.read()
        except OSError as exc:
            return None, "", {"error": str(exc)}
        return data, _guess_mime(resolved), {"raw_bytes": True}

    _ensure_pillow_heif()
    from PIL import Image, ImageOps  # type: ignore

    suffix = Path(resolved).suffix.lower()
    work_path = resolved

    # HEIC fallback to sips if pillow-heif not loaded.
    if suffix in (".heic", ".heif"):
        try:
            Image.open(resolved).verify()
        except Exception:
            tmp_png = str(Path(tempfile.gettempdir()) / f"jarvis_heic_{int(time.time()*1000)}.png")
            if _heic_to_png_sips(resolved, tmp_png):
                work_path = tmp_png
            else:
                return None, "", {"error": "HEIC support missing; install pillow-heif or use macOS sips."}

    try:
        img = Image.open(work_path)
        img.load()
    except Exception as exc:
        return None, "", {"error": f"failed to open image: {exc}"}

    # Extract EXIF for metadata, then rotate accordingly.
    meta: dict = {"original_format": img.format, "original_size": list(img.size)}
    try:
        exif = img.getexif()
        if exif:
            from PIL.ExifTags import TAGS  # type: ignore

            decoded = {}
            for tag_id, value in exif.items():
                tag = TAGS.get(tag_id, str(tag_id))
                if isinstance(value, bytes):
                    try:
                        value = value.decode("utf-8", errors="replace")
                    except Exception:
                        value = f"<{len(value)} bytes>"
                if isinstance(value, (int, float, str)):
                    decoded[tag] = value
            if decoded:
                meta["exif"] = decoded
    except Exception:
        pass

    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    # Downscale if oversized to save tokens.
    max_px = _max_pixels()
    w, h = img.size
    if w * h > max_px:
        scale = (max_px / float(w * h)) ** 0.5
        new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
        try:
            img = img.resize(new_size, Image.LANCZOS)
            meta["resized_to"] = list(img.size)
        except Exception:
            pass

    if img.mode not in ("RGB", "RGBA"):
        try:
            img = img.convert("RGB")
        except Exception:
            pass

    buf = io.BytesIO()
    save_format = "PNG" if img.mode == "RGBA" else "JPEG"
    save_kwargs = {"quality": 90, "optimize": True} if save_format == "JPEG" else {}
    try:
        img.save(buf, format=save_format, **save_kwargs)
    except Exception as exc:
        return None, "", {"error": f"failed to encode image: {exc}"}
    meta["width"], meta["height"] = img.size
    meta["encoded_format"] = save_format
    return buf.getvalue(), f"image/{save_format.lower()}", meta


def _encode_to_data_url(image_bytes: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"


def _encode_image_b64(path: str) -> Optional[str]:
    """Legacy helper — preprocesses then base64-encodes."""
    data, _, _ = _prepare_image_bytes(path)
    if not data:
        return None
    return base64.b64encode(data).decode("ascii")


# --------------------------------------------------------------------------- #
# Image history (powers "the last two", "the screenshot from earlier")
# --------------------------------------------------------------------------- #


_IMAGE_HISTORY_LOCK = threading.Lock()
_IMAGE_HISTORY: deque = deque(maxlen=16)  # capacity refreshed in remember_last_image


def remember_last_image(path: str, *, kind: str = "image", label: str = "") -> None:
    """Record an image in the history (newest first)."""
    if not path:
        return
    entry = {"path": path, "kind": kind, "label": label, "ts": time.time()}
    with _IMAGE_HISTORY_LOCK:
        if _IMAGE_HISTORY.maxlen != _history_depth():
            new_dq: deque = deque(maxlen=_history_depth())
            new_dq.extend(list(_IMAGE_HISTORY)[-_history_depth():])
            _IMAGE_HISTORY.clear()
            _IMAGE_HISTORY.extend(new_dq)
        _IMAGE_HISTORY.append(entry)


def get_last_image() -> tuple[str, str]:
    """Returns (path, kind) of the most recent image. Empty path means none."""
    with _IMAGE_HISTORY_LOCK:
        if not _IMAGE_HISTORY:
            return "", ""
        last = _IMAGE_HISTORY[-1]
    return last.get("path", ""), last.get("kind", "")


def image_history() -> list[dict]:
    """Returns the full history newest-last as a list of dicts."""
    with _IMAGE_HISTORY_LOCK:
        return list(_IMAGE_HISTORY)


def _resolve_history_reference(ref: str) -> Optional[str]:
    """Map phrases like 'last', 'previous', 'the one before', '2 ago' to a path."""
    if not ref:
        return None
    r = ref.lower().strip()
    items = image_history()
    if not items:
        return None
    if r in ("", "last", "the last image", "the last one", "latest"):
        return items[-1]["path"]
    if r in ("previous", "before that", "the one before", "second to last"):
        if len(items) >= 2:
            return items[-2]["path"]
    m = re.search(r"(\d+)\s*(?:ago|back)", r)
    if m:
        n = int(m.group(1))
        if 0 <= n < len(items):
            return items[-(n + 1)]["path"]
    return None


# --------------------------------------------------------------------------- #
# Screen capture
# --------------------------------------------------------------------------- #


def take_screenshot(*, out_path: Optional[Path] = None) -> tuple[bool, str]:
    """Capture full screen. Returns (ok, path_or_error)."""
    target = out_path or Path(tempfile.gettempdir()) / f"jarvis_screen_{int(time.time())}.png"
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    if sys.platform == "darwin":
        try:
            subprocess.run(
                ["screencapture", "-x", "-t", "png", str(target)],
                check=True, capture_output=True, text=True, timeout=10,
            )
        except subprocess.CalledProcessError as exc:
            return False, f"screencapture failed (likely missing Screen Recording permission): {exc.stderr or exc}"
        except Exception as exc:  # noqa: BLE001
            return False, f"screencapture failed: {exc}"
        return True, str(target)

    if sys.platform == "win32":
        try:
            from PIL import ImageGrab  # type: ignore
        except ImportError:
            return False, "Install Pillow for Windows screenshots: pip install Pillow"
        try:
            img = ImageGrab.grab(all_screens=True)
            img.save(target, "PNG")
        except Exception as exc:  # noqa: BLE001
            return False, f"Windows screenshot failed: {exc}"
        return True, str(target)

    for cmd_template in (
        ["gnome-screenshot", "-f", str(target)],
        ["scrot", str(target)],
        ["maim", str(target)],
    ):
        exe = shutil.which(cmd_template[0])
        if not exe:
            continue
        try:
            subprocess.run(cmd_template, check=True, capture_output=True, text=True, timeout=10)
            return True, str(target)
        except Exception:  # noqa: BLE001
            continue
    return False, "No screenshot tool found (gnome-screenshot / scrot / maim)."


# --------------------------------------------------------------------------- #
# Webcam capture (imagesnap → opencv → ffmpeg) + burst
# --------------------------------------------------------------------------- #


def _capture_with_imagesnap(target: Path, warmup_s: float = 0.6) -> tuple[bool, str]:
    exe = shutil.which("imagesnap")
    if not exe:
        return False, "imagesnap not installed"
    try:
        subprocess.run(
            [exe, "-w", str(warmup_s), str(target)],
            check=True, capture_output=True, text=True, timeout=15,
        )
    except subprocess.CalledProcessError as exc:
        return False, f"imagesnap failed: {exc.stderr or exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"imagesnap failed: {exc}"
    if not target.is_file() or target.stat().st_size == 0:
        return False, "imagesnap produced no file (Camera permission?)"
    return True, str(target)


def _capture_with_opencv(target: Path, warmup_frames: int = 5) -> tuple[bool, str]:
    try:
        import cv2  # type: ignore
    except ImportError:
        return False, "opencv not installed"
    cap = cv2.VideoCapture(_webcam_index())
    if not cap or not cap.isOpened():
        if cap:
            cap.release()
        return False, "opencv could not open webcam"
    try:
        for _ in range(max(0, warmup_frames)):
            cap.read()
        ok, frame = cap.read()
        if not ok or frame is None:
            return False, "opencv failed to read frame"
        cv2.imwrite(str(target), frame)
    finally:
        cap.release()
    if not target.is_file() or target.stat().st_size == 0:
        return False, "opencv produced no file"
    return True, str(target)


def _capture_with_ffmpeg(target: Path) -> tuple[bool, str]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False, "ffmpeg not installed"
    idx = _webcam_index()
    if sys.platform == "darwin":
        cmd = [ffmpeg, "-y", "-f", "avfoundation", "-framerate", "30",
               "-i", f"{idx}:none", "-frames:v", "1", str(target)]
    elif sys.platform.startswith("linux"):
        device = os.environ.get("JARVIS_WEBCAM_DEVICE", f"/dev/video{idx}")
        cmd = [ffmpeg, "-y", "-f", "v4l2", "-i", device, "-frames:v", "1", str(target)]
    elif sys.platform == "win32":
        device = os.environ.get("JARVIS_WEBCAM_DEVICE", "")
        if not device:
            return False, "Set JARVIS_WEBCAM_DEVICE='video=YourCameraName' for ffmpeg on Windows"
        cmd = [ffmpeg, "-y", "-f", "dshow", "-i", device, "-frames:v", "1", str(target)]
    else:
        return False, f"ffmpeg path not configured for {sys.platform}"
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=15)
    except subprocess.CalledProcessError as exc:
        tail = exc.stderr[-400:] if exc.stderr else str(exc)
        return False, f"ffmpeg failed: {tail}"
    except Exception as exc:  # noqa: BLE001
        return False, f"ffmpeg failed: {exc}"
    if not target.is_file() or target.stat().st_size == 0:
        return False, "ffmpeg produced no file"
    return True, str(target)


def capture_webcam(*, out_path: Optional[Path] = None) -> tuple[bool, str]:
    """Capture a single webcam frame. Returns (ok, path_or_error)."""
    target = out_path or Path(tempfile.gettempdir()) / f"jarvis_webcam_{int(time.time()*1000)}.png"
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    for fn in (_capture_with_imagesnap, _capture_with_opencv, _capture_with_ffmpeg):
        ok, info = fn(target)
        if ok:
            return True, info
        errors.append(f"{fn.__name__}: {info}")

    hint = ""
    if sys.platform == "darwin":
        hint = (
            " On macOS install one of: `brew install imagesnap`, "
            "`pip install opencv-python`, or `brew install ffmpeg`. "
            "Also grant Camera permission to your terminal/IDE."
        )
    return False, "Could not capture from webcam. " + " | ".join(errors) + hint


def capture_webcam_burst(n: int = 3, interval_s: float = 0.6) -> tuple[bool, list[str] | str]:
    """Capture N webcam frames spaced ``interval_s`` apart. Returns (ok, paths_or_error)."""
    n = max(2, min(int(n or 3), 8))
    paths: list[str] = []
    for i in range(n):
        ts = int(time.time() * 1000)
        target = Path(tempfile.gettempdir()) / f"jarvis_burst_{ts}_{i}.png"
        ok, info = capture_webcam(out_path=target)
        if not ok:
            return False, info
        paths.append(info)
        if i < n - 1:
            time.sleep(max(0.05, float(interval_s)))
    return True, paths


# --------------------------------------------------------------------------- #
# Clipboard image
# --------------------------------------------------------------------------- #


def _clipboard_image_macos(target: Path) -> tuple[bool, str]:
    pngpaste = shutil.which("pngpaste")
    if pngpaste:
        try:
            res = subprocess.run([pngpaste, str(target)], capture_output=True, text=True, timeout=8)
            if res.returncode == 0 and target.is_file() and target.stat().st_size > 0:
                return True, str(target)
        except Exception:  # noqa: BLE001
            pass
    script = (
        'try\n'
        '  set thePNG to (the clipboard as «class PNGf»)\n'
        f'  set theFile to (open for access POSIX file "{target}" with write permission)\n'
        '  set eof of theFile to 0\n'
        '  write thePNG to theFile\n'
        '  close access theFile\n'
        '  return "ok"\n'
        'on error errMsg\n'
        '  try\n'
        '    close access theFile\n'
        '  end try\n'
        '  return "err:" & errMsg\n'
        'end try\n'
    )
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=8)
    except Exception as exc:  # noqa: BLE001
        return False, f"osascript failed: {exc}"
    out = (res.stdout or "").strip()
    if out == "ok" and target.is_file() and target.stat().st_size > 0:
        return True, str(target)
    return False, "No image on clipboard (or unsupported format). Try `brew install pngpaste`."


def capture_clipboard_image(*, out_path: Optional[Path] = None) -> tuple[bool, str]:
    """Grab image from clipboard. Returns (ok, path_or_error)."""
    target = out_path or Path(tempfile.gettempdir()) / f"jarvis_clipboard_{int(time.time()*1000)}.png"
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    if sys.platform == "darwin":
        return _clipboard_image_macos(target)

    try:
        from PIL import ImageGrab  # type: ignore

        img = ImageGrab.grabclipboard()
        if img is None:
            return False, "No image on clipboard."
        if isinstance(img, list):
            for candidate in img:
                if isinstance(candidate, (str, Path)) and Path(candidate).is_file():
                    shutil.copyfile(candidate, target)
                    return True, str(target)
            return False, "Clipboard had file references but none were images."
        img.save(target, "PNG")
        return True, str(target)
    except ImportError:
        return False, "Install Pillow for clipboard image support: pip install Pillow"
    except Exception as exc:  # noqa: BLE001
        return False, f"Clipboard read failed: {exc}"


# --------------------------------------------------------------------------- #
# URL fetch + recent file picker
# --------------------------------------------------------------------------- #


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".heif", ".tif", ".tiff"}
_PDF_EXTS = {".pdf"}


def fetch_url_to_temp(url: str) -> tuple[bool, str]:
    """Download an image or PDF from a URL into a temp file. Returns (ok, path_or_error)."""
    if not _looks_like_url(url):
        return False, f"Not an http(s) URL: {url}"
    try:
        import requests  # type: ignore
    except ImportError:
        return False, "Install requests: pip install requests"
    try:
        resp = requests.get(url, timeout=20, stream=True, headers={"User-Agent": "Jarvis/1.0"})
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return False, f"Download failed: {exc}"

    ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    parsed = urllib.parse.urlparse(url)
    name = os.path.basename(parsed.path) or "download"
    ext = Path(name).suffix.lower()
    if not ext:
        if "pdf" in ctype:
            ext = ".pdf"
        elif "jpeg" in ctype or "jpg" in ctype:
            ext = ".jpg"
        elif "png" in ctype:
            ext = ".png"
        elif "webp" in ctype:
            ext = ".webp"
        elif "gif" in ctype:
            ext = ".gif"
        else:
            ext = ".bin"
    target = Path(tempfile.gettempdir()) / f"jarvis_url_{int(time.time()*1000)}{ext}"
    try:
        with open(target, "wb") as f:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)
    except Exception as exc:  # noqa: BLE001
        return False, f"Write failed: {exc}"
    if target.stat().st_size == 0:
        return False, "Downloaded file is empty."
    return True, str(target)


def find_recent_image(max_age_hours: Optional[float] = None) -> Optional[str]:
    """Scan common drop-zones for the most recent image file."""
    try:
        max_h = float(max_age_hours) if max_age_hours is not None \
            else float(os.environ.get("JARVIS_VISION_RECENT_HOURS", "24"))
    except (TypeError, ValueError):
        max_h = 24.0
    cutoff = time.time() - max_h * 3600

    home = Path.home()
    candidates: list[Path] = []
    for sub in ("Downloads", "Desktop", "Pictures", "Screenshots"):
        d = home / sub
        if d.is_dir():
            try:
                for p in d.iterdir():
                    if p.is_file() and p.suffix.lower() in _IMAGE_EXTS:
                        try:
                            if p.stat().st_mtime >= cutoff:
                                candidates.append(p)
                        except OSError:
                            continue
            except OSError:
                continue

    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return str(candidates[0])


# --------------------------------------------------------------------------- #
# Vision LLM core
# --------------------------------------------------------------------------- #


def _openai_client():
    try:
        from openai import OpenAI

        return OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    except KeyError:
        return None
    except ImportError:
        return None


_MODE_PROMPTS: dict[str, str] = {
    "describe": (
        "Describe this image in plain natural language as if narrating to someone who can't see it. "
        "Identify the main subject(s), notable text, setting, and likely context. "
        "Keep it under 8 sentences and be concrete."
    ),
    "ocr": (
        "Extract ALL legible text from this image. Preserve reading order. "
        "Group text into logical blocks (paragraphs / headings / buttons / labels). "
        "Respond in JSON with shape: "
        '{"text":"<entire text concatenated, newlines between blocks>", '
        '"blocks":[{"text":"...","kind":"heading|paragraph|button|label|caption|other"}], '
        '"language":"ISO-639-1 or null"}'
    ),
    "read_aloud": (
        "Read out the human-meaningful text in this image (signs, headlines, the message that "
        "matters). Skip UI chrome, watermarks, and decoration. Return plain prose suitable to be "
        "spoken aloud in under 6 sentences."
    ),
    "objects": (
        "Detect the salient objects in this image. Return JSON: "
        '{"objects":[{"label":"...","confidence":0.0-1.0,"bbox":[x,y,w,h]}]} '
        "where bbox is normalized [0,1] in image coordinates. Include up to 12 objects. "
        "If none, return {\"objects\":[]}."
    ),
    "structured": (
        "Produce a complete structured analysis of this image as JSON with shape: "
        "{"
        '"summary":"1–3 sentence description",'
        '"scene":"indoor|outdoor|screen|document|other + brief setting",'
        '"objects":[{"label":"...","confidence":0.0-1.0,"bbox":[x,y,w,h]}],'
        '"people_count":0,'
        '"text":"any prominent text",'
        '"colors":["#rrggbb","..."],'
        '"mood":"calm|tense|cheerful|neutral|...",'
        '"actions":["what is happening"],'
        '"suggested_next_steps":["actionable things the user might want"]'
        "}. bbox values are normalized [0,1]. Omit fields that don't apply by setting them to "
        "empty / null."
    ),
    "code": (
        "This image likely contains source code or a UI showing code. Transcribe the code "
        "faithfully (preserve indentation), then list any obvious bugs, suspicious patterns, "
        "or fixes in bullets. Return JSON: "
        '{"language":"...","code":"...","notes":["..."]}'
    ),
    "ui": (
        "This is a screenshot of a UI. Identify the app/page, the user's likely current task, "
        "key controls (buttons / inputs / menus), any error or warning visible, and the most "
        "useful next action. Return JSON: "
        '{"app":"...","page":"...","task":"...","controls":["..."],"errors":["..."],"next_action":"..."}'
    ),
}


_JSON_MODES = {"ocr", "objects", "structured", "code", "ui"}


def _build_image_part(path: str) -> tuple[Optional[dict], Optional[str]]:
    data, mime, meta = _prepare_image_bytes(path)
    if not data:
        return None, meta.get("error", "could not load image")
    return {"type": "image_url", "image_url": {"url": _encode_to_data_url(data, mime)}}, None


def _run_vision(
    image_paths: Sequence[str],
    *,
    prompt: str,
    mode: str = "describe",
    extra_system: str = "",
    json_mode: Optional[bool] = None,
    temperature: float = 0.3,
) -> dict:
    """
    Low-level vision call. Returns dict with keys:
      ok: bool
      text: str (raw model output)
      json: dict|list|None (parsed if json mode)
      error: str|None
    """
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        return {"ok": False, "text": "", "json": None, "error": "OPENAI_API_KEY not set."}

    image_parts: list[dict] = []
    for p in image_paths:
        part, err = _build_image_part(p)
        if not part:
            return {"ok": False, "text": "", "json": None, "error": err or f"failed to load {p}"}
        image_parts.append(part)
    if not image_parts:
        return {"ok": False, "text": "", "json": None, "error": "no images provided"}

    client = _openai_client()
    if client is None:
        return {"ok": False, "text": "", "json": None, "error": "OpenAI client unavailable"}

    if json_mode is None:
        json_mode = mode in _JSON_MODES

    messages: list[dict] = []
    if extra_system:
        messages.append({"role": "system", "content": extra_system})
    user_content: list[dict] = [{"type": "text", "text": prompt}]
    user_content.extend(image_parts)
    messages.append({"role": "user", "content": user_content})

    kwargs: dict[str, Any] = {
        "model": _vision_model(),
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        completion = client.chat.completions.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        # Retry without response_format if the model rejects it.
        if json_mode:
            try:
                kwargs.pop("response_format", None)
                completion = client.chat.completions.create(**kwargs)
            except Exception as exc2:  # noqa: BLE001
                return {"ok": False, "text": "", "json": None, "error": f"vision call failed: {exc2}"}
        else:
            return {"ok": False, "text": "", "json": None, "error": f"vision call failed: {exc}"}

    raw = getattr(completion.choices[0].message, "content", None) or ""
    raw = raw.strip()
    parsed: Any = None
    if json_mode:
        parsed = _safe_parse_json(raw)
    return {"ok": True, "text": raw, "json": parsed, "error": None}


def _safe_parse_json(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip code fences.
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Find first balanced {...} or [...] block.
    for open_c, close_c in (("{", "}"), ("[", "]")):
        i = text.find(open_c)
        while i != -1:
            depth = 0
            for j in range(i, len(text)):
                if text[j] == open_c:
                    depth += 1
                elif text[j] == close_c:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[i : j + 1])
                        except json.JSONDecodeError:
                            break
            i = text.find(open_c, i + 1)
    return None


# --------------------------------------------------------------------------- #
# Public analyze_* surface
# --------------------------------------------------------------------------- #


def analyze_image(
    image_path: str,
    *,
    prompt: str = "",
    mode: str = "describe",
    history_kind: str = "image",
) -> dict:
    """
    Single-image analysis. Returns dict: {ok, mode, text, json, path, model}.
    """
    resolved = _expand_user_path(image_path)
    if not resolved or not os.path.isfile(resolved):
        return {"ok": False, "mode": mode, "text": f"Image not found: {image_path}",
                "json": None, "path": image_path, "model": _vision_model()}

    mode_key = (mode or "describe").lower().strip()
    base_prompt = _MODE_PROMPTS.get(mode_key, _MODE_PROMPTS["describe"])
    user_prompt = (prompt or "").strip()
    if user_prompt:
        full_prompt = f"{base_prompt}\n\nUser instruction: {user_prompt}"
    else:
        full_prompt = base_prompt

    result = _run_vision([resolved], prompt=full_prompt, mode=mode_key)
    if result.get("ok"):
        remember_last_image(resolved, kind=history_kind)
    return {
        "ok": result.get("ok", False),
        "mode": mode_key,
        "text": result.get("text") or result.get("error") or "",
        "json": result.get("json"),
        "path": resolved,
        "model": _vision_model(),
        "error": result.get("error"),
    }


def analyze_images(
    image_paths: Sequence[str],
    *,
    prompt: str = "",
    mode: str = "compare",
) -> dict:
    """Multi-image analysis. Default mode 'compare' diffs two or more images."""
    resolved_paths: list[str] = []
    for p in image_paths:
        r = _expand_user_path(p)
        if not r or not os.path.isfile(r):
            return {"ok": False, "text": f"Image not found: {p}", "json": None, "paths": list(image_paths)}
        resolved_paths.append(r)

    user_prompt = (prompt or "").strip()
    if mode == "compare":
        base_prompt = (
            "Compare the following images in order. Call out the most important differences "
            "and similarities, infer what changed or what they mean together, and end with one "
            "concise takeaway. Keep under 8 sentences."
        )
    elif mode == "narrate":
        base_prompt = (
            "These images are frames captured in time order. Narrate what is happening as a "
            "short sequence of actions (under 6 sentences). Mention motion, posture changes, "
            "objects appearing or disappearing."
        )
    elif mode in _MODE_PROMPTS:
        base_prompt = _MODE_PROMPTS[mode]
    else:
        base_prompt = (
            "Analyze these images together and answer the user's question. "
            "If they appear to be a sequence, treat order as meaningful."
        )
    full_prompt = f"{base_prompt}\n\nUser instruction: {user_prompt}" if user_prompt else base_prompt

    result = _run_vision(resolved_paths, prompt=full_prompt, mode=mode)
    if result.get("ok") and resolved_paths:
        remember_last_image(resolved_paths[-1], kind="compare")
    return {
        "ok": result.get("ok", False),
        "mode": mode,
        "text": result.get("text") or result.get("error") or "",
        "json": result.get("json"),
        "paths": resolved_paths,
        "model": _vision_model(),
        "error": result.get("error"),
    }


# --------------------------------------------------------------------------- #
# Convenience wrappers (backwards-compatible APIs)
# --------------------------------------------------------------------------- #


def describe_image(image_path: str, *, prompt: str = "") -> str:
    """Describe an image (or answer a prompt about it). Returns voice-friendly text."""
    res = analyze_image(image_path, prompt=prompt, mode="describe", history_kind="image")
    if not res["ok"]:
        return res["text"] or res.get("error") or "I could not describe that image, Sir."
    return res["text"] or "I could not produce a description, Sir."


def describe_screen(*, prompt: str = "") -> str:
    ok, info = take_screenshot()
    if not ok:
        return info
    res = analyze_image(info, prompt=prompt, mode="describe", history_kind="screen")
    return res["text"] or res.get("error") or "I could not describe the screen, Sir."


def describe_webcam(*, prompt: str = "") -> str:
    ok, info = capture_webcam()
    if not ok:
        return info
    effective = (prompt or "").strip() or (
        "This photo was just captured from the user's webcam. Describe what you see — "
        "the person, surroundings, lighting, and anything notable — in 1–3 short sentences."
    )
    res = analyze_image(info, prompt=effective, mode="describe", history_kind="webcam")
    return res["text"] or res.get("error") or "I could not describe the photo, Sir."


def describe_clipboard_image(*, prompt: str = "") -> str:
    ok, info = capture_clipboard_image()
    if not ok:
        return info
    res = analyze_image(info, prompt=prompt, mode="describe", history_kind="clipboard")
    return res["text"] or res.get("error") or "I could not describe the clipboard image, Sir."


def ask_about_last_image(prompt: str) -> str:
    path, kind = get_last_image()
    if not path or not os.path.isfile(path):
        return ("I don't have a recent image to look at, Sir. Take a picture, share an image "
                "path, or copy one to the clipboard first.")
    label = {"screen": "the last screenshot", "webcam": "the last webcam photo",
             "clipboard": "the image you copied", "compare": "the last comparison",
             "image": "the last image"}.get(kind, "the last image")
    effective = (prompt or "").strip() or f"Tell me more about {label}."
    res = analyze_image(path, prompt=effective, mode="describe", history_kind=kind or "image")
    return res["text"] or res.get("error") or "I could not answer about that image, Sir."


def describe_webcam_motion(prompt: str = "", *, frames: int = 3, interval_s: float = 0.6) -> str:
    """Take a burst of webcam frames and describe the action across them."""
    ok, info = capture_webcam_burst(frames, interval_s)
    if not ok:
        return info  # error string
    assert isinstance(info, list)
    res = analyze_images(info, prompt=prompt, mode="narrate")
    return res["text"] or res.get("error") or "I could not analyze the burst, Sir."


# --------------------------------------------------------------------------- #
# Specialized helpers
# --------------------------------------------------------------------------- #


def extract_text_from_image(image_path: str, *, prefer_local: bool = False) -> dict:
    """
    Returns dict with keys: ok, text, blocks, language, source.
    Tries Tesseract first if ``prefer_local`` is True and pytesseract is installed,
    otherwise uses the vision model (more accurate but uses the API).
    """
    resolved = _expand_user_path(image_path)
    if not resolved or not os.path.isfile(resolved):
        return {"ok": False, "text": f"Image not found: {image_path}", "blocks": [],
                "language": None, "source": None}

    if prefer_local:
        try:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore

            txt = pytesseract.image_to_string(Image.open(resolved)).strip()
            if txt:
                return {"ok": True, "text": txt, "blocks": [], "language": None, "source": "tesseract"}
        except Exception:
            pass

    res = analyze_image(resolved, mode="ocr")
    data = res.get("json") or {}
    text = (data.get("text") if isinstance(data, dict) else None) or res.get("text", "")
    blocks = data.get("blocks") if isinstance(data, dict) else []
    language = data.get("language") if isinstance(data, dict) else None
    return {
        "ok": res.get("ok", False),
        "text": text,
        "blocks": blocks or [],
        "language": language,
        "source": "vision-model",
    }


def detect_objects(image_path: str) -> dict:
    """Returns dict: {ok, objects: [{label, confidence, bbox}], path}."""
    res = analyze_image(image_path, mode="objects")
    data = res.get("json") or {}
    objects = data.get("objects") if isinstance(data, dict) else []
    return {"ok": res.get("ok", False), "objects": objects or [], "path": res.get("path"),
            "error": res.get("error")}


def structured_analysis(image_path: str, *, prompt: str = "") -> dict:
    """Returns the full structured JSON dict (see _MODE_PROMPTS['structured'])."""
    res = analyze_image(image_path, prompt=prompt, mode="structured")
    data = res.get("json")
    if not isinstance(data, dict):
        data = {}
    data.setdefault("summary", res.get("text", ""))
    data["_path"] = res.get("path")
    data["_ok"] = res.get("ok", False)
    return data


def compare_images(image_paths: Sequence[str], *, prompt: str = "") -> str:
    """Voice-friendly diff/compare across 2+ images."""
    if len(image_paths) < 2:
        return "I need at least two images to compare, Sir."
    res = analyze_images(image_paths, prompt=prompt, mode="compare")
    return res["text"] or res.get("error") or "I could not compare those images, Sir."


# --------------------------------------------------------------------------- #
# PDF support
# --------------------------------------------------------------------------- #


def _pdf_rasterize(pdf_path: str, pages: Optional[Sequence[int]] = None,
                   dpi: int = 144) -> tuple[bool, list[str] | str]:
    resolved = _expand_user_path(pdf_path)
    if not resolved or not os.path.isfile(resolved):
        return False, f"PDF not found: {pdf_path}"
    try:
        import fitz  # type: ignore  # PyMuPDF
    except ImportError:
        return False, "Install PyMuPDF for PDF support: pip install pymupdf"

    out_paths: list[str] = []
    try:
        doc = fitz.open(resolved)
    except Exception as exc:  # noqa: BLE001
        return False, f"Failed to open PDF: {exc}"
    try:
        total = doc.page_count
        page_list = list(pages) if pages else list(range(min(total, 6)))  # cap default to 6 pages
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        ts = int(time.time() * 1000)
        for idx, pno in enumerate(page_list):
            if pno < 0 or pno >= total:
                continue
            page = doc.load_page(pno)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            target = Path(tempfile.gettempdir()) / f"jarvis_pdf_{ts}_p{pno + 1}.png"
            pix.save(str(target))
            out_paths.append(str(target))
            if idx >= 11:  # absolute safety cap
                break
    finally:
        doc.close()
    if not out_paths:
        return False, "No PDF pages rasterized."
    return True, out_paths


def analyze_pdf(pdf_path: str, *, prompt: str = "", pages: Optional[Sequence[int]] = None) -> str:
    """Rasterize selected PDF pages and analyze them together."""
    ok, info = _pdf_rasterize(pdf_path, pages=pages)
    if not ok:
        return info  # error string
    assert isinstance(info, list)
    if len(info) == 1:
        res = analyze_image(info[0], prompt=prompt, mode="describe", history_kind="pdf")
        return res["text"] or res.get("error") or "I could not analyze that PDF page, Sir."
    res = analyze_images(info, prompt=prompt or "Summarize the document across these pages.",
                         mode="describe")
    return res["text"] or res.get("error") or "I could not analyze that PDF, Sir."


# --------------------------------------------------------------------------- #
# Smart router
# --------------------------------------------------------------------------- #


def analyze_target(target: str, *, prompt: str = "", mode: str = "describe") -> str:
    """
    Smart router. ``target`` may be:
      - a local file path (image or PDF)
      - an http(s) URL
      - 'screen' | 'camera' | 'webcam' | 'clipboard' | 'last' | 'download'
      - 'pdf:<path>' to force PDF treatment
    """
    t = (target or "").strip()
    low = t.lower()
    if low in ("screen", "desktop"):
        return describe_screen(prompt=prompt)
    if low in ("camera", "webcam", "selfie"):
        return describe_webcam(prompt=prompt)
    if low in ("clipboard", "paste"):
        return describe_clipboard_image(prompt=prompt)
    if low in ("last", "latest", "previous"):
        return ask_about_last_image(prompt or "")
    if low in ("download", "downloads", "recent"):
        recent = find_recent_image()
        if not recent:
            return "I could not find a recent image, Sir."
        res = analyze_image(recent, prompt=prompt, mode=mode, history_kind="download")
        return res["text"] or res.get("error") or "I could not analyze that file, Sir."

    if low.startswith("pdf:"):
        return analyze_pdf(t[4:], prompt=prompt)

    if _looks_like_url(t):
        ok, info = fetch_url_to_temp(t)
        if not ok:
            return info
        if info.lower().endswith(".pdf"):
            return analyze_pdf(info, prompt=prompt)
        res = analyze_image(info, prompt=prompt, mode=mode, history_kind="url")
        return res["text"] or res.get("error") or "I could not analyze that URL, Sir."

    resolved = _expand_user_path(t)
    if resolved and os.path.isfile(resolved):
        if resolved.lower().endswith(".pdf"):
            return analyze_pdf(resolved, prompt=prompt)
        res = analyze_image(resolved, prompt=prompt, mode=mode, history_kind="image")
        return res["text"] or res.get("error") or "I could not analyze that image, Sir."

    # Last resort: maybe a history reference.
    hist = _resolve_history_reference(t)
    if hist:
        res = analyze_image(hist, prompt=prompt, mode=mode, history_kind="image")
        return res["text"] or res.get("error") or "I could not analyze that image, Sir."

    return f"I could not resolve '{target}' to an image, Sir."


# --------------------------------------------------------------------------- #
# Annotation overlay (bbox rendering)
# --------------------------------------------------------------------------- #


def annotate_image(image_path: str, boxes: Iterable[dict], *, out_path: Optional[str] = None) -> Optional[str]:
    """
    Draw labelled rectangles onto a copy of the image. ``boxes`` items:
        {"label": str, "bbox": [x, y, w, h], "confidence": float}
    bbox is normalized [0,1]. Returns path to the annotated file (None on failure).
    """
    if not _has_pillow():
        return None
    resolved = _expand_user_path(image_path)
    if not resolved or not os.path.isfile(resolved):
        return None
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
        _ensure_pillow_heif()
        img = Image.open(resolved).convert("RGB")
    except Exception:
        return None
    w, h = img.size
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(
            "/System/Library/Fonts/Supplemental/Arial.ttf" if sys.platform == "darwin"
            else "DejaVuSans.ttf", max(14, w // 60),
        )
    except Exception:
        font = ImageFont.load_default()

    for b in boxes:
        try:
            label = str(b.get("label", "?"))
            x, y, bw, bh = b.get("bbox", [0, 0, 0, 0])
            conf = float(b.get("confidence", 0.0) or 0.0)
        except Exception:
            continue
        x0, y0 = int(x * w), int(y * h)
        x1, y1 = int((x + bw) * w), int((y + bh) * h)
        if x1 <= x0 or y1 <= y0:
            continue
        draw.rectangle([x0, y0, x1, y1], outline=(255, 64, 64), width=3)
        caption = f"{label} {conf:.0%}" if conf else label
        try:
            tw = draw.textlength(caption, font=font)
            th = (font.size if hasattr(font, "size") else 14) + 4
            draw.rectangle([x0, y0 - th, x0 + tw + 8, y0], fill=(255, 64, 64))
            draw.text((x0 + 4, y0 - th), caption, fill=(255, 255, 255), font=font)
        except Exception:
            draw.text((x0 + 2, y0 + 2), caption, fill=(255, 255, 255), font=font)

    target = out_path or str(Path(tempfile.gettempdir()) / f"jarvis_annotated_{int(time.time()*1000)}.png")
    try:
        img.save(target, "PNG")
    except Exception:
        return None
    return target


# --------------------------------------------------------------------------- #
# Image generation (text → image)
# --------------------------------------------------------------------------- #


def generate_image(prompt: str, *, size: str = "1024x1024", out_path: Optional[str] = None,
                   quality: str = "high", n: int = 1) -> dict:
    """
    Generate an image from a text prompt. Saves to disk; returns dict with
    {ok, path, paths, model, error}.
    """
    if not (prompt or "").strip():
        return {"ok": False, "path": None, "paths": [], "model": _image_gen_model(),
                "error": "Empty prompt."}
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        return {"ok": False, "path": None, "paths": [], "model": _image_gen_model(),
                "error": "OPENAI_API_KEY not set."}

    client = _openai_client()
    if client is None:
        return {"ok": False, "path": None, "paths": [], "model": _image_gen_model(),
                "error": "OpenAI client unavailable."}

    n = max(1, min(int(n or 1), 4))
    model = _image_gen_model()
    try:
        # `quality` accepts auto/low/medium/high for gpt-image-1; standard/hd for dall-e-3.
        kwargs: dict[str, Any] = {"model": model, "prompt": prompt, "size": size, "n": n}
        if "gpt-image" in model:
            kwargs["quality"] = quality
        elif "dall-e-3" in model:
            kwargs["quality"] = "hd" if quality in ("hd", "high") else "standard"
        response = client.images.generate(**kwargs)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "path": None, "paths": [], "model": model, "error": f"generation failed: {exc}"}

    paths: list[str] = []
    ts = int(time.time() * 1000)
    for i, item in enumerate(response.data or []):
        b64 = getattr(item, "b64_json", None)
        url = getattr(item, "url", None)
        target = out_path if (n == 1 and out_path) else str(
            Path(tempfile.gettempdir()) / f"jarvis_gen_{ts}_{i}.png"
        )
        try:
            if b64:
                with open(target, "wb") as f:
                    f.write(base64.b64decode(b64))
            elif url:
                import requests  # type: ignore

                r = requests.get(url, timeout=60)
                r.raise_for_status()
                with open(target, "wb") as f:
                    f.write(r.content)
            else:
                continue
            paths.append(target)
        except Exception:  # noqa: BLE001
            continue

    if not paths:
        return {"ok": False, "path": None, "paths": [], "model": model, "error": "No image data returned."}
    if paths:
        remember_last_image(paths[0], kind="generated", label=prompt[:120])
    return {"ok": True, "path": paths[0], "paths": paths, "model": model, "error": None}


# --------------------------------------------------------------------------- #
# Public surface
# --------------------------------------------------------------------------- #


__all__ = [
    "analyze_image",
    "analyze_images",
    "analyze_pdf",
    "analyze_target",
    "annotate_image",
    "ask_about_last_image",
    "capture_clipboard_image",
    "capture_webcam",
    "capture_webcam_burst",
    "compare_images",
    "describe_clipboard_image",
    "describe_image",
    "describe_screen",
    "describe_webcam",
    "describe_webcam_motion",
    "detect_objects",
    "extract_text_from_image",
    "fetch_url_to_temp",
    "find_recent_image",
    "generate_image",
    "get_last_image",
    "image_history",
    "remember_last_image",
    "structured_analysis",
    "take_screenshot",
]
