-- 001_init.sql
-- Neon SQL Editor에서 실행하세요.

-- Extensions (가능한 경우)
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

-- Videos: 발견된 영상(링크/메타데이터)
CREATE TABLE IF NOT EXISTS videos (
  video_id TEXT PRIMARY KEY,
  channel_id TEXT,
  title TEXT,
  description TEXT,
  published_at TIMESTAMPTZ,
  url TEXT NOT NULL,
  fetched_at TIMESTAMPTZ DEFAULT now(),
  status TEXT NOT NULL DEFAULT 'DISCOVERED' -- DISCOVERED | TEXT_ADDED | CLEANED | INDEXED
);

-- Sources: 영상이 어디서 수집됐는지(채널/플레이리스트/검색어)
CREATE TABLE IF NOT EXISTS sources (
  source_id BIGSERIAL PRIMARY KEY,
  source_type TEXT NOT NULL,      -- channel | playlist | search
  source_value TEXT NOT NULL,     -- UC... | PL... | query string
  video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(source_type, source_value, video_id)
);

-- Transcripts: 수작업 입력된 원문/정제본(버전)
CREATE TABLE IF NOT EXISTS transcripts (
  transcript_id BIGSERIAL PRIMARY KEY,
  video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
  source TEXT NOT NULL DEFAULT 'manual_paste', -- manual_paste | manual_upload
  version INT NOT NULL DEFAULT 1,
  raw_text TEXT NOT NULL,
  cleaned_text TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(video_id, source, version)
);

-- Segments: 검색 단위(청크)
CREATE TABLE IF NOT EXISTS segments (
  segment_id BIGSERIAL PRIMARY KEY,
  transcript_id BIGINT NOT NULL REFERENCES transcripts(transcript_id) ON DELETE CASCADE,
  video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
  chunk_index INT NOT NULL,
  start_ms INT,
  end_ms INT,
  raw_text TEXT,
  cleaned_text TEXT NOT NULL,
  -- 추후 의미 기반 검색용(지금은 NULL 가능)
  embedding vector(3072),
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(transcript_id, chunk_index)
);

-- Jobs: 백그라운드 작업 큐(무료티어에서는 GitHub Actions/수동 실행으로 처리)
CREATE TABLE IF NOT EXISTS jobs (
  job_id BIGSERIAL PRIMARY KEY,
  job_type TEXT NOT NULL,               -- CLEAN | SEGMENT
  status TEXT NOT NULL DEFAULT 'PENDING', -- PENDING | RUNNING | DONE | FAILED
  payload JSONB NOT NULL,
  attempt INT NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_videos_published_at ON videos(published_at DESC);

-- 퍼지 검색 인덱스 (pg_trgm)
CREATE INDEX IF NOT EXISTS idx_segments_cleaned_trgm ON segments USING GIN (cleaned_text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_videos_title_trgm ON videos USING GIN (title gin_trgm_ops);

-- 상태 업데이트 helper (optional)
