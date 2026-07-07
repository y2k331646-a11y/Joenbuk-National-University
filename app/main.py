"""카카오톡 AI 챗봇 에이전트 — 카카오 i 오픈빌더 스킬 서버.

동작 방식
1. 사용자가 카카오톡 채널에 메시지를 보내면 오픈빌더가 이 서버의
   POST /skill 로 스킬 요청을 전달합니다.
2. 서버는 Claude API를 호출해 답변을 생성하고 스킬 응답(v2.0)으로 돌려줍니다.
3. 오픈빌더의 5초 응답 제한이 있으므로:
   - AI 챗봇(콜백) 기능이 승인된 봇: 즉시 "생각 중" 응답을 보내고,
     백그라운드에서 Claude 답변을 완성해 callbackUrl 로 전송 (최대 1분).
   - 콜백이 없는 봇: 제한 시간 안에 동기 방식으로 답변. 시간 초과 시
     안내 메시지를 반환.
"""

import asyncio
import logging
import os

import anthropic
import httpx
from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from fastapi import FastAPI, Request

from app.kakao import callback_waiting_response, text_response
from app.knowledge import load_knowledge
from app.memory import memory

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kakao-claude-bot")

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-8")
SYNC_TIMEOUT_SECONDS = float(os.getenv("SYNC_TIMEOUT_SECONDS", "4.2"))
HOSPITAL_NAME = os.getenv("HOSPITAL_NAME", "전북대학교병원")

PERSONA = f"""당신은 {HOSPITAL_NAME} 외래를 방문한 대기 환자를 돕는 카카오톡 안내 챗봇입니다.

## 역할
- 외래 진료 절차, 검사 준비사항, 원내 시설 위치, 진료과 안내, 제증명/수납 등 병원 이용 안내를 담당합니다.
- 답변은 한국어로, 대기 중인 환자가 읽기 쉽도록 짧고 친절하게 작성합니다. 모바일 메신저 환경이므로 마크다운 서식(#, *, 표) 없이 짧은 문장과 줄바꿈으로 답하세요.

## 반드시 지킬 규칙
1. 의학적 진단, 처방, 치료 판단을 하지 않습니다. 증상 문의에는 어떤 진료과가 적절한지 안내하는 수준까지만 답하고, "정확한 판단은 의료진 진료가 필요하다"고 덧붙입니다.
2. 가슴 통증, 호흡곤란, 의식 저하, 심한 출혈, 마비 등 응급 증상이 언급되면 다른 안내보다 먼저 "즉시 가까운 직원이나 외래 간호사에게 알리고, 원내라면 응급의료센터로, 원외라면 119에 연락하라"고 안내합니다.
3. 아래 병원 지식에 없는 정보(구체적 위치, 전화번호, 규정 등)는 지어내지 말고, 1층 종합안내 데스크나 대표전화로 확인하도록 안내합니다.
4. 예약 조회·변경, 대기 순번, 검사 결과 등 개인 진료정보는 아직 조회할 수 없습니다. 요청받으면 예약 전화나 원내 직원에게 문의하도록 안내합니다.
5. 개인정보(주민번호, 환자번호 등)를 채팅으로 입력하지 않도록 안내합니다.

## 병원 지식
{{knowledge}}"""

SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT") or PERSONA.format(
    knowledge=load_knowledge() or "(등록된 병원 지식이 없습니다. 일반적인 안내만 제공하세요.)"
)

app = FastAPI(title="Kakao Claude Chatbot")
claude = AsyncAnthropic()  # ANTHROPIC_API_KEY 환경 변수 사용


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "model": CLAUDE_MODEL}


async def generate_reply(user_id: str, utterance: str) -> str:
    """대화 기록을 포함해 Claude를 호출하고 답변 텍스트를 반환."""
    messages = memory.get(user_id) + [{"role": "user", "content": utterance}]
    response = await claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=messages,
    )
    reply = "".join(
        block.text for block in response.content if block.type == "text"
    )
    memory.append(user_id, utterance, reply)
    return reply


async def deliver_via_callback(callback_url: str, user_id: str, utterance: str) -> None:
    """백그라운드에서 답변을 생성해 오픈빌더 callbackUrl 로 전송 (1분 제한)."""
    try:
        reply = await generate_reply(user_id, utterance)
        payload = text_response(reply)
    except anthropic.APIStatusError as exc:
        logger.error("Claude API error in callback: %s %s", exc.status_code, exc.message)
        payload = text_response("죄송해요, 지금은 답변을 만들 수 없어요. 잠시 후 다시 시도해 주세요.")
    except Exception:
        logger.exception("Unexpected error in callback path")
        payload = text_response("죄송해요, 오류가 발생했어요. 잠시 후 다시 시도해 주세요.")

    async with httpx.AsyncClient(timeout=10) as http:
        result = await http.post(callback_url, json=payload)
        if result.status_code != 200:
            logger.error("Callback delivery failed: %s %s", result.status_code, result.text)


@app.post("/skill")
async def skill(request: Request) -> dict:
    body = await request.json()
    user_request = body.get("userRequest", {})
    utterance = (user_request.get("utterance") or "").strip()
    user_id = user_request.get("user", {}).get("id", "anonymous")
    callback_url = user_request.get("callbackUrl")

    if not utterance:
        return text_response(
            f"안녕하세요, {HOSPITAL_NAME} 외래 안내 챗봇입니다.\n"
            "진료 절차, 검사 준비사항, 시설 위치 등 궁금한 점을 물어보세요."
        )

    # 간단한 관리 명령: 대화 기록 초기화
    if utterance in ("/새대화", "/reset"):
        memory.clear(user_id)
        return text_response("새 대화를 시작할게요. 무엇을 도와드릴까요?")

    # AI 챗봇(콜백) 승인 봇: 즉시 접수 응답 후 백그라운드에서 답변 전송
    if callback_url:
        asyncio.create_task(deliver_via_callback(callback_url, user_id, utterance))
        return callback_waiting_response()

    # 콜백 미사용 봇: 5초 제한 안에서 동기 응답
    try:
        reply = await asyncio.wait_for(
            generate_reply(user_id, utterance), timeout=SYNC_TIMEOUT_SECONDS
        )
        return text_response(reply)
    except asyncio.TimeoutError:
        logger.warning("Sync reply timed out for user %s", user_id)
        return text_response(
            "답변 생성에 시간이 걸리고 있어요. 질문을 조금 더 짧게 하거나 "
            "다시 한 번 보내주세요.\n(팁: 오픈빌더에서 'AI 챗봇' 콜백 기능을 "
            "신청하면 긴 답변도 끊김 없이 받을 수 있어요.)"
        )
    except anthropic.RateLimitError:
        return text_response("요청이 많아 잠시 대기가 필요해요. 잠시 후 다시 보내주세요.")
    except anthropic.APIStatusError as exc:
        logger.error("Claude API error: %s %s", exc.status_code, exc.message)
        return text_response("죄송해요, 지금은 답변을 만들 수 없어요. 잠시 후 다시 시도해 주세요.")
    except anthropic.APIConnectionError:
        logger.error("Network error reaching Claude API")
        return text_response("네트워크 오류가 발생했어요. 잠시 후 다시 시도해 주세요.")
