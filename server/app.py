import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="ClipCut")

ALLOWED = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

MAX_CLIP_SECONDS = int(os.getenv("MAX_CLIP_SECONDS", "900"))  # 15 min default
YT_RE = re.compile(
    r"^https?://((www|m|music)\.)?(youtube\.com|youtu\.be)/", re.I
)


class ClipReq(BaseModel):
    url: str
    start: float
    end: float
    quality: str = "720"  # 360 / 480 / 720 / 1080 / audio


class InfoReq(BaseModel):
    url: str


def _check_url(url: str):
    if not YT_RE.match(url.strip()):
        raise HTTPException(400, "Please paste a valid YouTube link.")


def _ytdlp_base():
    cmd = ["yt-dlp", "--no-playlist", "--no-warnings"]
    cookies = os.getenv("YT_COOKIES_FILE")
    if cookies and Path(cookies).exists():
        cmd += ["--cookies", cookies]
    return cmd


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/info")
def info(req: InfoReq):
    _check_url(req.url)
    cmd = _ytdlp_base() + [
        "--skip-download",
        "--print", "%(title)s\n%(duration)s\n%(thumbnail)s",
        req.url,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "YouTube took too long to respond.")
    if out.returncode != 0:
        raise HTTPException(422, "Couldn't read that video. It may be private or blocked.")
    lines = out.stdout.strip().split("\n")
    title = lines[0] if lines else "video"
    try:
        duration = int(float(lines[1]))
    except Exception:
        duration = 0
    thumb = lines[2] if len(lines) > 2 else ""
    return {"title": title, "duration": duration, "thumbnail": thumb}


def _cleanup(path: str):
    shutil.rmtree(path, ignore_errors=True)


@app.post("/api/clip")
def clip(req: ClipReq, bg: BackgroundTasks):
    _check_url(req.url)
    if req.start < 0 or req.end <= req.start:
        raise HTTPException(400, "End time must be after start time.")
    if req.end - req.start > MAX_CLIP_SECONDS:
        raise HTTPException(400, f"Clips are limited to {MAX_CLIP_SECONDS // 60} minutes.")

    work = tempfile.mkdtemp(prefix="clip_")
    name = uuid.uuid4().hex[:8]
    out_tpl = os.path.join(work, f"{name}.%(ext)s")
    section = f"*{req.start:.2f}-{req.end:.2f}"

    cmd = _ytdlp_base() + [
        # Only the requested range is fetched via HTTP range requests (ffmpeg)
        "--download-sections", section,
        "--force-keyframes-at-cuts",
        "-o", out_tpl,
    ]

    if req.quality == "audio":
        cmd += ["-f", "bestaudio", "-x", "--audio-format", "mp3"]
    else:
        h = int(req.quality) if req.quality.isdigit() else 720
        cmd += [
            "-f", f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/b[height<={h}][ext=mp4]/b[height<={h}]",
            "--merge-output-format", "mp4",
        ]
    cmd.append(req.url)

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        _cleanup(work)
        raise HTTPException(504, "Clip took too long. Try a shorter range.")

    files = list(Path(work).glob(f"{name}.*"))
    if res.returncode != 0 or not files:
        _cleanup(work)
        raise HTTPException(422, "Download failed. YouTube may be blocking the server.")

    f = files[0]
    bg.add_task(_cleanup, work)
    return FileResponse(
        f,
        filename=f"clip_{int(req.start)}-{int(req.end)}{f.suffix}",
        media_type="application/octet-stream",
    )
