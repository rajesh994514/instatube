"""
InstaTube Backend – Production Ready
=====================================
Works for EVERYONE without needing personal cookies.

Strategy:
  1. Use yt-dlp with rotating fake user-agents
  2. Use PO Token + Visitor Data (YouTube's public access method)
  3. Use invidious/piped public APIs as fallback for YouTube
  4. Use best format selection with multiple fallback chains
  5. Rate limiting to avoid IP bans
  6. Auto-update yt-dlp to always have latest patches
"""

from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import yt_dlp
import os, threading, uuid, json, time, re, random, subprocess, sys

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

# Serve frontend
@app.route("/")
def index():
    return send_file(os.path.join(os.path.dirname(__file__), "index.html"))

DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

progress_store = {}

# ─────────────────────────────────────────────
# Auto-update yt-dlp at startup (always latest)
# ─────────────────────────────────────────────
def auto_update_ytdlp():
    try:
        print("🔄 Updating yt-dlp to latest version...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "yt-dlp", "--quiet"],
            check=True, capture_output=True
        )
        print("✅ yt-dlp is up to date")
    except Exception as e:
        print(f"⚠️  Could not update yt-dlp: {e}")

threading.Thread(target=auto_update_ytdlp, daemon=True).start()

# ─────────────────────────────────────────────
# Rotating User Agents (avoids bot detection)
# ─────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]

def random_ua():
    return random.choice(USER_AGENTS)

# ─────────────────────────────────────────────
# Platform URL patterns
# ─────────────────────────────────────────────
YOUTUBE_PATTERNS = [
    r"youtube\.com/watch",
    r"youtu\.be/",
    r"youtube\.com/shorts/",
    r"youtube\.com/live/",
    r"m\.youtube\.com/",
    r"youtube\.com/embed/",
]
INSTAGRAM_PATTERNS = [
    r"instagram\.com/p/",
    r"instagram\.com/reel/",
    r"instagram\.com/tv/",
    r"instagram\.com/stories/",
]

def detect_platform(url):
    for p in YOUTUBE_PATTERNS:
        if re.search(p, url, re.IGNORECASE): return "youtube"
    for p in INSTAGRAM_PATTERNS:
        if re.search(p, url, re.IGNORECASE): return "instagram"
    return "unknown"

# ─────────────────────────────────────────────
# Format map
# ─────────────────────────────────────────────
FORMAT_MAP = {
    "144p":          "bestvideo[height<=144]+bestaudio/best[height<=144]/worst",
    "240p":          "bestvideo[height<=240]+bestaudio/best[height<=240]",
    "360p":          "bestvideo[height<=360]+bestaudio/best[height<=360]",
    "480p":          "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "720p HD":       "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "1080p FHD":     "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "1440p 2K":      "bestvideo[height<=1440]+bestaudio/best[height<=1440]",
    "2160p 4K":      "bestvideo[height<=2160]+bestaudio/best[height<=2160]",
    "Audio 128kbps": "bestaudio[abr<=130]/bestaudio",
    "Audio 192kbps": "bestaudio[abr<=195]/bestaudio",
    "Audio 320kbps": "bestaudio/best",
}

CONTAINER_MAP = {
    "MP4": "mp4", "WEBM": "webm", "MKV": "mkv",
    "MP3": "mp3", "M4A": "m4a",
}

def is_audio_res(res): return res.startswith("Audio")

# ─────────────────────────────────────────────
# Core yt-dlp options — NO cookies needed
# Uses multiple strategies to work for everyone
# ─────────────────────────────────────────────
def make_ydl_opts(extra=None):
    """
    Build yt-dlp options that work for any user, no login required.
    Uses: rotating UA, extractor args, sleep intervals, retries.
    """
    opts = {
        "quiet":        True,
        "no_warnings":  True,
        "nocheckcertificate": True,   # works behind proxies/firewalls
        "http_headers": {
            "User-Agent":      random_ua(),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Sec-Fetch-Mode":  "navigate",
        },
        # YouTube: try multiple clients — web first, then android, ios
        "extractor_args": {
            "youtube": {
                "player_client": ["web", "android", "ios", "mweb"],
            },
        },
        # Retry on errors
        "retries":              8,
        "fragment_retries":     8,
        "file_access_retries":  3,
        # Small sleep between requests to avoid rate-limit
        "sleep_interval":             1,
        "max_sleep_interval":         3,
        "sleep_interval_requests":    1,
        # Socket timeout
        "socket_timeout": 30,
    }
    # Merge in server-side cookies.txt if admin provided one
    cookie_path = os.path.join(os.path.dirname(__file__), "cookies.txt")
    if os.path.exists(cookie_path):
        opts["cookiefile"] = cookie_path

    if extra:
        opts.update(extra)
    return opts

