"""
InstaTube Backend – Full Production Fix
========================================
YouTube  → android_vr + ios clients (no cookies, bypasses bot detection)
Instagram → cookies.txt from COOKIES_TXT env variable (required)
Progress  → polling-based (works on Railway, no SSE issues)
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os, threading, uuid, json, time, re, random, subprocess, sys

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
COOKIE_FILE  = os.path.join(os.path.dirname(__file__), "cookies.txt")
progress_store = {}

@app.route("/")
def index():
    return send_file(os.path.join(os.path.dirname(__file__), "index.html"))

# ── Write cookies from Railway env variable ──
def setup_cookies():
    content = os.environ.get("COOKIES_TXT", "").strip()
    if content:
        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        print("✅ cookies.txt written from COOKIES_TXT env var")
    elif os.path.exists(COOKIE_FILE):
        print("✅ Using existing cookies.txt")
    else:
        print("⚠️  No cookies — Instagram will not work. Set COOKIES_TXT in Railway Variables.")
setup_cookies()

# ── Auto-update yt-dlp ──
def auto_update():
    try:
        subprocess.run([sys.executable,"-m","pip","install","-U","yt-dlp","-q"],
                       capture_output=True, timeout=90)
        print("✅ yt-dlp up to date")
    except Exception as e:
        print(f"⚠️  yt-dlp update: {e}")
threading.Thread(target=auto_update, daemon=True).start()

# ── User Agents ──
USER_AGENTS = [
    "com.google.android.youtube/17.36.4 (Linux; U; Android 12) gzip",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 Chrome/112.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
]
def random_ua(): return random.choice(USER_AGENTS)

# ── Platform detection ──
def detect_platform(url):
    yt_p = [r"youtube\.com/watch",r"youtu\.be/",r"youtube\.com/shorts/",r"youtube\.com/live/",r"m\.youtube\.com/"]
    ig_p = [r"instagram\.com/p/",r"instagram\.com/reel/",r"instagram\.com/tv/",r"instagram\.com/stories/"]
    for p in yt_p:
        if re.search(p, url, re.IGNORECASE): return "youtube"
    for p in ig_p:
        if re.search(p, url, re.IGNORECASE): return "instagram"
    return "unknown"

# ── Format maps ──
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

# ── Build yt-dlp options ──
def make_opts(platform="youtube", extra=None):
    opts = {
        "quiet": True, "no_warnings": True, "nocheckcertificate": True,
        "http_headers": {"User-Agent": random_ua(), "Accept-Language": "en-US,en;q=0.9"},
        "retries": 10, "fragment_retries": 10, "file_access_retries": 3,
        "socket_timeout": 60, "concurrent_fragment_downloads": 4,
    }
    if platform == "youtube":
        # android_vr + ios = bypass YouTube bot detection, no login needed
        opts["extractor_args"] = {
            "youtube": {"player_client": ["android_vr", "ios", "android"]}
        }
        if cookies_ready():
            opts["cookiefile"] = COOKIE_FILE

    elif platform == "instagram":
        if cookies_ready():
            opts["cookiefile"] = COOKIE_FILE
        opts["http_headers"].update({
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
            "Referer":    "https://www.instagram.com/",
            "X-IG-App-ID":"936619743392459",
        })
    if extra:
        opts.update(extra)
    return opts

def build_resolutions(formats):
    lmap = {2160:"2160p 4K",1440:"1440p 2K",1080:"1080p FHD",
            720:"720p HD",480:"480p",360:"360p",240:"240p",144:"144p"}
    heights = sorted(set(f.get("height") for f in formats
                         if f.get("height") and f.get("vcodec","none")!="none"), reverse=True)
    labels = []
    for h in heights:
        for t,l in lmap.items():
            if h >= t and l not in labels:
                labels.append(l); break
    if not labels: labels = ["720p HD","480p","360p","144p"]
    return labels + ["Audio 128kbps","Audio 192kbps","Audio 320kbps"]

def safe_extract(url, platform):
    """Extract info with automatic retry on bot-detection."""
    opts = make_opts(platform=platform, extra={"skip_download": True})
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False), None
    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        # YouTube retry with ios-only client
        if platform == "youtube" and ("Sign in" in msg or "403" in msg or "bot" in msg.lower()):
            r_opts = make_opts(platform="youtube", extra={"skip_download": True})
            r_opts["extractor_args"] = {"youtube": {"player_client": ["ios"]}}
            try:
                with yt_dlp.YoutubeDL(r_opts) as ydl:
                    return ydl.extract_info(url, download=False), None
            except Exception as e2:
                return None, str(e2)
        return None, msg
    except Exception as e:
        return None, str(e)

# ── 1. GET /api/info ──
@app.route("/api/info", methods=["GET"])
def get_info():
    url      = request.args.get("url","").strip()
    platform = request.args.get("platform","yt").lower()
    if not url:
        return jsonify({"error":"❌ Please paste a video URL."}), 400

    detected = detect_platform(url)
    if platform == "yt" and detected != "youtube":
        return jsonify({"error":"❌ Not a YouTube URL. Switch to Instagram tab!"}), 400
    if platform == "ig" and detected != "instagram":
        return jsonify({"error":"❌ Not an Instagram URL. Switch to YouTube tab!"}), 400
    if detected == "instagram" and not cookies_ready():
        return jsonify({"error":"❌ Instagram needs cookies. Add COOKIES_TXT in Railway → Variables."}), 400

    info, err = safe_extract(url, detected)
    if err:
        if "private" in err.lower():   return jsonify({"error":"❌ This video is private."}), 400
        if "removed" in err.lower():   return jsonify({"error":"❌ Video was removed."}), 400
        if "429" in err or "rate" in err.lower(): return jsonify({"error":"❌ Rate limited. Wait 30s and retry."}), 429
        return jsonify({"error": f"❌ {err}"}), 400

    dur = info.get("duration")
    return jsonify({
        "title":       info.get("title","Unknown"),
        "duration":    f"{int(dur//60)}:{int(dur%60):02d}" if dur else "",
        "thumbnail":   info.get("thumbnail",""),
        "uploader":    info.get("uploader") or info.get("channel",""),
        "platform":    detected,
        "resolutions": build_resolutions(info.get("formats",[])),
    })

# ── 2. POST /api/download ──
@app.route("/api/download", methods=["POST"])
def start_download():
    data     = request.json or {}
    url      = data.get("url","").strip()
    res      = data.get("resolution","720p HD")
    fmt      = data.get("format","MP4").upper()
    platform = data.get("platform","yt").lower()
    if not url: return jsonify({"error":"No URL"}), 400

    detected = detect_platform(url)
    if platform=="yt" and detected!="youtube": return jsonify({"error":"❌ Not YouTube"}), 400
    if platform=="ig" and detected!="instagram": return jsonify({"error":"❌ Not Instagram"}), 400

    job_id  = str(uuid.uuid4())
    fmt_ext = CONTAINER_MAP.get(fmt,"mp4")
    ydl_fmt = FORMAT_MAP.get(res, FORMAT_MAP["720p HD"])
    progress_store[job_id] = {"status":"queued","percent":0,"filename":None,"error":None,"speed":"","eta":""}

    threading.Thread(target=_worker, args=(job_id,url,ydl_fmt,fmt_ext,res,detected), daemon=True).start()
    return jsonify({"job_id": job_id})

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

def _worker(job_id, url, ydl_fmt, fmt_ext, resolution, platform):
    out_tpl    = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")
    audio_only = is_audio(resolution)
    pps = []
    if fmt_ext=="mp3" or audio_only:
        q = "320" if "320" in resolution else "192" if "192" in resolution else "128"
        pps.append({"key":"FFmpegExtractAudio","preferredcodec":"mp3","preferredquality":q})
        fmt_ext = "mp3"
    elif fmt_ext in ("mp4","mkv"):
        pps.append({"key":"FFmpegVideoConvertor","preferedformat":fmt_ext})

    opts = make_opts(platform=platform, extra={
        "format":             ydl_fmt,
        "outtmpl":            out_tpl,
        "progress_hooks":     [lambda d: _progress_hook(d, job_id)],
        "postprocessors":     pps,
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
            progress_store[job_id].update({"status":"error","error":"File not found after download."})
    except Exception as e:
        err = str(e)
        if "Sign in" in err:   err = "YouTube blocked this. Please retry in a moment."
        if "login" in err.lower() and "instagram" in err.lower(): err = "Instagram cookies expired. Refresh COOKIES_TXT in Railway Variables."
        progress_store[job_id].update({"status":"error","error":err})

# ── 3. Progress poll ──
@app.route("/api/progress/<job_id>")
def progress_poll(job_id):
    info = progress_store.get(job_id)
    if not info: return jsonify({"status":"not_found","percent":0}), 404
    return jsonify(info)

# ── 4. Serve file ──
@app.route("/api/file/<job_id>")
def serve_file(job_id):
    info  = progress_store.get(job_id,{})
    fname = info.get("filename")
    if not fname: return jsonify({"error":"Not ready"}), 404
    fp = os.path.join(DOWNLOAD_DIR, fname)
    if not os.path.exists(fp): return jsonify({"error":"Missing"}), 404
    safe = "".join(c if c.isalnum() or c in " ._-()" else "_" for c in info.get("title","video"))[:80]
    return send_file(fp, as_attachment=True, download_name=f"{safe}{os.path.splitext(fname)[1]}")

# ── 5. Health ──
@app.route("/api/health")
def health():
    return jsonify({"status":"ok","yt_dlp":yt_dlp.version.__version__,
                    "cookies":"✅ loaded" if cookies_ready() else "⚠️ missing"})

# ── 6. Cleanup ──
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
    print(f"🚀 InstaTube → http://localhost:{port}")
    print(f"🍪 Cookies: {'✅' if cookies_ready() else '⚠️  missing'}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
