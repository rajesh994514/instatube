"""
InstaTube – Works for EVERY user, no personal cookies needed
=============================================================
YouTube:   cobalt.tools API (free, no cookies, no bot detection)
Instagram: cobalt.tools API (free, no cookies, no bot detection)  
Fallback:  yt-dlp with multiple client rotation

cobalt.tools is an open-source downloader API used by millions.
It handles all bot detection internally — we just call it.
"""

from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import yt_dlp, requests, os, threading, uuid, json, time, re, random, subprocess, sys, urllib.request

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
COOKIE_FILE   = os.path.join(os.path.dirname(__file__), "cookies.txt")
progress_store = {}

# ── Serve frontend ──
@app.route("/")
def index():
    return send_file(os.path.join(os.path.dirname(__file__), "index.html"))

# ── Setup cookies from env (optional, improves reliability) ──
def setup_cookies():
    content = os.environ.get("COOKIES_TXT", "").strip()
    if content:
        with open(COOKIE_FILE, "w") as f: f.write(content)
        print("✅ cookies.txt loaded from env")
setup_cookies()

# ── Auto-update yt-dlp ──
def auto_update():
    try:
        subprocess.run([sys.executable,"-m","pip","install","-U","yt-dlp","-q"],
                       capture_output=True, timeout=90)
        print("✅ yt-dlp updated")
    except: pass
threading.Thread(target=auto_update, daemon=True).start()

# ─────────────────────────────────────────────
# USER AGENTS
# ─────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 Chrome/112.0 Mobile Safari/537.36",
    "com.google.android.youtube/17.36.4 (Linux; U; Android 12) gzip",
]
def random_ua(): return random.choice(USER_AGENTS)

# ─────────────────────────────────────────────
# Platform detection
# ─────────────────────────────────────────────
def detect_platform(url):
    yt = [r"youtube\.com/watch",r"youtu\.be/",r"youtube\.com/shorts/",r"youtube\.com/live/"]
    ig = [r"instagram\.com/p/",r"instagram\.com/reel/",r"instagram\.com/tv/",r"instagram\.com/stories/"]
    for p in yt:
        if re.search(p, url, re.IGNORECASE): return "youtube"
    for p in ig:
        if re.search(p, url, re.IGNORECASE): return "instagram"
    return "unknown"

# ─────────────────────────────────────────────
# Format maps
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
CONTAINER_MAP = {"MP4":"mp4","WEBM":"webm","MKV":"mkv","MP3":"mp3","M4A":"m4a"}
def is_audio(r): return r.startswith("Audio")

def cookies_ready():
    return os.path.exists(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 100

# ─────────────────────────────────────────────
# COBALT.TOOLS API — works for everyone
# Open source, free, no cookies needed
# Handles YouTube + Instagram bot detection
# ─────────────────────────────────────────────
COBALT_INSTANCES = [
    "https://api.cobalt.tools",
    "https://cobalt.synzr.space",
    "https://cobalt.api.timelessnesses.me",
    "https://cobalt-api.hyper.lol",
    "https://cobalt.api.lostdusty.com",
]

def cobalt_get_info(url):
    """Get video info using yt-dlp (for metadata only, fast)."""
    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "nocheckcertificate": True,
        "http_headers": {"User-Agent": random_ua()},
        "extractor_args": {"youtube": {"player_client": ["android_vr","ios","android"]}},
        "socket_timeout": 30,
    }
    if cookies_ready(): opts["cookiefile"] = COOKIE_FILE
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)

