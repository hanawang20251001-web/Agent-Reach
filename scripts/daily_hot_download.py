#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Download daily top videos from YouTube trending and Bilibili popular.

Usage examples:
  python scripts/daily_hot_download.py
  python scripts/daily_hot_download.py --top 10 --dry-run
  python scripts/daily_hot_download.py --cookies-from-browser chrome
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import requests


YOUTUBE_TRENDING_URL = "https://www.youtube.com/feed/trending"
BILIBILI_POPULAR_API = "https://api.bilibili.com/x/web-interface/popular"


def _run(cmd: List[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def ensure_yt_dlp() -> None:
    result = _run(["yt-dlp", "--version"])
    if result.returncode != 0:
        raise RuntimeError(
            "yt-dlp is required but not found. Install with: python -m pip install yt-dlp"
        )


def fetch_youtube_top(top_n: int, cookies_from_browser: str | None, proxy: str | None) -> List[Dict[str, Any]]:
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-single-json",
        "--playlist-end",
        str(top_n),
        "--proxy",
        proxy or "",
        YOUTUBE_TRENDING_URL,
    ]
    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])

    result = _run(cmd)
    if result.returncode != 0:
        raise RuntimeError(
            "Failed to fetch YouTube trending list.\n"
            f"Command: {' '.join(cmd)}\n"
            f"stderr: {result.stderr.strip()}"
        )
    payload = json.loads(result.stdout)
    entries = payload.get("entries", []) or []

    videos: List[Dict[str, Any]] = []
    for idx, item in enumerate(entries[:top_n], start=1):
        video_id = item.get("id")
        if not video_id:
            continue
        videos.append(
            {
                "rank": idx,
                "platform": "youtube",
                "id": video_id,
                "title": item.get("title", ""),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "duration": item.get("duration"),
            }
        )
    return videos


def fetch_bilibili_top(top_n: int, proxy: str | None) -> List[Dict[str, Any]]:
    session = requests.Session()
    # Avoid inherited broken system proxy. Users can still pass --proxy explicitly.
    session.trust_env = False
    proxies = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}
    response = session.get(
        BILIBILI_POPULAR_API,
        params={"pn": 1, "ps": top_n},
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0 Agent-Reach-Hot-Task"},
        proxies=proxies,
    )
    response.raise_for_status()
    payload = response.json()

    if payload.get("code") != 0:
        raise RuntimeError(f"Bilibili API error: code={payload.get('code')} msg={payload.get('message')}")

    data_list = (payload.get("data") or {}).get("list") or []
    videos: List[Dict[str, Any]] = []
    for idx, item in enumerate(data_list[:top_n], start=1):
        bvid = item.get("bvid")
        if not bvid:
            continue
        url = f"https://www.bilibili.com/video/{bvid}"
        videos.append(
            {
                "rank": idx,
                "platform": "bilibili",
                "id": bvid,
                "title": item.get("title", ""),
                "url": url,
                "duration": item.get("duration"),
            }
        )
    return videos


