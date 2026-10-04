"""
Embed videos from their ORIGINAL links — nothing is downloaded or re-hosted.

    embed_info("https://youtu.be/dQw4w9WgXcQ?t=90")
    → {"kind": "iframe", "src": "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?rel=0&start=90",
       "provider": "youtube", "provider_label": "YouTube", "original": "https://youtu.be/…", …}

kind:
  iframe  — provider player (YouTube, Vimeo, Google Drive, Loom, Microsoft Stream / SharePoint, Lark / Feishu)
  video   — direct file (.mp4 / .webm / .mov …) played with <video controls>
  hls     — .m3u8 stream (native HLS or hls.js, lazy-loaded)
  link    — anything else: shown as a card with an "Open" button

Only http(s) URLs are accepted; everything else returns None.
"""

import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
VIMEO_ID = re.compile(r"^\d{4,12}$")
DRIVE_ID = re.compile(r"^[A-Za-z0-9_-]{10,200}$")
LOOM_ID = re.compile(r"^[A-Za-z0-9]{16,64}$")
TIME_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?$")

VIDEO_EXT = {"mp4": "video/mp4", "m4v": "video/mp4", "webm": "video/webm", "ogv": "video/ogg", "ogg": "video/ogg", "mov": ""}

IFRAME_ALLOW = "fullscreen; picture-in-picture; encrypted-media"

PROVIDERS = {
    "youtube": "YouTube",
    "vimeo": "Vimeo",
    "drive": "Google Drive",
    "loom": "Loom",
    "stream": "Microsoft Stream / SharePoint",
    "lark": "Lark / Feishu",
    "file": "Video file",
    "upload": "Uploaded video",
    "hls": "HLS stream",
    "link": "Link",
}

# Players that usually need the viewer to be signed in to that service.
LOGIN_PROVIDERS = {"stream", "lark", "drive"}


