import json
import re
import requests
from typing import Optional
from .settings import llm_provider, gemini_api_key, openai_api_key

def _normalize_whitespace(text: str) -> str:
    # 최소한의 정리(공백/줄바꿈)
    text = text.replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def clean_text_no_summarize(text: str) -> str:
    """요약 없이 오타/띄어쓰기/문장부호만 교정.
    - LLM_PROVIDER=none이면 원문을 가볍게 normalize만 하고 반환
    - gemini/openai면 LLM 호출 (비용 발생 가능)
    """
    provider = llm_provider()
    text = _normalize_whitespace(text)

    if provider == "none":
        return text

    if provider == "gemini":
        key = gemini_api_key()
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        return _clean_with_gemini(text, key)

    if provider == "openai":
        key = openai_api_key()
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        return _clean_with_openai(text, key)

    raise RuntimeError(f"Unknown LLM_PROVIDER: {provider}")

def _clean_with_gemini(text: str, api_key: str) -> str:
    # Gemini generateContent REST
    # https://ai.google.dev/api/generate-content
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
    headers = {"Content-Type": "application/json"}
    prompt = (
        "당신은 한국어 문장 교정 도구입니다.\n"
        "아래 텍스트를 '요약 없이' 그대로 유지하되, 오타/띄어쓰기/문장부호만 자연스럽게 교정하세요.\n"
        "- 문장/내용을 추가하거나 삭제하지 마세요.\n"
        "- 숫자/고유명사/사실관계는 변경하지 마세요.\n"
        "- 출력은 교정된 '전문 텍스트'만 반환하세요.\n\n"
        f"원문:\n{text}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.9,
            "maxOutputTokens": 8192
        }
    }
    resp = requests.post(url, params={"key": api_key}, headers=headers, data=json.dumps(payload), timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini error {resp.status_code}: {resp.text}")
    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        raise RuntimeError(f"Gemini response parse failed: {data}")

def _clean_with_openai(text: str, api_key: str) -> str:
    # OpenAI Responses API
    # https://developers.openai.com/api/docs/guides/migrate-to-responses/
    url = "https://api.openai.com/v1/responses"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    instructions = (
        "You are a Korean proofreading tool. "
        "Correct typos, spacing, and punctuation without summarizing. "
        "Do NOT add or delete sentences. Do NOT change facts, numbers, or proper nouns. "
        "Return only the corrected full text."
    )
    payload = {
        "model": "gpt-4.1-mini",
        "input": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": text}
        ],
        "temperature": 0.2
    }
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"OpenAI error {resp.status_code}: {resp.text}")
    data = resp.json()
    # Responses API output parsing
    try:
        # Find first output_text
        for item in data.get("output", []):
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") == "output_text":
                        return c.get("text", "").strip()
        # fallback legacy
        return data["output_text"].strip()
    except Exception:
        raise RuntimeError(f"OpenAI response parse failed: {data}")
