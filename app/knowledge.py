"""knowledge/ 디렉터리의 마크다운 파일을 읽어 시스템 프롬프트용 지식으로 합칩니다.

파일명 순서(00_, 01_, ...)대로 연결되며, 서버 시작 시 1회 로드됩니다.
지식을 수정한 뒤에는 서버를 재시작하세요.
"""

import logging
from pathlib import Path

logger = logging.getLogger("kakao-claude-bot")

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"


def load_knowledge() -> str:
    if not KNOWLEDGE_DIR.is_dir():
        logger.warning("knowledge/ 디렉터리가 없습니다 — 지식 없이 동작합니다.")
        return ""

    sections = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        if text:
            sections.append(text)

    logger.info("병원 지식 로드 완료: %d개 문서", len(sections))
    return "\n\n---\n\n".join(sections)
