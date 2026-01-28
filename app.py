"""Web API for video stutter analysis."""

import tempfile
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse

from main import analyze_frametimes, to_json

app = FastAPI(
    title="Video Stutter Analyzer",
    description="Analyze frame times and detect stutters in game recordings",
)

HTML_PAGE = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Video Stutter Analyzer</title>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background: #1a1a2e;
            color: #eee;
        }
        h1 { color: #00d9ff; }
        .upload-area {
            border: 2px dashed #444;
            border-radius: 12px;
            padding: 40px;
            text-align: center;
            margin: 20px 0;
            transition: all 0.3s;
        }
        .upload-area:hover, .upload-area.dragover {
            border-color: #00d9ff;
            background: rgba(0, 217, 255, 0.1);
        }
        input[type="file"] { display: none; }
        .btn {
            background: #00d9ff;
            color: #1a1a2e;
            border: none;
            padding: 12px 24px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 16px;
            font-weight: bold;
        }
        .btn:hover { background: #00b8d9; }
        .btn:disabled { background: #555; cursor: not-allowed; }
        #result {
            background: #16213e;
            border-radius: 12px;
            padding: 20px;
            margin-top: 20px;
            display: none;
        }
        .score {
            font-size: 48px;
            font-weight: bold;
            text-align: center;
            margin: 20px 0;
        }
        .score.good { color: #00ff88; }
        .score.fair { color: #ffaa00; }
        .score.poor { color: #ff4444; }
        .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
        .stat-card {
            background: #1a1a2e;
            padding: 15px;
            border-radius: 8px;
        }
        .stat-label { color: #888; font-size: 14px; }
        .stat-value { font-size: 24px; font-weight: bold; margin-top: 5px; }
        .loading { display: none; text-align: center; padding: 40px; }
        .spinner {
            border: 4px solid #333;
            border-top: 4px solid #00d9ff;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
        }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .stutters { margin-top: 20px; }
        .stutter-item {
            background: #1a1a2e;
            padding: 10px 15px;
            border-radius: 6px;
            margin: 8px 0;
            border-left: 3px solid #ff4444;
        }
    </style>
</head>
<body>
    <h1>Video Stutter Analyzer</h1>
    <p>Upload a game recording to analyze frame times and detect stutters.</p>

    <div class="upload-area" id="dropZone">
        <p>Drag & drop video file here, or</p>
        <input type="file" id="fileInput" accept="video/*">
        <button class="btn" onclick="document.getElementById('fileInput').click()">Select File</button>
    </div>

    <div class="loading" id="loading">
        <div class="spinner"></div>
        <p>Analyzing video... This may take a while for large files.</p>
    </div>

    <div id="result"></div>

    <script>
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');
        const loading = document.getElementById('loading');
        const result = document.getElementById('result');

        ['dragenter', 'dragover'].forEach(e => {
            dropZone.addEventListener(e, (ev) => { ev.preventDefault(); dropZone.classList.add('dragover'); });
        });
        ['dragleave', 'drop'].forEach(e => {
            dropZone.addEventListener(e, (ev) => { ev.preventDefault(); dropZone.classList.remove('dragover'); });
        });
        dropZone.addEventListener('drop', (e) => { if (e.dataTransfer.files.length) analyzeFile(e.dataTransfer.files[0]); });
        fileInput.addEventListener('change', (e) => { if (e.target.files.length) analyzeFile(e.target.files[0]); });

        async function analyzeFile(file) {
            dropZone.style.display = 'none';
            loading.style.display = 'block';
            result.style.display = 'none';

            const formData = new FormData();
            formData.append('file', file);

            try {
                const resp = await fetch('/analyze', { method: 'POST', body: formData });
                const data = await resp.json();
                if (!resp.ok) throw new Error(data.detail || 'Analysis failed');
                showResult(data);
            } catch (err) {
                alert('Error: ' + err.message);
                dropZone.style.display = 'block';
            } finally {
                loading.style.display = 'none';
            }
        }

        function showResult(data) {
            const score = data.smoothness_score;
            const scoreClass = score >= 80 ? 'good' : score >= 50 ? 'fair' : 'poor';
            const avgFps = (1000 / data.frame_times_ms.average).toFixed(1);
            const lowFps = (1000 / data.frame_times_ms.one_percent_low).toFixed(1);

            let stutterHtml = '';
            if (data.stutter_events.length > 0) {
                stutterHtml = '<div class="stutters"><h3>Stutter Events</h3>';
                data.stutter_events.slice(0, 10).forEach(s => {
                    stutterHtml += `<div class="stutter-item">@ ${s.timestamp.toFixed(2)}s - ${s.frametime_ms.toFixed(0)}ms (${s.duplicate_count} dup)</div>`;
                });
                if (data.stutter_events.length > 10) stutterHtml += `<p>...and ${data.stutter_events.length - 10} more</p>`;
                stutterHtml += '</div>';
            }

            result.innerHTML = `
                <div class="score ${scoreClass}">${score.toFixed(1)}/100</div>
                <div class="stats">
                    <div class="stat-card">
                        <div class="stat-label">Average FPS</div>
                        <div class="stat-value">${avgFps}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">1% Low FPS</div>
                        <div class="stat-value">${lowFps}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Duplicate Frames</div>
                        <div class="stat-value">${data.duplicate_detection.duplicate_frames} (${(data.duplicate_detection.duplicate_ratio * 100).toFixed(1)}%)</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Stutters Detected</div>
                        <div class="stat-value">${data.stutter_events.length}</div>
                    </div>
                </div>
                ${stutterHtml}
                <p style="margin-top:20px;text-align:center;">
                    <button class="btn" onclick="location.reload()">Analyze Another</button>
                </p>
            `;
            result.style.display = 'block';
        }
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def root():
    return HTML_PAGE


@app.get("/api")
def api_info():
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