def cobalt_download(url, quality="720p HD", is_audio_mode=False, audio_quality="192"):
    """
    Download via cobalt.tools API — works for everyone without cookies.
    Returns: (file_path, title, error)
    """
    headers = {
        "Accept":       "application/json",
        "Content-Type": "application/json",
        "User-Agent":   "InstaTube/1.0",
    }

    # Map our quality to cobalt format
    quality_map = {
        "144p":"144","240p":"240","360p":"360","480p":"480",
        "720p HD":"720","1080p FHD":"1080","1440p 2K":"1440","2160p 4K":"2160",
    }
    cobalt_quality = quality_map.get(quality, "720")

    payload = {
        "url":           url,
        "videoQuality":  cobalt_quality,
        "audioFormat":   "mp3",
        "audioBitrate":  audio_quality,
        "downloadMode":  "audio" if is_audio_mode else "auto",
        "filenameStyle": "basic",
    }

    last_error = "All cobalt instances failed"

    for instance in COBALT_INSTANCES:
        try:
            resp = requests.post(
                instance, json=payload, headers=headers, timeout=20
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            status = data.get("status","")

            if status == "error":
                last_error = data.get("error", {}).get("code", "Unknown cobalt error")
                continue

            # Direct download URL
            if status in ("redirect", "stream", "tunnel"):
                download_url = data.get("url")
                if not download_url:
                    continue
                return download_url, data.get("filename","video"), None

            # Picker (multiple streams — pick best)
            if status == "picker":
                picks = data.get("picker", [])
                if picks:
                    return picks[0].get("url"), "video", None

        except Exception as e:
            last_error = str(e)
            continue

    return None, None, last_error


def download_from_url(download_url, job_id, title, ext):
    """Stream download from URL to disk with progress tracking."""
    out_path = os.path.join(DOWNLOAD_DIR, f"{job_id}.{ext}")
    try:
        resp = requests.get(download_url, stream=True, timeout=60,
                            headers={"User-Agent": random_ua()})
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0

        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024*64):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = round(min(downloaded/total*100, 99), 1)
                        speed_kb = round(len(chunk)/1024, 1)
                        progress_store[job_id].update({
                            "status":"downloading","percent":pct,
                            "speed":f"{speed_kb} KB/s","eta":""
                        })

        fname = f"{job_id}.{ext}"
        progress_store[job_id].update({
            "status":"done","percent":100,
            "filename":fname,"title":title
        })

    except Exception as e:
        progress_store[job_id].update({"status":"error","error":str(e)})


# ─────────────────────────────────────────────
# YT-DLP FALLBACK — when cobalt fails
# ─────────────────────────────────────────────
def ytdlp_opts(platform="youtube", extra=None):
    opts = {
        "quiet": True, "no_warnings": True, "nocheckcertificate": True,
        "http_headers": {"User-Agent": random_ua(), "Accept-Language": "en-US,en;q=0.9"},
        "retries": 10, "fragment_retries": 10, "socket_timeout": 60,
        "concurrent_fragment_downloads": 4,
    }
    if platform == "youtube":
        opts["extractor_args"] = {
            "youtube": {"player_client": ["android_vr","ios","android","tv_embedded"]}
        }
    if cookies_ready():
        opts["cookiefile"] = COOKIE_FILE
    if platform == "instagram":
        opts["http_headers"].update({
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
            "Referer":    "https://www.instagram.com/",
        })
    if extra: opts.update(extra)
    return opts

def build_resolutions(formats):
    lmap = {2160:"2160p 4K",1440:"1440p 2K",1080:"1080p FHD",
            720:"720p HD",480:"480p",360:"360p",240:"240p",144:"144p"}
    heights = sorted(set(
        f.get("height") for f in formats
        if f.get("height") and f.get("vcodec","none")!="none"
    ), reverse=True)
    labels = []
    for h in heights:
        for t,l in lmap.items():
            if h >= t and l not in labels: labels.append(l); break
    if not labels: labels = ["1080p FHD","720p HD","480p","360p","144p"]
    return labels + ["Audio 128kbps","Audio 192kbps","Audio 320kbps"]

