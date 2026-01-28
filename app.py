"""Web API for video stutter analysis."""

import tempfile
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

from main import analyze_frametimes, to_json, FrameTimeStats, StutterEvent

app = FastAPI(
    title="Video Stutter Analyzer",
    description="Analyze frame times and detect stutters in game recordings",
)


@app.get("/")
def root():
    return {
        "service": "Video Stutter Analyzer",
        "endpoints": {
            "POST /analyze": "Upload video file for analysis",
            "POST /analyze-url": "Analyze video from URL",
            "GET /health": "Health check",
        }
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze")
async def analyze_upload(file: UploadFile = File(...)):
    """Analyze uploaded video file."""
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    suffix = Path(file.filename).suffix
    if suffix.lower() not in [".mp4", ".mov", ".avi", ".mkv", ".webm"]:
        raise HTTPException(400, f"Unsupported format: {suffix}")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        stats, stutters = analyze_frametimes(tmp_path)
        result = to_json(stats, stutters, file.filename)
        return JSONResponse(result)
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    finally:
        os.unlink(tmp_path)


@app.post("/analyze-url")
async def analyze_url(url: str):
    """Analyze video from URL."""
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.RequestError as e:
        raise HTTPException(400, f"Failed to fetch URL: {e}")

    content_type = resp.headers.get("content-type", "")
    if "video" not in content_type and not url.endswith((".mp4", ".mov", ".avi", ".mkv", ".webm")):
        raise HTTPException(400, f"URL does not appear to be a video: {content_type}")

    suffix = ".mp4"
    for ext in [".mp4", ".mov", ".avi", ".mkv", ".webm"]:
        if url.endswith(ext):
            suffix = ext
            break

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(resp.content)
        tmp_path = tmp.name

    try:
        stats, stutters = analyze_frametimes(tmp_path)
        result = to_json(stats, stutters, url)
        return JSONResponse(result)
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    finally:
        os.unlink(tmp_path)
