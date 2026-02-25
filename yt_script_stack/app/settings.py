import os

def admin_token() -> str:
    token = os.getenv("ADMIN_TOKEN")
    if not token:
        raise RuntimeError("ADMIN_TOKEN is not set")
    return token

def llm_provider() -> str:
    return (os.getenv("LLM_PROVIDER") or "none").strip().lower()

def youtube_api_key() -> str | None:
    return os.getenv("YOUTUBE_API_KEY")

def gemini_api_key() -> str | None:
    return os.getenv("GEMINI_API_KEY")

def openai_api_key() -> str | None:
    return os.getenv("OPENAI_API_KEY")
