"""
InstaTube - Final Working Version
- No ffmpeg needed (uses single file formats)
- Works with cookies for YouTube + Instagram
- Multiple client fallbacks
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

@app.route("/")
def index():
    return send_file(os.path.join(os.path.dirname(__file__), "index.html"))

def cookies_ok():
    return os.path.exists(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 100

def setup_cookies():
    content = os.environ.get("COOKIES_TXT", "").strip()
    if content:
        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"✅ cookies.txt written — {os.path.getsize(COOKIE_FILE)} bytes")
    else:
        print("⚠️  No COOKIES_TXT found!")
setup_cookies()
print(f"🍪 Cookies: {'READY ✅' if cookies_ok() else 'MISSING ❌'}")

def auto_update():
    try:
        subprocess.run([sys.executable,"-m","pip","install","-U","yt-dlp","-q"],
                      capture_output=True, timeout=90)
        print("✅ yt-dlp updated")
    except: pass
threading.Thread(target=auto_update, daemon=True).start()

def detect_platform(url):
    yt = [r"youtube\.com/watch",r"youtu\.be/",r"youtube\.com/shorts/",r"youtube\.com/live/"]
    ig = [r"instagram\.com/p/",r"instagram\.com/reel/",r"instagram\.com/tv/",r"instagram\.com/stories/"]
    for p in yt:
        if re.search(p, url, re.IGNORECASE): return "youtube"
    for p in ig:
        if re.search(p, url, re.IGNORECASE): return "instagram"
    return "unknown"

CONTAINER_MAP = {"MP4":"mp4","WEBM":"webm","MKV":"mkv","MP3":"mp3","M4A":"m4a"}
def is_audio(r): return r.startswith("Audio")

QUALITY_MAP = {
    "144p":144,"240p":240,"360p":360,"480p":480,
    "720p HD":720,"1080p FHD":1080,"1440p 2K":1440,"2160p 4K":2160,
}

USER_AGENTS = [
    "com.google.android.youtube/17.36.4 (Linux; U; Android 12) gzip",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
]
def random_ua(): return random.choice(USER_AGENTS)

# KEY FIX: Use single-file formats — NO ffmpeg needed!
# Format: best single file up to that height
FORMAT_MAP = {
    "144p":          "best[height<=144]/worst[ext=mp4]/worst",
    "240p":          "best[height<=240]/worst[ext=mp4]/worst",
    "360p":          "best[height<=360]/best[ext=mp4]/best",
    "480p":          "best[height<=480]/best[ext=mp4]/best",
    "720p HD":       "best[height<=720]/best[ext=mp4]/best",
    "1080p FHD":     "best[height<=1080]/best[ext=mp4]/best",
    "1440p 2K":      "best[height<=1440]/best[ext=mp4]/best",
    "2160p 4K":      "best[height<=2160]/best[ext=mp4]/best",
    "Audio 128kbps": "bestaudio[ext=m4a]/bestaudio/best",
    "Audio 192kbps": "bestaudio[ext=m4a]/bestaudio/best",
    "Audio 320kbps": "bestaudio[ext=m4a]/bestaudio/best",
}

def make_opts(platform="youtube", client=None, extra=None):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "http_headers": {
            "User-Agent": random_ua(),
            "Accept-Language": "en-US,en;q=0.9",
        },
        "retries": 6,
        "fragment_retries": 6,
        "socket_timeout": 30,
        # NEVER try to merge — no ffmpeg on server
        "format_sort": ["res", "ext:mp4:m4a"],
    }
    if platform == "youtube":
        opts["extractor_args"] = {
            "youtube": {
                "player_client": client or ["tv_embedded","android_vr","ios","android"]
            }
        }
    elif platform == "instagram":
        opts["http_headers"].update({
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
            "Referer": "https://www.instagram.com/",
        })
    if cookies_ok():
        opts["cookiefile"] = COOKIE_FILE
    if extra:
        opts.update(extra)
    return opts

def build_resolutions(formats):
    lmap = {2160:"2160p 4K",1440:"1440p 2K",1080:"1080p FHD",
            720:"720p HD",480:"480p",360:"360p",240:"240p",144:"144p"}
    heights = sorted(set(
        f.get("height") for f in formats
        if f.get("height") and f.get("vcodec","none") != "none"
    ), reverse=True)
    labels = []
    for h in heights:
        for t,l in lmap.items():
            if h >= t and l not in labels:
                labels.append(l); break
    if not labels:
        labels = ["720p HD","480p","360p","144p"]
    return labels + ["Audio 128kbps","Audio 192kbps","Audio 320kbps"]

# ── cobalt.tools (no ffmpeg needed, direct download) ──
COBALT = [
    "https://api.cobalt.tools",
    "https://cobalt.synzr.space",
    "https://cobalt.api.timelessnesses.me",
]

def try_cobalt(url, quality, audio_only, audio_q):
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
    headers = {
        "Accept":"application/json",
        "Content-Type":"application/json",
        "User-Agent":"InstaTube/1.0"
    }
    for inst in COBALT:
        try:
            r = requests.post(inst, json=payload, headers=headers,
                            timeout=8, verify=False)
            if r.status_code != 200: continue
            d = r.json()
            if d.get("status") in ("redirect","stream","tunnel"):
                dl = d.get("url")
                if dl: return dl, d.get("filename","video"), None
            if d.get("status") == "picker":
                picks = d.get("picker",[])
                if picks: return picks[0].get("url"), "video", None
        except Exception as e:
            print(f"cobalt {inst}: {str(e)[:50]}")
            continue
    return None, None, "cobalt unavailable"

def download_url(dl_url, job_id, title, ext):
    out = os.path.join(DOWNLOAD_DIR, f"{job_id}.{ext}")
    try:
        r = requests.get(dl_url, stream=True, timeout=120, headers={"User-Agent":random_ua()})
        total = int(r.headers.get("content-length",0))
        done = 0
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
        progress_store[job_id].update({
            "status":"done","percent":100,
            "filename":f"{job_id}.{ext}","title":title
        })
    except Exception as e:
        progress_store[job_id].update({"status":"error","error":str(e)})

# ── 1. GET /api/info ──
@app.route("/api/info", methods=["GET"])
def get_info():
    url = request.args.get("url","").strip()
    platform = request.args.get("platform","yt").lower()
    if not url: return jsonify({"error":"❌ Please paste a URL."}), 400

    detected = detect_platform(url)
    if platform=="yt" and detected!="youtube":
        return jsonify({"error":"❌ Not a YouTube URL. Switch to Instagram tab!"}), 400
    if platform=="ig" and detected!="instagram":
        return jsonify({"error":"❌ Not an Instagram URL. Switch to YouTube tab!"}), 400

    try:
        opts = make_opts(platform=detected, extra={"skip_download":True})
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
        if "private" in msg.lower():
            return jsonify({"error":"❌ This video is private."}), 400
        # Return basic info so user can still try downloading
        return jsonify({
            "title":"Video ready — click Download",
            "duration":"","thumbnail":"","uploader":detected.title(),
            "platform":detected,
            "resolutions":["720p HD","480p","360p","144p",
                          "Audio 128kbps","Audio 192kbps","Audio 320kbps"],
        })

# ── 2. POST /api/download ──
@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.json or {}
    url = data.get("url","").strip()
    resolution = data.get("resolution","720p HD")
    fmt = data.get("format","MP4").upper()
    platform = data.get("platform","yt").lower()
    if not url: return jsonify({"error":"No URL"}), 400

    detected = detect_platform(url)
    job_id = str(uuid.uuid4())
    fmt_ext = CONTAINER_MAP.get(fmt,"mp4")
    audio_only = is_audio(resolution)
    if audio_only: fmt_ext = "mp4"  # cobalt gives mp4 for audio too

    progress_store[job_id] = {
        "status":"queued","percent":0,
        "filename":None,"error":None,"speed":"","eta":""
    }
    threading.Thread(
        target=_worker,
        args=(job_id,url,resolution,fmt_ext,audio_only,detected),
        daemon=True
    ).start()
    return jsonify({"job_id":job_id})

def _progress_hook(d, job_id):
    if d["status"] == "downloading":
        dl = d.get("downloaded_bytes") or 0
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        pct = round(min(dl/total*100,99),1) if total>0 else progress_store[job_id].get("percent",0)
        speed = re.sub(r'\x1b\[[0-9;]*m','',d.get("_speed_str","") or "").strip()
        eta = re.sub(r'\x1b\[[0-9;]*m','',d.get("_eta_str","") or "").strip()
        progress_store[job_id].update({"status":"downloading","percent":pct,"speed":speed,"eta":eta})
    elif d["status"] == "finished":
        progress_store[job_id].update({"percent":99,"status":"processing"})

def _worker(job_id, url, resolution, fmt_ext, audio_only, platform):
    progress_store[job_id].update({"status":"downloading","percent":5})
    audio_q = "320" if "320" in resolution else "192" if "192" in resolution else "128"

    # ── Strategy 1: cobalt.tools ──
    dl_url, title, err = try_cobalt(url, resolution, audio_only, audio_q)
    if dl_url:
        print(f"✅ cobalt success for {job_id}")
        # Detect best extension
        if audio_only:
            ext = "mp3"
        elif ".webm" in dl_url.lower():
            ext = "webm"
        else:
            ext = "mp4"
        download_url(dl_url, job_id, title or "video", ext)
        return

    print(f"⚠️  cobalt failed: {err}")

    # ── Strategy 2: yt-dlp ──
    # Use simplest possible format — no filters at all
    # YouTube Shorts use portrait orientation so height filters break
    formats_to_try = [
        "best[ext=mp4]/best[ext=webm]/best",
        "best",
        "worst[ext=mp4]/worst",
    ]
    out_tpl = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")

    clients = [
        ["tv_embedded"], ["android_vr"], ["ios"], ["android"]
    ] if platform == "youtube" else [None]

    for ydl_fmt in formats_to_try:
        for client in clients:
            try:
                opts = make_opts(platform=platform, client=client, extra={
                    "format": ydl_fmt,
                    "outtmpl": out_tpl,
                    "progress_hooks": [lambda d: _progress_hook(d,job_id)],
                    "postprocessors": [],
                    "merge_output_format": None,
                })
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    title = info.get("title","video")

                fname = next((f for f in os.listdir(DOWNLOAD_DIR) if f.startswith(job_id)), None)
                if fname:
                    progress_store[job_id].update({
                        "status":"done","percent":100,
                        "filename":fname,"title":title
                    })
                    return
            except Exception as e:
                err = str(e)
                print(f"⚠️  fmt={ydl_fmt[:20]} client={client}: {err[:60]}")
                if "private" in err.lower():
                    progress_store[job_id].update({"status":"error","error":"❌ This video is private."})
                    return
                continue

    progress_store[job_id].update({
        "status":"error",
        "error":"❌ YouTube download failed. Please try again in 1 minute."
    })

# ── 3. Progress ──
@app.route("/api/progress/<job_id>")
def progress_poll(job_id):
    info = progress_store.get(job_id)
    if not info: return jsonify({"status":"not_found","percent":0}), 404
    return jsonify(info)

# ── 4. Serve file ──
@app.route("/api/file/<job_id>")
def serve_file(job_id):
    info = progress_store.get(job_id,{})
    fname = info.get("filename")
    if not fname: return jsonify({"error":"Not ready"}), 404
    fp = os.path.join(DOWNLOAD_DIR, fname)
    if not os.path.exists(fp): return jsonify({"error":"Missing"}), 404
    safe = "".join(c if c.isalnum() or c in " ._-()" else "_" for c in info.get("title","video"))[:80]
    return send_file(fp, as_attachment=True, download_name=f"{safe}{os.path.splitext(fname)[1]}")

# ── 5. Health ──
@app.route("/api/health")
def health():
    return jsonify({
        "status":"ok",
        "yt_dlp":yt_dlp.version.__version__,
        "cookies":"✅ loaded" if cookies_ok() else "❌ missing"
    })

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
