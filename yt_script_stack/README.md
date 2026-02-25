# yt_script_stack (MVP)

무료 티어(또는 최소 비용)로 시작하는:
- YouTube 링크 자동 수집(공식 YouTube Data API)
- 스크립트는 수작업으로 붙여넣기/업로드
- (선택) LLM로 '요약 없이' 오타/띄어쓰기/문장부호 교정
- 텍스트를 청크(segments)로 나눠 DB에 저장
- 퍼지(유사 문자열) 검색으로 관련 영상/청크 찾기

권장 무료 조합:
- DB: Neon Postgres (pg_trgm, vector 확장)
- 런타임: Render Web Service (무료면 sleep/콜드스타트 있음)
- 배치/자동화: GitHub Actions cron (링크 수집 + jobs 처리)

## 1) 환경변수

필수:
- DATABASE_URL: Neon이 제공하는 Postgres 접속 문자열 (sslmode=require 포함 권장)
- ADMIN_TOKEN: 관리자 페이지 접근 토큰 (임의의 긴 문자열)

선택:
- YOUTUBE_API_KEY: 링크 수집 시 필요
- LLM_PROVIDER: none | gemini | openai (기본 none)
- GEMINI_API_KEY / OPENAI_API_KEY: LLM_PROVIDER 선택 시 필요

## 2) DB 스키마 설치

Neon SQL Editor에서 `migrations/001_init.sql` 실행.

## 3) 로컬 실행

```bash
pip install -r requirements.txt
export DATABASE_URL="..."
export ADMIN_TOKEN="..."
uvicorn app.main:app --reload
```

## 4) 링크 수집 (채널 업로드 전체)

```bash
export YOUTUBE_API_KEY="..."
python -m scripts.collect_channel --channel-id UCxxxx --max-pages 50
```

## 5) 스크립트 입력

브라우저:
- `/admin?token=ADMIN_TOKEN` 접속 → 영상 선택 → 텍스트 붙여넣기 → 저장

저장되면 jobs가 쌓이며, jobs는 다음으로 처리됩니다.

## 6) jobs 처리(정제/청킹)

```bash
python -m scripts.run_jobs --batch 10
```

또는 GitHub Actions workflows 사용 (Secrets에 DATABASE_URL 등 등록).

## 7) 검색

- JSON API: `/search?q=키워드`
- 간단 UI: `/search-ui?token=ADMIN_TOKEN`