def _host_is(host: str, *domains: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def parse_start(value) -> int | None:
    """90 · "90" · "90s" · "1m30s" · "1h2m3s" · "01:30" · "1:02:03" → seconds."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value >= 0 else None
    text = str(value).strip().lower()
    if not text:
        return None
    if ":" in text:
        parts = text.split(":")
        if len(parts) > 3 or not all(p.isdigit() for p in parts):
            return None
        total = 0
        for p in parts:
            total = total * 60 + int(p)
        return total
    m = TIME_RE.match(text)
    if not m or not any(m.groups()):
        return None
    h, mi, s = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mi * 60 + s


def clean_url(url) -> str | None:
    """The URL if it is an absolute http(s) URL without credentials, else None."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    if not url or len(url) > 2000 or any(ord(c) < 33 for c in url):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname or "@" in parts.netloc:
        return None
    return url


def clock(seconds) -> str:
    """90 → "01:30", 3725 → "1:02:05"."""
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _result(kind, src, provider, original, start=None, end=None, **extra):
    if end is not None and start is not None and end <= start:
        end = None
    return {
        "kind": kind,
        "src": src,
        "provider": provider,
        "provider_label": PROVIDERS[provider],
        "original": original,
        "start": start,
        "end": end,
        # The part of the original video that matches the text next to it ("01:20 – 02:05").
        "segment": (f"{clock(start or 0)} – {clock(end)}" if end is not None else (f"{clock(start)} থেকে" if start else "")),
        "needs_login": provider in LOGIN_PROVIDERS,
        "allow": IFRAME_ALLOW if kind == "iframe" else "",
        **extra,
    }


def _youtube_id(host, path, query):
    if host == "youtu.be" or host.endswith(".youtu.be"):
        return path.strip("/").split("/")[0]
    if not _host_is(host, "youtube.com", "youtube-nocookie.com"):
        return None
    if path.rstrip("/") in ("/watch", "/watch_popup"):
        return (query.get("v") or [""])[0]
    m = re.match(r"^/(?:shorts|embed|live|v|e)/([^/?#]+)", path)
    return m.group(1) if m else None


def _vimeo(host, path, query):
    """(id, hash) for vimeo.com/123, vimeo.com/123/abcdef, player.vimeo.com/video/123?h=…, /channels/x/123 …"""
    if not _host_is(host, "vimeo.com"):
        return None, None
    segs = [s for s in path.split("/") if s]
    if host.startswith("player.") and len(segs) >= 2 and segs[0] == "video":
        vid = segs[1]
        return (vid if VIMEO_ID.match(vid) else None), (query.get("h") or [None])[0]
    for i, seg in enumerate(segs):
        if VIMEO_ID.match(seg):
            nxt = segs[i + 1] if i + 1 < len(segs) else None
            unlisted = nxt if nxt and re.match(r"^[0-9a-f]{6,20}$", nxt) else (query.get("h") or [None])[0]
            return seg, unlisted
    return None, None


def _drive_id(host, path, query):
    if not _host_is(host, "drive.google.com", "docs.google.com"):
        return None
    m = re.match(r"^/file/d/([^/]+)", path)
    if m:
        return m.group(1)
    if path.rstrip("/") in ("/open", "/uc"):
        return (query.get("id") or [None])[0]
    return None


def embed_info(url, start=None, end=None) -> dict | None:
    """Player info for the ORIGINAL link. start/end (seconds or "m:ss") mark the part of the
    video a step or Task Error example refers to: players that support it start there (and
    YouTube / direct files also stop at `end`); the segment is always shown as a label."""
    original = clean_url(url)
    if original is None:
        return None
    parts = urlsplit(original)
    host = (parts.hostname or "").lower()
    path = parts.path or "/"
    query = parse_qs(parts.query)
    start = parse_start(start)
    end = parse_start(end)

    # YouTube --------------------------------------------------------------
    yt = _youtube_id(host, path, query)
    if yt is not None:
        if not YOUTUBE_ID.match(yt):
            return _result("link", original, "link", original)
        if start is None:
            start = parse_start((query.get("t") or query.get("start") or [None])[0])
        params = {"rel": "0"}
        if start:
            params["start"] = str(start)
        if end and end > (start or 0):
            params["end"] = str(end)
        return _result("iframe", f"https://www.youtube-nocookie.com/embed/{yt}?{urlencode(params)}", "youtube", original, start, end,
                       video_id=yt)

    # Vimeo ----------------------------------------------------------------
    vid, vhash = _vimeo(host, path, query)
    if vid:
        params = {"h": vhash} if vhash and re.match(r"^[0-9a-f]{6,20}$", vhash) else {}
        src = f"https://player.vimeo.com/video/{vid}" + (f"?{urlencode(params)}" if params else "")
        if start is None and parts.fragment.startswith("t="):
            start = parse_start(parts.fragment[2:])
        if start:
            src += f"#t={start}s"
        return _result("iframe", src, "vimeo", original, start, end, video_id=vid, vimeo_hash=params.get("h", ""))

    # Google Drive -----------------------------------------------------------
    did = _drive_id(host, path, query)
    if did and DRIVE_ID.match(did):
        return _result("iframe", f"https://drive.google.com/file/d/{did}/preview", "drive", original, start, end)

    # Loom -------------------------------------------------------------------
    if _host_is(host, "loom.com"):
        m = re.match(r"^/(?:share|embed)/([^/?#]+)", path)
        if m and LOOM_ID.match(m.group(1)):
            if start is None:
                start = parse_start((query.get("t") or [None])[0])
            src = f"https://www.loom.com/embed/{m.group(1)}" + (f"?t={start}" if start else "")
            return _result("iframe", src, "loom", original, start, end)

    # Microsoft Stream / SharePoint / OneDrive -------------------------------
    if _host_is(host, "sharepoint.com", "microsoftstream.com", "onedrive.live.com", "1drv.ms") or host == "stream.microsoft.com":
        src = original
        m = re.match(r"^/video/([0-9a-f-]{36})", path)
        if host == "web.microsoftstream.com" and m:  # classic Stream
            src = f"https://web.microsoftstream.com/embed/video/{m.group(1)}"
        return _result("iframe", src, "stream", original, start, end)

    # Lark / Feishu ----------------------------------------------------------
    if _host_is(host, "larksuite.com", "feishu.cn", "larkoffice.com", "feishu.net", "larksuite.cn"):
        return _result("iframe", original, "lark", original, start, end)

    # Direct files / HLS -----------------------------------------------------
    ext = path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
    if ext == "m3u8":
        return _result("hls", original, "hls", original, start, end)
    if ext in VIDEO_EXT:
        src = original
        if _host_is(host, "dropbox.com"):  # share page → raw file
            q = {k: v[0] for k, v in query.items() if k != "dl"}
            q["raw"] = "1"
            src = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), ""))
        if start or (end and end > (start or 0)):
            src = src.split("#", 1)[0] + f"#t={start or 0}" + (f",{end}" if end and end > (start or 0) else "")
        return _result("video", src, "file", original, start, end, mime=VIDEO_EXT[ext], ext=ext.upper())

    return _result("link", original, "link", original, None, host=host.removeprefix("www."))


def asset_embed_info(asset, user, start=None, end=None) -> dict | None:
    """Player info for a video uploaded to our own storage (signed, per-viewer URL)."""
    from apps.storage.services import media_url

    if asset is None:
        return None
    src = media_url(asset, user)
    if not src:
        return None
    start, end = parse_start(start), parse_start(end)
    if getattr(asset, "is_hls", False):
        return _result("hls", src, "hls", "", start, end, uploaded=True)
    if start or (end and end > (start or 0)):
        src = src.split("#", 1)[0] + f"#t={start or 0}" + (f",{end}" if end and end > (start or 0) else "")
    return _result("video", src, "upload", "", start, end, mime=asset.mime_type or "", uploaded=True)


def item_video(obj, user) -> dict | None:
    """Player info for a guide step / Task Error example: its uploaded video, else its original link."""
    if getattr(obj, "video_asset_id", None):
        return asset_embed_info(obj.video_asset, user, obj.video_start, obj.video_end)
    if obj.video_url:
        return embed_info(obj.video_url, obj.video_start, obj.video_end)
    return None


def describe(info: dict | None) -> str:
    """Short English description for the admin editor ("Detected: …")."""
    if info is None:
        return "Not a valid http(s) link"
    kind, label = info["kind"], info["provider_label"]
    if kind == "iframe":
        note = " — viewers may need to be signed in to that service" if info["needs_login"] else ""
        return f"{label} · embedded player{note}"
    if kind == "video":
        return f"Direct {info.get('ext') or 'video'} file · played in the browser's video player"
    if kind == "hls":
        return "HLS stream (.m3u8) · played with native HLS or hls.js"
    return f"Not a recognised video link ({info.get('host') or 'link'}) · shown as an Open button"