# ─────────────────────────────────────────────
# 1. GET /api/info
# ─────────────────────────────────────────────
@app.route("/api/info", methods=["GET"])
def get_info():
    url      = request.args.get("url","").strip()
    platform = request.args.get("platform","yt").lower()
    if not url:
        return jsonify({"error":"❌ Please paste a video URL."}), 400

    detected = detect_platform(url)
    if platform == "yt" and detected != "youtube":
        return jsonify({"error":"❌ Not a YouTube URL. Switch to the Instagram tab!"}), 400
    if platform == "ig" and detected != "instagram":
        return jsonify({"error":"❌ Not an Instagram URL. Switch to the YouTube tab!"}), 400

    # Try yt-dlp for metadata (fast, just needs info not download)
    try:
        opts = ytdlp_opts(platform=detected, extra={"skip_download":True})
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        dur = info.get("duration")
        return jsonify({
            "title":       info.get("title","Unknown"),
            "duration":    f"{int(dur//60)}:{int(dur%60):02d}" if dur else "",
            "thumbnail":   info.get("thumbnail",""),
            "uploader":    info.get("uploader") or info.get("channel",""),
            "platform":    detected,
            "resolutions": build_resolutions(info.get("formats",[])),
        })
    except Exception as e:
        msg = str(e)
        # Even if metadata fails, still allow download attempt via cobalt
        # Return basic info so user can still try downloading
        if "Sign in" in msg or "bot" in msg.lower() or "403" in msg:
            return jsonify({
                "title":       "Video (click Download to fetch)",
                "duration":    "",
                "thumbnail":   "",
                "uploader":    detected.title(),
                "platform":    detected,
                "resolutions": ["1080p FHD","720p HD","480p","360p","144p",
                                "Audio 128kbps","Audio 192kbps","Audio 320kbps"],
            })
        if "private" in msg.lower():
            return jsonify({"error":"❌ This video is private."}), 400
        return jsonify({"error":f"❌ {msg}"}), 400


# ─────────────────────────────────────────────
# 2. POST /api/download
# ─────────────────────────────────────────────
@app.route("/api/download", methods=["POST"])
def start_download():
    data       = request.json or {}
    url        = data.get("url","").strip()
    resolution = data.get("resolution","720p HD")
    fmt        = data.get("format","MP4").upper()
    platform   = data.get("platform","yt").lower()
    if not url: return jsonify({"error":"No URL"}), 400

    detected = detect_platform(url)
    if platform=="yt" and detected!="youtube": return jsonify({"error":"❌ Not YouTube"}), 400
    if platform=="ig" and detected!="instagram": return jsonify({"error":"❌ Not Instagram"}), 400

    job_id  = str(uuid.uuid4())
    fmt_ext = CONTAINER_MAP.get(fmt,"mp4")
    ydl_fmt = FORMAT_MAP.get(resolution, FORMAT_MAP["720p HD"])
    audio_only = is_audio(resolution)
    if audio_only: fmt_ext = "mp3"

    progress_store[job_id] = {
        "status":"queued","percent":0,
        "filename":None,"error":None,"speed":"","eta":""
    }

    threading.Thread(
        target=_worker,
        args=(job_id, url, resolution, fmt_ext, ydl_fmt, audio_only, detected),
        daemon=True
    ).start()
    return jsonify({"job_id": job_id})


def _worker(job_id, url, resolution, fmt_ext, ydl_fmt, audio_only, platform):
    progress_store[job_id].update({"status":"downloading","percent":5})

    # ── Strategy 1: cobalt.tools (no cookies, works for everyone) ──
    audio_q = "320" if "320" in resolution else "192" if "192" in resolution else "128"
    dl_url, title, err = cobalt_download(url, resolution, audio_only, audio_q)

    if dl_url:
        print(f"✅ cobalt.tools success for job {job_id}")
        progress_store[job_id].update({"status":"downloading","percent":10})
        download_from_url(dl_url, job_id, title or "video", fmt_ext)
        return

    # ── Strategy 2: yt-dlp fallback ──
    print(f"⚠️  cobalt failed ({err}), trying yt-dlp for job {job_id}")
    progress_store[job_id].update({"status":"downloading","percent":5})
    _ytdlp_worker(job_id, url, ydl_fmt, fmt_ext, resolution, platform)


def _progress_hook(d, job_id):
    if d["status"] == "downloading":
        dl    = d.get("downloaded_bytes") or 0
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        if total > 0:
            pct = round(min(dl/total*100, 99), 1)
        else:
            raw = re.sub(r'\x1b\[[0-9;]*m','', d.get("_percent_str","0%") or "0%").replace("%","").strip()
            try: pct = float(raw)
            except: pct = progress_store[job_id].get("percent",0)
        speed = re.sub(r'\x1b\[[0-9;]*m','', d.get("_speed_str","") or "").strip()
        eta   = re.sub(r'\x1b\[[0-9;]*m','', d.get("_eta_str","")   or "").strip()
        progress_store[job_id].update({"status":"downloading","percent":pct,"speed":speed,"eta":eta})
    elif d["status"] == "finished":
        progress_store[job_id].update({"percent":99,"status":"processing"})


