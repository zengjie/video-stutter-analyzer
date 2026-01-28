"""Web API for video stutter analysis."""

import tempfile
import os
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse

from main import analyze_frametimes, to_json

app = FastAPI(
    title="Video Stutter Analyzer",
    description="Analyze frame times and detect stutters in game recordings",
)

# Store uploaded videos temporarily
VIDEO_CACHE = {}  # video_id -> file_path

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
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background: #1a1a2e;
            color: #eee;
        }
        h1 { color: #00d9ff; margin-bottom: 10px; }
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
        .btn-sm { padding: 8px 16px; font-size: 14px; }
        #result { display: none; }
        .video-container {
            position: relative;
            background: #000;
            border-radius: 12px;
            overflow: hidden;
            margin: 20px 0;
        }
        .video-container.stutter video { outline: 4px solid #ff4444; }
        video { width: 100%; display: block; }
        .timeline {
            height: 32px;
            background: #222;
            position: relative;
            cursor: pointer;
        }
        .timeline-progress {
            position: absolute;
            top: 0;
            left: 0;
            height: 100%;
            background: rgba(0, 217, 255, 0.3);
            pointer-events: none;
        }
        .timeline-marker {
            position: absolute;
            top: 0;
            height: 100%;
            background: #ff4444;
            opacity: 0.8;
            min-width: 3px;
        }
        .timeline-marker:hover { opacity: 1; }
        .stutter-label {
            position: absolute;
            top: 8px;
            right: 10px;
            background: #ff4444;
            color: white;
            padding: 4px 12px;
            border-radius: 4px;
            font-weight: bold;
            display: none;
        }
        .video-container.stutter .stutter-label { display: block; }
        .score-bar {
            display: flex;
            align-items: center;
            gap: 20px;
            background: #16213e;
            padding: 15px 20px;
            border-radius: 12px;
            margin: 20px 0;
        }
        .score {
            font-size: 36px;
            font-weight: bold;
            min-width: 120px;
        }
        .score.good { color: #00ff88; }
        .score.fair { color: #ffaa00; }
        .score.poor { color: #ff4444; }
        .score-details { flex: 1; display: flex; gap: 20px; flex-wrap: wrap; }
        .score-item { text-align: center; }
        .score-item-value { font-size: 20px; font-weight: bold; }
        .score-item-label { font-size: 12px; color: #888; }
        .stutters-list {
            background: #16213e;
            border-radius: 12px;
            padding: 15px;
            margin: 20px 0;
            max-height: 200px;
            overflow-y: auto;
        }
        .stutter-item {
            display: flex;
            justify-content: space-between;
            padding: 8px 12px;
            margin: 4px 0;
            background: #1a1a2e;
            border-radius: 6px;
            cursor: pointer;
            border-left: 3px solid #ff4444;
        }
        .stutter-item:hover { background: #252550; }
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
        .controls { display: flex; gap: 10px; margin: 15px 0; align-items: center; flex-wrap: wrap; }
        .frame-info {
            font-family: monospace;
            background: #1a1a2e;
            padding: 8px 12px;
            border-radius: 6px;
            width: 220px;
            text-align: center;
        }
    </style>
</head>
<body>
    <h1>Video Stutter Analyzer</h1>
    <p>Upload a game recording to detect frame stutters.</p>

    <div class="upload-area" id="dropZone">
        <p>Drag & drop video here, or</p>
        <input type="file" id="fileInput" accept="video/*">
        <button class="btn" onclick="document.getElementById('fileInput').click()">Select File</button>
    </div>

    <div class="loading" id="loading">
        <div class="spinner"></div>
        <p>Analyzing video frames...</p>
    </div>

    <div id="result">
        <div class="video-container" id="videoContainer">
            <video id="video" controls></video>
            <div class="stutter-label" id="stutterLabel">STUTTER</div>
            <div class="timeline" id="timeline">
                <div class="timeline-progress" id="timelineProgress"></div>
            </div>
        </div>

        <div class="controls">
            <button class="btn btn-sm" id="prevFrame" title="Previous Frame (,)">&lt; Frame</button>
            <button class="btn btn-sm" id="nextFrame" title="Next Frame (.)">Frame &gt;</button>
            <span class="frame-info" id="frameInfo">Frame: --</span>
            <div style="border-left: 1px solid #444; height: 24px; margin: 0 10px;"></div>
            <button class="btn btn-sm" id="prevStutter">Prev Stutter</button>
            <button class="btn btn-sm" id="nextStutter">Next Stutter</button>
            <button class="btn btn-sm" onclick="location.reload()">New</button>
        </div>

        <div class="score-bar">
            <div class="score" id="scoreValue">--</div>
            <div class="score-details">
                <div class="score-item"><div class="score-item-value" id="avgFps">--</div><div class="score-item-label">Avg FPS</div></div>
                <div class="score-item"><div class="score-item-value" id="lowFps">--</div><div class="score-item-label">1% Low</div></div>
                <div class="score-item"><div class="score-item-value" id="dupFrames">--</div><div class="score-item-label">Dup Frames</div></div>
                <div class="score-item"><div class="score-item-value" id="stutterCount">--</div><div class="score-item-label">Stutters</div></div>
            </div>
        </div>

        <div class="stutters-list" id="stuttersList"></div>
    </div>

    <script>
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');
        const loading = document.getElementById('loading');
        const result = document.getElementById('result');
        const video = document.getElementById('video');
        const videoContainer = document.getElementById('videoContainer');
        const timeline = document.getElementById('timeline');
        const timelineProgress = document.getElementById('timelineProgress');
        const stutterLabel = document.getElementById('stutterLabel');

        let analysisData = null;
        let stutterIndex = -1;

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
                analysisData = data;
                showResult(data);
            } catch (err) {
                alert('Error: ' + err.message);
                dropZone.style.display = 'block';
            } finally {
                loading.style.display = 'none';
            }
        }

        function showResult(data) {
            // Set video source
            video.src = `/video/${data.video_id}`;

            // Update score
            const score = data.smoothness_score;
            const scoreEl = document.getElementById('scoreValue');
            scoreEl.textContent = score.toFixed(1);
            scoreEl.className = 'score ' + (score >= 80 ? 'good' : score >= 50 ? 'fair' : 'poor');

            // Update stats
            document.getElementById('avgFps').textContent = (1000 / data.frame_times_ms.average).toFixed(1);
            document.getElementById('lowFps').textContent = (1000 / data.frame_times_ms.one_percent_low).toFixed(1);
            document.getElementById('dupFrames').textContent = data.duplicate_detection.duplicate_frames;
            document.getElementById('stutterCount').textContent = data.stutter_events.length;

            // Add stutter markers to timeline
            video.addEventListener('loadedmetadata', () => {
                const duration = video.duration;
                data.stutter_events.forEach((s, i) => {
                    const marker = document.createElement('div');
                    marker.className = 'timeline-marker';
                    marker.style.left = (s.timestamp / duration * 100) + '%';
                    marker.style.width = Math.max(3, s.duplicate_count * 2) + 'px';
                    marker.title = `@ ${s.timestamp.toFixed(2)}s - ${s.frametime_ms.toFixed(0)}ms`;
                    marker.onclick = (e) => { e.stopPropagation(); video.currentTime = s.timestamp; };
                    timeline.appendChild(marker);
                });
            });

            // Update progress bar
            video.addEventListener('timeupdate', () => {
                const pct = (video.currentTime / video.duration) * 100;
                timelineProgress.style.width = pct + '%';

                // Check if in stutter zone
                const inStutter = data.stutter_events.some(s =>
                    video.currentTime >= s.timestamp && video.currentTime <= s.timestamp + s.duplicate_count / data.fps
                );
                videoContainer.classList.toggle('stutter', inStutter);
                stutterLabel.textContent = inStutter ? 'STUTTER' : '';
            });

            // Timeline click to seek
            timeline.addEventListener('click', (e) => {
                const rect = timeline.getBoundingClientRect();
                const pct = (e.clientX - rect.left) / rect.width;
                video.currentTime = pct * video.duration;
            });

            // Stutter list
            const listEl = document.getElementById('stuttersList');
            if (data.stutter_events.length === 0) {
                listEl.innerHTML = '<p style="text-align:center;color:#888;">No stutters detected!</p>';
            } else {
                listEl.innerHTML = data.stutter_events.map((s, i) =>
                    `<div class="stutter-item" onclick="jumpToStutter(${i})">
                        <span>#${i+1} @ ${s.timestamp.toFixed(2)}s</span>
                        <span>${s.frametime_ms.toFixed(0)}ms (${s.duplicate_count} dup)</span>
                    </div>`
                ).join('');
            }

            result.style.display = 'block';
        }

        function jumpToStutter(index) {
            if (!analysisData || !analysisData.stutter_events[index]) return;
            stutterIndex = index;
            video.currentTime = analysisData.stutter_events[index].timestamp;
        }

        document.getElementById('prevStutter').onclick = () => {
            if (!analysisData || analysisData.stutter_events.length === 0) return;
            stutterIndex = stutterIndex <= 0 ? analysisData.stutter_events.length - 1 : stutterIndex - 1;
            jumpToStutter(stutterIndex);
        };

        document.getElementById('nextStutter').onclick = () => {
            if (!analysisData || analysisData.stutter_events.length === 0) return;
            stutterIndex = stutterIndex >= analysisData.stutter_events.length - 1 ? 0 : stutterIndex + 1;
            jumpToStutter(stutterIndex);
        };

        // Frame stepping
        function getFrameDuration() {
            return analysisData ? 1 / analysisData.fps : 1/30;
        }

        function stepFrame(delta) {
            video.pause();
            video.currentTime = Math.max(0, Math.min(video.duration, video.currentTime + delta * getFrameDuration()));
        }

        function updateFrameInfo() {
            if (!analysisData) return;
            const frame = Math.round(video.currentTime * analysisData.fps);
            const time = video.currentTime.toFixed(3);
            const inStutter = analysisData.stutter_events.find(s =>
                video.currentTime >= s.timestamp - 0.01 && video.currentTime <= s.timestamp + s.duplicate_count / analysisData.fps + 0.01
            );
            document.getElementById('frameInfo').innerHTML = inStutter
                ? `<span style="color:#ff4444">Frame: ${frame} | ${time}s | STUTTER</span>`
                : `Frame: ${frame} | ${time}s`;
        }

        video.addEventListener('timeupdate', updateFrameInfo);
        video.addEventListener('seeked', updateFrameInfo);

        document.getElementById('prevFrame').onclick = () => stepFrame(-1);
        document.getElementById('nextFrame').onclick = () => stepFrame(1);

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.target.tagName === 'INPUT') return;
            if (e.key === ',') { stepFrame(-1); e.preventDefault(); }
            if (e.key === '.') { stepFrame(1); e.preventDefault(); }
            if (e.key === '[') { document.getElementById('prevStutter').click(); e.preventDefault(); }
            if (e.key === ']') { document.getElementById('nextStutter').click(); e.preventDefault(); }
            if (e.key === ' ') { video.paused ? video.play() : video.pause(); e.preventDefault(); }
        });
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

    # Save video with unique ID
    video_id = str(uuid.uuid4())[:8]
    tmp_path = f"/tmp/video_{video_id}{suffix}"

    with open(tmp_path, "wb") as f:
        f.write(await file.read())

    VIDEO_CACHE[video_id] = tmp_path

    try:
        stats, stutters = analyze_frametimes(tmp_path)
        result = to_json(stats, stutters, file.filename)
        result["video_id"] = video_id
        return JSONResponse(result)
    except RuntimeError as e:
        os.unlink(tmp_path)
        VIDEO_CACHE.pop(video_id, None)
        raise HTTPException(500, str(e))


@app.get("/video/{video_id}")
async def get_video(video_id: str):
    """Serve uploaded video for playback."""
    if video_id not in VIDEO_CACHE:
        raise HTTPException(404, "Video not found")
    return FileResponse(VIDEO_CACHE[video_id], media_type="video/mp4")


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