def write_manifest(output_dir: Path, manifest: Dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _build_playlist_items(youtube: List[Dict[str, Any]], bilibili: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Interleave by rank: Y1, B1, Y2, B2...
    items: List[Dict[str, Any]] = []
    max_len = max(len(youtube), len(bilibili)) if (youtube or bilibili) else 0
    for i in range(max_len):
        if i < len(youtube):
            items.append(youtube[i])
        if i < len(bilibili):
            items.append(bilibili[i])
    return items


def write_playlist_page(output_dir: Path, manifest: Dict[str, Any]) -> Path:
    playlist_items = _build_playlist_items(manifest.get("youtube", []), manifest.get("bilibili", []))
    playlist_json = json.dumps(playlist_items, ensure_ascii=False)

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Daily Hot Playlist - {manifest.get("date", "")}</title>
  <style>
    :root {{
      --bg: #0f172a;
      --card: #111827;
      --text: #f3f4f6;
      --muted: #9ca3af;
      --accent: #22d3ee;
      --line: #1f2937;
    }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background: radial-gradient(1200px 700px at 10% 10%, #1f2937 0%, var(--bg) 55%);
      color: var(--text);
    }}
    .wrap {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 20px;
      display: grid;
      grid-template-columns: 1.5fr 1fr;
      gap: 16px;
    }}
    .card {{
      background: color-mix(in srgb, var(--card) 90%, black);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 14px;
    }}
    .player {{
      width: 100%;
      aspect-ratio: 16 / 9;
      border: 0;
      border-radius: 10px;
      background: black;
    }}
    .topbar {{
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 10px;
    }}
    button {{
      border: 1px solid var(--line);
      background: #0b1220;
      color: var(--text);
      border-radius: 8px;
      padding: 8px 12px;
      cursor: pointer;
    }}
    button:hover {{
      border-color: var(--accent);
    }}
    .meta {{
      color: var(--muted);
      font-size: 13px;
    }}
    .list {{
      max-height: 72vh;
      overflow: auto;
      display: grid;
      gap: 8px;
    }}
    .item {{
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
      cursor: pointer;
    }}
    .item.active {{
      border-color: var(--accent);
      box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 60%, white);
    }}
    .item .platform {{
      color: var(--accent);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .item .title {{
      margin-top: 4px;
      line-height: 1.35;
    }}
    @media (max-width: 960px) {{
      .wrap {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="card">
      <div class="topbar">
        <button id="prevBtn">上一条</button>
        <button id="nextBtn">下一条</button>
        <button id="toggleBtn">暂停自动播放</button>
        <span class="meta" id="status"></span>
      </div>
      <div id="ytPlayerHost" class="player" style="display:none"></div>
      <iframe id="biliPlayer" class="player" style="display:none" allow="autoplay; fullscreen"></iframe>
      <div class="meta" style="margin-top:8px" id="currentMeta"></div>
    </section>
    <aside class="card">
      <h3 style="margin:0 0 10px 0">播放列表（YouTube + B站）</h3>
      <div class="meta" style="margin-bottom:10px">日期：{manifest.get("date", "")}，总数：{len(playlist_items)}</div>
      <div class="list" id="playlist"></div>
    </aside>
  </div>

  <script src="https://www.youtube.com/iframe_api"></script>
  <script>
    const playlist = {playlist_json};
    let index = 0;
    let autoPlay = true;
    let ytPlayer = null;
    let fallbackTimer = null;

    const listEl = document.getElementById('playlist');
    const statusEl = document.getElementById('status');
    const metaEl = document.getElementById('currentMeta');
    const ytHost = document.getElementById('ytPlayerHost');
    const biliFrame = document.getElementById('biliPlayer');

    function fmtPlatform(p) {{
      return p === 'youtube' ? 'YouTube' : 'Bilibili';
    }}

    function clearTimer() {{
      if (fallbackTimer) {{
        clearTimeout(fallbackTimer);
        fallbackTimer = null;
      }}
    }}

    function renderList() {{
      listEl.innerHTML = '';
      playlist.forEach((item, i) => {{
        const div = document.createElement('div');
        div.className = 'item' + (i === index ? ' active' : '');
        div.onclick = () => playAt(i);
        const dur = item.duration ? `时长约 ${{item.duration}} 秒` : '时长未知';
        div.innerHTML = `
          <div class="platform">${{fmtPlatform(item.platform)}} #${{item.rank}}</div>
          <div class="title">${{item.title || '(无标题)'}} </div>
          <div class="meta">${{item.id}} · ${{dur}}</div>
        `;
        listEl.appendChild(div);
      }});
    }}

    function updateMeta(item) {{
      const dur = item.duration ? `时长约 ${{item.duration}} 秒` : '时长未知';
      statusEl.textContent = `第 ${{index + 1}} / ${{playlist.length}} 条`;
      metaEl.textContent = `${{fmtPlatform(item.platform)}} · ${{item.id}} · ${{dur}}`;
    }}

    function scheduleFallbackNext(item) {{
      clearTimer();
      if (!autoPlay) return;
      const seconds = Math.max(20, Number(item.duration || 120));
      fallbackTimer = setTimeout(() => next(), (seconds + 3) * 1000);
    }}

    function playBilibili(item) {{
      if (ytPlayer && ytPlayer.stopVideo) ytPlayer.stopVideo();
      ytHost.style.display = 'none';
      biliFrame.style.display = 'block';
      biliFrame.src = `https://player.bilibili.com/player.html?bvid=${{encodeURIComponent(item.id)}}&autoplay=1`;
      scheduleFallbackNext(item);
    }}

    function playYouTube(item) {{
      biliFrame.style.display = 'none';
      biliFrame.src = '';
      ytHost.style.display = 'block';
      clearTimer();
      if (!ytPlayer) {{
        ytPlayer = new YT.Player('ytPlayerHost', {{
          videoId: item.id,
          playerVars: {{ autoplay: 1, rel: 0 }},
          events: {{
            onStateChange: function(ev) {{
              if (ev.data === YT.PlayerState.ENDED && autoPlay) next();
            }}
          }}
        }});
      }} else {{
        ytPlayer.loadVideoById(item.id);
      }}
    }}

    function playAt(i) {{
      if (!playlist.length) return;
      index = (i + playlist.length) % playlist.length;
      const item = playlist[index];
      updateMeta(item);
      renderList();
      if (item.platform === 'youtube') playYouTube(item);
      else playBilibili(item);
    }}

    function next() {{
      playAt(index + 1);
    }}
    function prev() {{
      playAt(index - 1);
    }}

    window.onYouTubeIframeAPIReady = function() {{
      if (playlist.length) playAt(0);
      else {{
        statusEl.textContent = '播放列表为空（请先成功抓取榜单）';
      }}
    }};

    document.getElementById('nextBtn').onclick = next;
    document.getElementById('prevBtn').onclick = prev;
    document.getElementById('toggleBtn').onclick = function() {{
      autoPlay = !autoPlay;
      this.textContent = autoPlay ? '暂停自动播放' : '恢复自动播放';
      if (!autoPlay) clearTimer();
      else if (playlist[index] && playlist[index].platform === 'bilibili') scheduleFallbackNext(playlist[index]);
    }};
  </script>
</body>
</html>
"""

    path = output_dir / "playlist.html"
    path.write_text(html, encoding="utf-8")
    return path


def download_video(
    url: str, platform_dir: Path, cookies_from_browser: str | None, proxy: str | None
) -> tuple[bool, str]:
    platform_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(platform_dir / "%(upload_date)s_%(id)s_%(title).180B.%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-overwrites",
        "--merge-output-format",
        "mp4",
        "--proxy",
        proxy or "",
        "-o",
        output_template,
        url,
    ]
    if cookies_from_browser and "youtube.com" in url:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])
    result = _run(cmd)
    if result.returncode == 0:
        return True, ""
    return False, (result.stderr.strip() or result.stdout.strip())[-1000:]


def parse_args() -> argparse.Namespace:
    today = dt.date.today().isoformat()
    default_output = Path.cwd() / "downloads" / "daily_hot" / today
    parser = argparse.ArgumentParser(
        description="Fetch YouTube/Bilibili daily hot top videos and download to local."
    )
    parser.add_argument("--top", type=int, default=10, help="Top N videos per platform (default: 10)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_output,
        help=f"Output directory (default: {default_output})",
    )
    parser.add_argument(
        "--cookies-from-browser",
        default=None,
        help="Browser name for yt-dlp cookies (e.g. chrome/firefox/edge), optional",
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help="Optional proxy URL, e.g. http://user:pass@host:port (default: disable system proxy)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Fetch list only, do not download")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.top <= 0:
        raise SystemExit("--top must be > 0")

    ensure_yt_dlp()

    fetch_errors: Dict[str, str] = {}

    print(f"[1/4] Fetching YouTube trending top {args.top}...")
    yt_videos: List[Dict[str, Any]] = []
    try:
        yt_videos = fetch_youtube_top(args.top, args.cookies_from_browser, args.proxy)
        print(f"  YouTube items: {len(yt_videos)}")
    except Exception as exc:
        fetch_errors["youtube"] = str(exc)
        print(f"  YouTube fetch failed: {exc}")

    print(f"[2/4] Fetching Bilibili popular top {args.top}...")
    bili_videos: List[Dict[str, Any]] = []
    try:
        bili_videos = fetch_bilibili_top(args.top, args.proxy)
        print(f"  Bilibili items: {len(bili_videos)}")
    except Exception as exc:
        fetch_errors["bilibili"] = str(exc)
        print(f"  Bilibili fetch failed: {exc}")

    manifest: Dict[str, Any] = {
        "date": dt.date.today().isoformat(),
        "top": args.top,
        "youtube": yt_videos,
        "bilibili": bili_videos,
        "fetch_errors": fetch_errors,
        "download_results": {"youtube": [], "bilibili": []},
    }

    manifest_path = write_manifest(args.output_dir, manifest)
    playlist_path = write_playlist_page(args.output_dir, manifest)
    print(f"[3/4] Manifest written: {manifest_path}")
    print(f"      Playlist page: {playlist_path}")

    if args.dry_run:
        print("[4/4] Dry run enabled. Skip downloads.")
        if not yt_videos and not bili_videos:
            return 1
        return 0

    print("[4/4] Downloading videos...")
    for platform, videos in (("youtube", yt_videos), ("bilibili", bili_videos)):
        pdir = args.output_dir / platform
        for item in videos:
            ok, err = download_video(item["url"], pdir, args.cookies_from_browser, args.proxy)
            result = {"rank": item["rank"], "id": item["id"], "url": item["url"], "ok": ok}
            if err:
                result["error"] = err
            manifest["download_results"][platform].append(result)
            status = "ok" if ok else "failed"
            print(f"  [{platform}] #{item['rank']} {item['id']} -> {status}")

    write_manifest(args.output_dir, manifest)
    print(f"Done. Final manifest: {manifest_path}")
    if not yt_videos and not bili_videos:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
