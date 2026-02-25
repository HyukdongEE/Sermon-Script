import argparse
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Iterable

import requests
from dateutil import parser as dateparser

from app.db import db_conn
from app.settings import youtube_api_key

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

def yt_get(api_key: str, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{YOUTUBE_API_BASE}/{path}"
    params = dict(params)
    params["key"] = api_key
    resp = requests.get(url, params=params, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"YouTube API error {resp.status_code}: {resp.text}")
    return resp.json()

def get_uploads_playlist_id(api_key: str, channel_id: str) -> str:
    data = yt_get(api_key, "channels", {"part": "contentDetails", "id": channel_id, "maxResults": 1})
    items = data.get("items", [])
    if not items:
        raise RuntimeError(f"Channel not found: {channel_id}")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

def iter_playlist_video_ids(api_key: str, playlist_id: str, max_pages: Optional[int] = None) -> Iterable[str]:
    page_token = None
    pages = 0
    while True:
        params = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": 50}
        if page_token:
            params["pageToken"] = page_token
        data = yt_get(api_key, "playlistItems", params)
        for item in data.get("items", []):
            vid = item["contentDetails"].get("videoId")
            if vid:
                yield vid
        page_token = data.get("nextPageToken")
        pages += 1
        if not page_token:
            break
        if max_pages is not None and pages >= max_pages:
            break
        time.sleep(0.1)

def fetch_videos_details(api_key: str, ids: List[str]) -> List[Dict[str, Any]]:
    if not ids:
        return []
    data = yt_get(api_key, "videos", {"part": "snippet", "id": ",".join(ids), "maxResults": 50})
    out = []
    now = datetime.utcnow().isoformat() + "Z"
    for item in data.get("items", []):
        sn = item.get("snippet", {})
        published_at = sn.get("publishedAt")
        out.append({
            "video_id": item["id"],
            "channel_id": sn.get("channelId"),
            "title": sn.get("title"),
            "description": sn.get("description"),
            "published_at": published_at,
            "url": f"https://www.youtube.com/watch?v={item['id']}",
            "fetched_at": now,
        })
    return out

def upsert(conn, video: Dict[str, Any]):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO videos (video_id, channel_id, title, description, published_at, url, fetched_at, status)
        VALUES (%s,%s,%s,%s,%s,%s, now(), 'DISCOVERED')
        ON CONFLICT(video_id) DO UPDATE SET
          channel_id=EXCLUDED.channel_id,
          title=EXCLUDED.title,
          description=EXCLUDED.description,
          published_at=EXCLUDED.published_at,
          url=EXCLUDED.url,
          fetched_at=now()
        """,
        (video["video_id"], video["channel_id"], video["title"], video["description"], video["published_at"], video["url"]),
    )

def attach_source(conn, channel_id: str, video_id: str):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO sources (source_type, source_value, video_id)
        VALUES ('channel', %s, %s)
        ON CONFLICT (source_type, source_value, video_id) DO NOTHING
        """,
        (channel_id, video_id),
    )

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel-id", required=True, help="UC....")
    ap.add_argument("--max-pages", type=int, default=None, help="Limit playlistItems pages (50 videos/page)")
    args = ap.parse_args()

    api_key = youtube_api_key()
    if not api_key:
        raise SystemExit("YOUTUBE_API_KEY is not set")

    uploads = get_uploads_playlist_id(api_key, args.channel_id)

    buffer: List[str] = []
    count = 0

    with db_conn() as conn:
        for vid in iter_playlist_video_ids(api_key, uploads, max_pages=args.max_pages):
            buffer.append(vid)
            if len(buffer) >= 50:
                details = fetch_videos_details(api_key, buffer)
                for v in details:
                    upsert(conn, v)
                    attach_source(conn, args.channel_id, v["video_id"])
                count += len(details)
                buffer = []
        if buffer:
            details = fetch_videos_details(api_key, buffer)
            for v in details:
                upsert(conn, v)
                attach_source(conn, args.channel_id, v["video_id"])
            count += len(details)

    print(f"[OK] collected/upserted {count} videos for channel {args.channel_id}")

if __name__ == "__main__":
    main()
