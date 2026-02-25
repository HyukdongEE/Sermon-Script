import re
from typing import List

def segment_text(text: str, max_chars: int = 800) -> List[str]:
    """단순 세그먼트 분할:
    - 먼저 빈 줄 기준 문단 분리
    - 문단이 너무 길면 문장 단위로 추가 분리
    """
    text = (text or "").strip()
    if not text:
        return []

    # 문단 분리
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    segments: List[str] = []

    sent_split = re.compile(r"(?<=[\.!?…。])\s+|\n+")

    for p in paras:
        if len(p) <= max_chars:
            segments.append(p)
            continue

        # 문장 단위 분리 후 max_chars 내로 묶기
        sentences = [s.strip() for s in sent_split.split(p) if s.strip()]
        buf = ""
        for s in sentences:
            if not buf:
                buf = s
            elif len(buf) + 1 + len(s) <= max_chars:
                buf += " " + s
            else:
                segments.append(buf)
                buf = s
        if buf:
            segments.append(buf)

    return segments
