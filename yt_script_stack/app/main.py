from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from datetime import datetime
from typing import Optional

from .db import db_conn
from .settings import admin_token
from .llm import clean_text_no_summarize
from .segmenter import segment_text

app = FastAPI(title="yt_script_stack")
templates = Jinja2Templates(directory="app/templates")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

def _check_token(token: Optional[str]):
    if token != admin_token():
        # no detail for security
        raise PermissionError("Invalid token")

@app.get("/healthz")
def healthz():
    return {"ok": True, "time": datetime.utcnow().isoformat() + "Z"}

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})

@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, token: str):
    _check_token(token)
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("""SELECT video_id, title, published_at, url, status
                       FROM videos
                       ORDER BY published_at DESC NULLS LAST, fetched_at DESC
                       LIMIT 200""")
        videos = cur.fetchall()
    return templates.TemplateResponse("admin.html", {"request": request, "token": token, "videos": videos})

@app.get("/admin/video/{video_id}", response_class=HTMLResponse)
def admin_video(request: Request, video_id: str, token: str):
    _check_token(token)
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("""SELECT video_id, title, published_at, url, status, description
                       FROM videos WHERE video_id=%s""", (video_id,))
        video = cur.fetchone()
        if not video:
            return HTMLResponse("Video not found", status_code=404)

        cur.execute("""SELECT transcript_id, source, version, created_at
                       FROM transcripts WHERE video_id=%s
                       ORDER BY version DESC, created_at DESC""", (video_id,))
        transcripts = cur.fetchall()

    return templates.TemplateResponse(
        "video_detail.html",
        {"request": request, "token": token, "video": video, "transcripts": transcripts},
    )

@app.post("/admin/video/{video_id}/transcript")
def add_transcript(video_id: str, token: str, raw_text: str = Form(...), source: str = Form("manual_paste")):
    _check_token(token)
    raw_text = (raw_text or "").strip()
    if not raw_text:
        return RedirectResponse(url=f"/admin/video/{video_id}?token={token}", status_code=303)

    with db_conn() as conn:
        cur = conn.cursor()
        # determine next version
        cur.execute("""SELECT COALESCE(MAX(version),0)+1 AS next_version
                       FROM transcripts WHERE video_id=%s AND source=%s""", (video_id, source))
        next_version = cur.fetchone()["next_version"]

        cur.execute("""INSERT INTO transcripts (video_id, source, version, raw_text, cleaned_text, created_at, updated_at)
                       VALUES (%s,%s,%s,%s,NULL, now(), now())
                       RETURNING transcript_id""", (video_id, source, next_version, raw_text))
        transcript_id = cur.fetchone()["transcript_id"]

        # enqueue jobs: CLEAN then SEGMENT
        cur.execute("""INSERT INTO jobs (job_type, status, payload, created_at, updated_at)
                       VALUES
                       ('CLEAN','PENDING', %s::jsonb, now(), now()),
                       ('SEGMENT','PENDING', %s::jsonb, now(), now())""",
                    (f'{{"transcript_id": {transcript_id}}}', f'{{"transcript_id": {transcript_id}}}'))

        # update video status
        cur.execute("""UPDATE videos SET status='TEXT_ADDED' WHERE video_id=%s""", (video_id,))

    return RedirectResponse(url=f"/admin/video/{video_id}?token={token}", status_code=303)

@app.post("/admin/run-jobs")
def run_jobs_now(token: str, batch: int = Form(10)):
    _check_token(token)
    processed = _run_jobs(batch=batch)
    return JSONResponse({"processed": processed})

@app.get("/search")
def search(q: str, limit: int = 20):
    q = (q or "").strip()
    if not q:
        return {"q": q, "results": []}
    limit = max(1, min(100, limit))

    with db_conn() as conn:
        cur = conn.cursor()
        # pg_trgm 퍼지 검색(% 연산자) + fallback ILIKE
        cur.execute("""
        SELECT
          s.segment_id,
          s.video_id,
          v.title,
          v.url,
          s.chunk_index,
          s.cleaned_text,
          similarity(s.cleaned_text, %s) AS sim
        FROM segments s
        JOIN videos v ON v.video_id = s.video_id
        WHERE
          (s.cleaned_text ILIKE '%%' || %s || '%%')
          OR (similarity(s.cleaned_text, %s) > 0.12)
        ORDER BY sim DESC NULLS LAST, v.published_at DESC NULLS LAST
        LIMIT %s
        """, (q, q, q, limit))
        rows = cur.fetchall()

    results = []
    for r in rows:
        results.append({
            "segment_id": r["segment_id"],
            "video_id": r["video_id"],
            "title": r["title"],
            "url": r["url"],
            "chunk_index": r["chunk_index"],
            "snippet": r["cleaned_text"][:400],
            "similarity": float(r["sim"]) if r["sim"] is not None else None,
        })
    return {"q": q, "results": results}

@app.get("/search-ui", response_class=HTMLResponse)
def search_ui(request: Request, token: str, q: str = ""):
    _check_token(token)
    data = {"q": q, "results": []}
    if q.strip():
        data = search(q=q, limit=30)
    return templates.TemplateResponse("search_ui.html", {"request": request, "token": token, **data})