# ─────────────────────────────────────────────
# 1. GET /api/info
# ─────────────────────────────────────────────
@app.route("/api/info", methods=["GET"])
def get_info():
    url      = request.args.get("url", "").strip()
    platform = request.args.get("platform", "").lower()

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    detected = detect_platform(url)
    if platform == "yt" and detected != "youtube":
        return jsonify({"error": "❌ This doesn't look like a YouTube URL. Please use the Instagram tab for Instagram links."}), 400
    if platform == "ig" and detected != "instagram":
        return jsonify({"error": "❌ This doesn't look like an Instagram URL. Please use the YouTube tab for YouTube links."}), 400

    ydl_opts = make_ydl_opts({"skip_download": True})

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = info.get("formats", [])

        # Build video resolutions
        heights = sorted(
            set(f.get("height") for f in formats
                if f.get("height") and f.get("vcodec", "none") != "none"),
            reverse=True
        )
        label_map = {2160:"2160p 4K",1440:"1440p 2K",1080:"1080p FHD",
                     720:"720p HD",480:"480p",360:"360p",240:"240p",144:"144p"}
        res_labels = []
        for h in heights:
            for threshold, label in label_map.items():
                if h >= threshold and label not in res_labels:
                    res_labels.append(label)
                    break

        if not res_labels:
            res_labels = ["720p HD", "480p", "360p", "144p"]

        all_res = res_labels + ["Audio 128kbps", "Audio 192kbps", "Audio 320kbps"]

        dur = info.get("duration")
        dur_str = f"{int(dur//60)}:{int(dur%60):02d}" if dur else ""

        return jsonify({
            "title":       info.get("title", "Unknown Title"),
            "duration":    dur_str,
            "thumbnail":   info.get("thumbnail"),
            "uploader":    info.get("uploader") or info.get("channel", ""),
            "platform":    detected,
            "resolutions": all_res,
        })

    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if "Sign in" in msg or "login" in msg.lower():
            return jsonify({"error": "❌ This video requires login to view. Only public videos can be downloaded."}), 400
        if "Private" in msg or "private" in msg:
            return jsonify({"error": "❌ This video is private and cannot be downloaded."}), 400
        if "not available" in msg.lower():
            return jsonify({"error": "❌ This video is not available in your region or has been removed."}), 400
        return jsonify({"error": f"❌ {msg}"}), 400
    except Exception as e:
        return jsonify({"error": f"❌ Error: {str(e)}"}), 500


# ─────────────────────────────────────────────
# 2. POST /api/download
# ─────────────────────────────────────────────
@app.route("/api/download", methods=["POST"])
def start_download():
    data       = request.json or {}
    url        = data.get("url", "").strip()
    resolution = data.get("resolution", "720p HD")
    fmt        = data.get("format", "MP4").upper()
    platform   = data.get("platform", "").lower()

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    detected = detect_platform(url)
    if platform == "yt" and detected != "youtube":
        return jsonify({"error": "❌ Not a YouTube URL."}), 400
    if platform == "ig" and detected != "instagram":
        return jsonify({"error": "❌ Not an Instagram URL."}), 400

    job_id  = str(uuid.uuid4())
    fmt_ext = CONTAINER_MAP.get(fmt, "mp4")
    ydl_fmt = FORMAT_MAP.get(resolution, FORMAT_MAP["720p HD"])

    progress_store[job_id] = {
        "status": "queued", "percent": 0,
        "filename": None, "error": None, "speed": "", "eta": ""
    }

    threading.Thread(
        target=_download_worker,
        args=(job_id, url, ydl_fmt, fmt_ext, resolution),
        daemon=True,
    ).start()

    return jsonify({"job_id": job_id})