def _ytdlp_worker(job_id, url, ydl_fmt, fmt_ext, resolution, platform):
    out_tpl    = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")
    audio_only = is_audio(resolution)
    pps = []
    if fmt_ext=="mp3" or audio_only:
        q = "320" if "320" in resolution else "192" if "192" in resolution else "128"
        pps.append({"key":"FFmpegExtractAudio","preferredcodec":"mp3","preferredquality":q})
        fmt_ext = "mp3"
    elif fmt_ext in ("mp4","mkv"):
        pps.append({"key":"FFmpegVideoConvertor","preferedformat":fmt_ext})

    opts = ytdlp_opts(platform=platform, extra={
        "format": ydl_fmt, "outtmpl": out_tpl,
        "progress_hooks": [lambda d: _progress_hook(d, job_id)],
        "postprocessors": pps,
        "merge_output_format": fmt_ext if not audio_only and fmt_ext!="mp3" else None,
    })
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info  = ydl.extract_info(url, download=True)
            title = info.get("title","video")
        fname = next((f for f in os.listdir(DOWNLOAD_DIR) if f.startswith(job_id)), None)
        if fname:
            progress_store[job_id].update({"status":"done","percent":100,"filename":fname,"title":title})
        else:
            progress_store[job_id].update({"status":"error","error":"Download finished but file not saved. Try again."})
    except Exception as e:
        err = str(e)
        if "Sign in" in err or "bot" in err.lower():
            err = "❌ YouTube is blocking this server. Please try again in 1 minute."
        elif "login" in err.lower() and "instagram" in err.lower():
            err = "❌ Instagram is blocking this server. Please add cookies in Railway Variables."
        progress_store[job_id].update({"status":"error","error":err})


# ─────────────────────────────────────────────
# 3. Progress poll
# ─────────────────────────────────────────────
@app.route("/api/progress/<job_id>")
def progress_poll(job_id):
    info = progress_store.get(job_id)
    if not info: return jsonify({"status":"not_found","percent":0}), 404
    return jsonify(info)


# ─────────────────────────────────────────────
# 4. Serve file
# ─────────────────────────────────────────────
@app.route("/api/file/<job_id>")
def serve_file(job_id):
    info  = progress_store.get(job_id,{})
    fname = info.get("filename")
    if not fname: return jsonify({"error":"Not ready"}), 404
    fp = os.path.join(DOWNLOAD_DIR, fname)
    if not os.path.exists(fp): return jsonify({"error":"File missing"}), 404
    safe = "".join(c if c.isalnum() or c in " ._-()" else "_" for c in info.get("title","video"))[:80]
    ext  = os.path.splitext(fname)[1]
    return send_file(fp, as_attachment=True, download_name=f"{safe}{ext}")


# ─────────────────────────────────────────────
# 5. Health
# ─────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({
        "status":  "ok",
        "yt_dlp":  yt_dlp.version.__version__,
        "cookies": "✅ loaded" if cookies_ready() else "⚠️ none (YouTube only)",
        "engine":  "cobalt.tools + yt-dlp fallback",
    })


# ─────────────────────────────────────────────
# 6. Cleanup
# ─────────────────────────────────────────────
def _cleanup():
    while True:
        time.sleep(1800)
        now = time.time()
        for f in os.listdir(DOWNLOAD_DIR):
            fp = os.path.join(DOWNLOAD_DIR, f)
            try:
                if os.path.isfile(fp) and now - os.path.getmtime(fp) > 3600: os.remove(fp)
            except: pass
threading.Thread(target=_cleanup, daemon=True).start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("=" * 55)
    print(f"🚀 InstaTube → http://localhost:{port}")
    print(f"🔧 Engine: cobalt.tools API + yt-dlp fallback")
    print(f"🌍 Works for ALL users — no cookies needed")
    print("=" * 55)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
