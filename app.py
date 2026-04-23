"""
InstaTube – Final Fix
======================
Uses multiple download APIs that work from any server IP:
1. cobalt.tools (multiple instances)
2. yt-dlp with TV embedded client (most reliable bypass)
3. Direct YouTube API fallback
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp, requests, os, threading, uuid, json, time, re, random, subprocess, sys

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
COOKIE_FILE = os.path.join(os.path.dirname(__file__), "cookies.txt")
progress_store = {}

def cookies_ok():
    return os.path.exists(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 100

@app.route("/")
def index():
    return send_file(os.path.join(os.path.dirname(__file__), "index.html"))

# ── Cookies from env ──
def setup_cookies():
    content = os.environ.get("COOKIES_TXT", "").strip()
    if content:
        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        size = os.path.getsize(COOKIE_FILE)
        print(f"✅ cookies.txt written — {size} bytes")
    elif os.path.exists(COOKIE_FILE):
        size = os.path.getsize(COOKIE_FILE)
        print(f"✅ cookies.txt exists — {size} bytes")
    else:
        print("⚠️  NO COOKIES — YouTube/Instagram will be blocked!")
setup_cookies()
# Print cookie status at startup
print(f"🍪 Cookie status: {'READY ✅' if cookies_ok() else 'MISSING ❌'}")

# ── Auto-update yt-dlp ──
def auto_update():
    try:
        subprocess.run([sys.executable,"-m","pip","install","-U","yt-dlp","-q"],
                       capture_output=True, timeout=90)
        print("✅ yt-dlp updated")
    except: pass
threading.Thread(target=auto_update, daemon=True).start()

USER_AGENTS = [
    "com.google.android.youtube/17.36.4 (Linux; U; Android 12; GB) gzip",
    "com.google.android.youtube/17.31.35 (Linux; U; Android 11) gzip",
    "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 Chrome/112.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
]
def random_ua(): return random.choice(USER_AGENTS)

def detect_platform(url):
    yt = [r"youtube\.com/watch",r"youtu\.be/",r"youtube\.com/shorts/",r"youtube\.com/live/"]
    ig = [r"instagram\.com/p/",r"instagram\.com/reel/",r"instagram\.com/tv/",r"instagram\.com/stories/"]
    for p in yt:
        if re.search(p, url, re.IGNORECASE): return "youtube"
    for p in ig:
        if re.search(p, url, re.IGNORECASE): return "instagram"
    return "unknown"

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

# ─────────────────────────────────────────────
# cobalt.tools instances
# ─────────────────────────────────────────────
COBALT_INSTANCES = [
    "https://api.cobalt.tools",
    "https://cobalt.synzr.space",
    "https://cobalt.api.timelessnesses.me",
    "https://cobalt-api.hyper.lol",
    "https://capi.7ms.us",
]

def try_cobalt(url, quality="720p HD", audio_only=False, audio_q="192"):
    qmap = {"144p":"144","240p":"240","360p":"360","480p":"480",
            "720p HD":"720","1080p FHD":"1080","1440p 2K":"1440","2160p 4K":"2160"}
    payload = {
        "url": url,
        "videoQuality": qmap.get(quality,"720"),
        "audioFormat": "mp3",
        "audioBitrate": audio_q,
        "downloadMode": "audio" if audio_only else "auto",
        "filenameStyle": "basic",
    }
    headers = {"Accept":"application/json","Content-Type":"application/json","User-Agent":"InstaTube/1.0"}
    for inst in COBALT_INSTANCES:
        try:
            r = requests.post(inst, json=payload, headers=headers, timeout=15)
            if r.status_code != 200: continue
            d = r.json()
            if d.get("status") in ("redirect","stream","tunnel"):
                dl_url = d.get("url")
                if dl_url: return dl_url, d.get("filename","video"), None
            if d.get("status") == "picker":
                picks = d.get("picker",[])
                if picks: return picks[0].get("url"), "video", None
        except: continue
    return None, None, "All cobalt instances failed"

# ─────────────────────────────────────────────
# yt-dlp with ALL bypass methods
# ─────────────────────────────────────────────
# Try these clients in order — each bypasses YouTube differently
YT_CLIENTS = [
    ["tv_embedded"],           # Most reliable, no bot check
    ["android_vr"],            # VR client, bypasses detection
    ["ios"],                   # iOS client
    ["android"],               # Android client
    ["mweb"],                  # Mobile web
    ["android_creator"],       # Creator app
]

def make_ydl_opts(platform="youtube", client=None, extra=None):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "http_headers": {
            "User-Agent": random_ua(),
            "Accept-Language": "en-US,en;q=0.9",
        },
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": 4,
    }
    if platform == "youtube":
        opts["extractor_args"] = {
            "youtube": {
                "player_client": client or ["tv_embedded","android_vr","ios"],
            }
        }
    elif platform == "instagram":
        opts["http_headers"].update({
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
            "Referer": "https://www.instagram.com/",
        })
    if cookies_ok():
        opts["cookiefile"] = COOKIE_FILE
    if extra: opts.update(extra)
    return opts

def try_ytdlp_info(url, platform):
    """Try getting info with multiple clients."""
    # Try all clients
    clients_to_try = YT_CLIENTS if platform == "youtube" else [None]
    for client in clients_to_try:
        try:
            opts = make_ydl_opts(platform=platform, client=client, extra={"skip_download":True})
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info, None
        except Exception as e:
            err = str(e)
            if "private" in err.lower(): return None, "private"
            continue
    return None, "blocked"

def build_resolutions(formats):
    lmap = {2160:"2160p 4K",1440:"1440p 2K",1080:"1080p FHD",
            720:"720p HD",480:"480p",360:"360p",240:"240p",144:"144p"}
    heights = sorted(set(f.get("height") for f in formats
        if f.get("height") and f.get("vcodec","none")!="none"), reverse=True)
    labels = []
    for h in heights:
        for t,l in lmap.items():
            if h >= t and l not in labels: labels.append(l); break
    if not labels: labels = ["1080p FHD","720p HD","480p","360p","144p"]
    return labels + ["Audio 128kbps","Audio 192kbps","Audio 320kbps"]

# ── 1. GET /api/info ──
@app.route("/api/info", methods=["GET"])
def get_info():
    url      = request.args.get("url","").strip()
    platform = request.args.get("platform","yt").lower()
    if not url: return jsonify({"error":"❌ Please paste a URL."}), 400

    detected = detect_platform(url)
    if platform=="yt" and detected!="youtube":
        return jsonify({"error":"❌ Not a YouTube URL. Switch to Instagram tab!"}), 400
    if platform=="ig" and detected!="instagram":
        return jsonify({"error":"❌ Not an Instagram URL. Switch to YouTube tab!"}), 400

    info, err = try_ytdlp_info(url, detected)
    if info:
        dur = info.get("duration")
        return jsonify({
            "title":       info.get("title","Unknown"),
            "duration":    f"{int(dur//60)}:{int(dur%60):02d}" if dur else "",
            "thumbnail":   info.get("thumbnail",""),
            "uploader":    info.get("uploader") or info.get("channel",""),
            "platform":    detected,
            "resolutions": build_resolutions(info.get("formats",[])),
        })

    # Even if info fails, allow download via cobalt
    return jsonify({
        "title":       "Video ready to download",
        "duration":    "",
        "thumbnail":   "",
        "uploader":    detected.title(),
        "platform":    detected,
        "resolutions": ["1080p FHD","720p HD","480p","360p","144p",
                        "Audio 128kbps","Audio 192kbps","Audio 320kbps"],
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
    job_id   = str(uuid.uuid4())
    fmt_ext  = CONTAINER_MAP.get(fmt,"mp4")
    ydl_fmt  = FORMAT_MAP.get(res, FORMAT_MAP["720p HD"])
    audio_only = is_audio(res)
    if audio_only: fmt_ext = "mp3"

    progress_store[job_id] = {"status":"queued","percent":0,"filename":None,"error":None,"speed":"","eta":""}
    threading.Thread(target=_worker,
        args=(job_id,url,res,fmt_ext,ydl_fmt,audio_only,detected), daemon=True).start()
    return jsonify({"job_id": job_id})

def download_url_to_file(dl_url, job_id, title, ext):
    out = os.path.join(DOWNLOAD_DIR, f"{job_id}.{ext}")
    try:
        r = requests.get(dl_url, stream=True, timeout=120, headers={"User-Agent":random_ua()})
        total = int(r.headers.get("content-length",0))
        done  = 0
        with open(out,"wb") as f:
            for chunk in r.iter_content(65536):
                if chunk:
                    f.write(chunk)
                    done += len(chunk)
                    if total > 0:
                        progress_store[job_id].update({
                            "status":"downloading",
                            "percent":round(min(done/total*100,99),1)
                        })
        progress_store[job_id].update({"status":"done","percent":100,
            "filename":f"{job_id}.{ext}","title":title})
    except Exception as e:
        progress_store[job_id].update({"status":"error","error":str(e)})

def _progress_hook(d, job_id):
    if d["status"] == "downloading":
        dl    = d.get("downloaded_bytes") or 0
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        pct   = round(min(dl/total*100,99),1) if total>0 else progress_store[job_id].get("percent",0)
        speed = re.sub(r'\x1b\[[0-9;]*m','',d.get("_speed_str","") or "").strip()
        eta   = re.sub(r'\x1b\[[0-9;]*m','',d.get("_eta_str","")   or "").strip()
        progress_store[job_id].update({"status":"downloading","percent":pct,"speed":speed,"eta":eta})
    elif d["status"] == "finished":
        progress_store[job_id].update({"percent":99,"status":"processing"})

def _worker(job_id, url, resolution, fmt_ext, ydl_fmt, audio_only, platform):
    progress_store[job_id].update({"status":"downloading","percent":5})

    # ── Strategy 1: cobalt.tools ──
    audio_q = "320" if "320" in resolution else "192" if "192" in resolution else "128"
    dl_url, title, err = try_cobalt(url, resolution, audio_only, audio_q)
    if dl_url:
        print(f"✅ cobalt success")
        download_url_to_file(dl_url, job_id, title or "video", fmt_ext)
        return

    print(f"⚠️  cobalt failed: {err} — trying yt-dlp")

    # ── Strategy 2: yt-dlp with multiple clients ──
    out_tpl = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")
    pps = []
    if fmt_ext=="mp3" or audio_only:
        q = "320" if "320" in resolution else "192" if "192" in resolution else "128"
        pps.append({"key":"FFmpegExtractAudio","preferredcodec":"mp3","preferredquality":q})
        fmt_ext = "mp3"
    elif fmt_ext in ("mp4","mkv"):
        pps.append({"key":"FFmpegVideoConvertor","preferedformat":fmt_ext})

    clients = YT_CLIENTS if platform=="youtube" else [None]
    for client in clients:
        try:
            opts = make_ydl_opts(platform=platform, client=client, extra={
                "format": ydl_fmt, "outtmpl": out_tpl,
                "progress_hooks": [lambda d: _progress_hook(d,job_id)],
                "postprocessors": pps,
                "merge_output_format": fmt_ext if not audio_only and fmt_ext!="mp3" else None,
            })
            with yt_dlp.YoutubeDL(opts) as ydl:
                info  = ydl.extract_info(url, download=True)
                title = info.get("title","video")

            fname = next((f for f in os.listdir(DOWNLOAD_DIR) if f.startswith(job_id)),None)
            if fname:
                progress_store[job_id].update({"status":"done","percent":100,"filename":fname,"title":title})
                return
        except Exception as e:
            err = str(e)
            print(f"⚠️  client {client} failed: {err[:80]}")
            if "private" in err.lower(): break
            continue

    progress_store[job_id].update({"status":"error",
        "error":"❌ YouTube is blocking all download attempts from this server. Please try again in 2 minutes."})

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
                    "cookies":"✅" if cookies_ok() else "⚠️ none"})

# ── 6. Cleanup ──
def _cleanup():
    while True:
        time.sleep(1800)
        now = time.time()
        for f in os.listdir(DOWNLOAD_DIR):
            fp = os.path.join(DOWNLOAD_DIR,f)
            try:
                if os.path.isfile(fp) and now-os.path.getmtime(fp)>3600: os.remove(fp)
            except: pass
threading.Thread(target=_cleanup,daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT",8080))
    print(f"🚀 InstaTube → port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