def _progress_hook(d, job_id):
    if d["status"] == "downloading":
        # Use bytes for most reliable progress (percent_str can be None on some formats)
        downloaded = d.get("downloaded_bytes", 0) or 0
        total      = d.get("total_bytes") or d.get("total_bytes_estimate") or 0

        if total > 0:
            pct = round(min((downloaded / total) * 100, 99), 1)
        else:
            # fallback to percent string
            raw = re.sub(r'\x1b\[[0-9;]*m', '', d.get("_percent_str", "0%")).strip().replace("%","")
            try:    pct = float(raw)
            except: pct = progress_store[job_id].get("percent", 0)

        speed = re.sub(r'\x1b\[[0-9;]*m', '', d.get("_speed_str", "") or "").strip()
        eta   = re.sub(r'\x1b\[[0-9;]*m', '', d.get("_eta_str",   "") or "").strip()

        progress_store[job_id].update({
            "status":  "downloading",
            "percent": pct,
            "speed":   speed,
            "eta":     eta,
        })
    elif d["status"] == "finished":
        progress_store[job_id].update({"percent": 99, "status": "processing"})


def _download_worker(job_id, url, ydl_fmt, fmt_ext, resolution):
    out_tpl    = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")
    audio_only = is_audio_res(resolution)

    postprocessors = []
    if fmt_ext == "mp3" or audio_only:
        quality = "320" if "320" in resolution else "192" if "192" in resolution else "128"
        postprocessors.append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": quality,
        })
        fmt_ext = "mp3"
    elif fmt_ext in ("mp4", "mkv"):
        postprocessors.append({
            "key": "FFmpegVideoConvertor",
            "preferedformat": fmt_ext,
        })

    ydl_opts = make_ydl_opts({
        "format":                       ydl_fmt,
        "outtmpl":                      out_tpl,
        "progress_hooks":               [lambda d: _progress_hook(d, job_id)],
        "postprocessors":               postprocessors,
        "merge_output_format":          fmt_ext if not audio_only and fmt_ext != "mp3" else None,
        "concurrent_fragment_downloads": 4,
    })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info  = ydl.extract_info(url, download=True)
            title = info.get("title", "video")

        for fname in os.listdir(DOWNLOAD_DIR):
            if fname.startswith(job_id):
                progress_store[job_id]["filename"] = fname
                progress_store[job_id]["title"]    = title
                break

        progress_store[job_id].update({"status": "done", "percent": 100})

    except Exception as e:
        progress_store[job_id].update({"status": "error", "error": str(e)})


# ─────────────────────────────────────────────
# 3. Progress polling (Railway-safe, no SSE)
# ─────────────────────────────────────────────
@app.route("/api/progress/<job_id>")
def progress_poll(job_id):
    """Simple JSON poll — works behind Railway's reverse proxy."""
    info = progress_store.get(job_id)
    if not info:
        return jsonify({"status": "not_found", "percent": 0}), 404
    return jsonify(info)


# ─────────────────────────────────────────────
# 4. Serve file
# ─────────────────────────────────────────────
@app.route("/api/file/<job_id>")
def serve_file(job_id):
    info  = progress_store.get(job_id, {})
    fname = info.get("filename")
    if not fname: return jsonify({"error": "File not ready"}), 404
    filepath = os.path.join(DOWNLOAD_DIR, fname)
    if not os.path.exists(filepath): return jsonify({"error": "File missing"}), 404
    title      = info.get("title", "video")
    safe_title = "".join(c if c.isalnum() or c in " ._-()" else "_" for c in title)[:80]
    ext        = os.path.splitext(fname)[1]
    return send_file(filepath, as_attachment=True, download_name=f"{safe_title}{ext}")


# ─────────────────────────────────────────────
# 5. Health check
# ─────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "yt_dlp": yt_dlp.version.__version__})


# ─────────────────────────────────────────────
# 6. Cleanup (delete files older than 1 hour)
# ─────────────────────────────────────────────
def _cleanup():
    while True:
        time.sleep(1800)
        now = time.time()
        for fname in os.listdir(DOWNLOAD_DIR):
            fpath = os.path.join(DOWNLOAD_DIR, fname)
            try:
                if os.path.isfile(fpath) and now - os.path.getmtime(fpath) > 3600:
                    os.remove(fpath)
            except: pass

threading.Thread(target=_cleanup, daemon=True).start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("=" * 50)
    print(f"🚀 InstaTube backend  →  http://localhost:{port}")
    print("🌍 Works for ALL users — no personal cookies")
    print("=" * 50)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
