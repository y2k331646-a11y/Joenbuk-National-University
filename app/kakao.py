"""카카오 i 오픈빌더 스킬 응답(v2.0) 생성 헬퍼."""

# simpleText 1개당 최대 글자 수 (오픈빌더 제한: 1,000자)
SIMPLE_TEXT_LIMIT = 1000
# 한 응답에 담을 수 있는 출력 블록 수 (오픈빌더 제한: 3개)
MAX_OUTPUTS = 3


def text_response(text: str) -> dict:
    """긴 답변은 1,000자 단위로 잘라 최대 3개의 simpleText로 반환."""
    text = text.strip() or "죄송해요, 답변을 만들지 못했어요. 다시 시도해 주세요."
    chunks = [
        text[i : i + SIMPLE_TEXT_LIMIT]
        for i in range(0, len(text), SIMPLE_TEXT_LIMIT)
    ][:MAX_OUTPUTS]
    return {
        "version": "2.0",
        "template": {
            "outputs": [{"simpleText": {"text": chunk}} for chunk in chunks]
        },
    }


def callback_waiting_response(waiting_text: str = "잠시만요, 생각 중이에요...") -> dict:
    """AI 챗봇 콜백이 활성화된 봇에서 '먼저 접수' 응답."""
    return {
        "version": "2.0",
        "useCallback": True,
        "data": {"text": waiting_text},
    }