def _run_jobs(batch: int = 10) -> int:
    """jobs 테이블에서 PENDING을 batch만큼 꺼내 처리"""
    processed = 0
    with db_conn() as conn:
        cur = conn.cursor()
        # lock rows to avoid concurrent runs
        cur.execute("""
            SELECT job_id, job_type, payload
            FROM jobs
            WHERE status='PENDING'
            ORDER BY created_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT %s
        """, (batch,))
        jobs = cur.fetchall()

        for job in jobs:
            job_id = job["job_id"]
            job_type = job["job_type"]
            payload = job["payload"]

            # mark running
            cur.execute("""UPDATE jobs SET status='RUNNING', updated_at=now(), attempt=attempt+1 WHERE job_id=%s""", (job_id,))

            try:
                if job_type == "CLEAN":
                    _job_clean(conn, payload)
                elif job_type == "SEGMENT":
                    _job_segment(conn, payload)
                else:
                    raise RuntimeError(f"Unknown job_type: {job_type}")

                cur.execute("""UPDATE jobs SET status='DONE', updated_at=now(), last_error=NULL WHERE job_id=%s""", (job_id,))
                processed += 1
            except Exception as e:
                cur.execute("""UPDATE jobs SET status='FAILED', updated_at=now(), last_error=%s WHERE job_id=%s""", (str(e)[:2000], job_id))
        # commit handled by context manager
    return processed

def _job_clean(conn, payload: dict):
    transcript_id = int(payload["transcript_id"])
    cur = conn.cursor()
    cur.execute("""SELECT transcript_id, video_id, raw_text, cleaned_text FROM transcripts WHERE transcript_id=%s""", (transcript_id,))
    tr = cur.fetchone()
    if not tr:
        raise RuntimeError(f"Transcript not found: {transcript_id}")

    cleaned = clean_text_no_summarize(tr["raw_text"])

    # simple quality guard: avoid extreme length change
    raw_len = len(tr["raw_text"])
    cleaned_len = len(cleaned)
    if raw_len > 0:
        ratio = cleaned_len / raw_len
        if ratio < 0.7 or ratio > 1.3:
            # still store but mark as potential issue
            pass

    cur.execute("""UPDATE transcripts SET cleaned_text=%s, updated_at=now() WHERE transcript_id=%s""", (cleaned, transcript_id))
    cur.execute("""UPDATE videos SET status='CLEANED' WHERE video_id=%s AND status IN ('TEXT_ADDED','DISCOVERED','CLEANED')""", (tr["video_id"],))

def _job_segment(conn, payload: dict):
    transcript_id = int(payload["transcript_id"])
    cur = conn.cursor()
    cur.execute("""SELECT transcript_id, video_id, raw_text, cleaned_text FROM transcripts WHERE transcript_id=%s""", (transcript_id,))
    tr = cur.fetchone()
    if not tr:
        raise RuntimeError(f"Transcript not found: {transcript_id}")

    text = tr["cleaned_text"] or tr["raw_text"]
    segs = segment_text(text)

    # clear existing segments for this transcript (idempotent)
    cur.execute("""DELETE FROM segments WHERE transcript_id=%s""", (transcript_id,))

    for idx, seg in enumerate(segs):
        cur.execute("""INSERT INTO segments (transcript_id, video_id, chunk_index, start_ms, end_ms, raw_text, cleaned_text, embedding, created_at)
                       VALUES (%s,%s,%s,NULL,NULL,NULL,%s,NULL, now())""", (transcript_id, tr["video_id"], idx, seg))

    cur.execute("""UPDATE videos SET status='INDEXED' WHERE video_id=%s""", (tr["video_id"],))

import os
import subprocess
from fastapi import HTTPException
from starlette.responses import JSONResponse

@app.get("/admin/collect")
def admin_collect(token: str, max_pages: int = 1, channel_id: str | None = None):
    # 1) 관리자 토큰 검사
    admin_token = os.getenv("ADMIN_TOKEN")
    if not admin_token or token != admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # 2) 환경변수 확인
    yt_key = os.getenv("YOUTUBE_API_KEY")
    db_url = os.getenv("DATABASE_URL")

    # channel_id는 (a) URL 파라미터로 받거나 (b) ENV CHANNEL_ID 사용
    ch_id = channel_id or os.getenv("CHANNEL_ID")

    if not yt_key:
        raise HTTPException(status_code=400, detail="Missing YOUTUBE_API_KEY")
    if not db_url:
        raise HTTPException(status_code=400, detail="Missing DATABASE_URL")
    if not ch_id:
        raise HTTPException(status_code=400, detail="Missing CHANNEL_ID (env) or channel_id (param)")

    # 3) 기존 수집 스크립트를 서버가 실행
    env = os.environ.copy()
    env["YOUTUBE_API_KEY"] = yt_key
    env["DATABASE_URL"] = db_url

    cmd = [
        "python", "-m", "scripts.collect_channel",
        "--channel-id", ch_id,
        "--max-pages", str(max_pages),
    ]

    try:
        p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="collect timed out (try smaller max_pages)")

    if p.returncode != 0:
        # stderr 마지막 일부만 보여주기
        err_tail = (p.stderr or "")[-1200:]
        raise HTTPException(status_code=500, detail=f"collect failed: {err_tail}")

    out_tail = (p.stdout or "")[-1200:]
    return JSONResponse({"ok": True, "channel_id": ch_id, "max_pages": max_pages, "stdout_tail": out_tail})