"""사용자별 대화 기록을 메모리에 보관하는 간단한 저장소.

프로세스 메모리에만 저장되므로 서버 재시작 시 초기화됩니다.
운영 환경에서 여러 인스턴스를 띄우거나 기록을 유지하려면
Redis 등 외부 저장소로 교체하세요.
"""

import os
import time
from collections import defaultdict

MAX_HISTORY_TURNS = int(os.getenv("MAX_HISTORY_TURNS", "10"))
# 마지막 대화 후 이 시간(초)이 지나면 기록을 버리고 새 대화로 시작
HISTORY_TTL_SECONDS = 60 * 60


class ConversationMemory:
    def __init__(self) -> None:
        self._store: dict[str, dict] = defaultdict(
            lambda: {"messages": [], "updated_at": 0.0}
        )

    def get(self, user_id: str) -> list[dict]:
        entry = self._store[user_id]
        if time.time() - entry["updated_at"] > HISTORY_TTL_SECONDS:
            entry["messages"] = []
        return list(entry["messages"])

    def append(self, user_id: str, user_text: str, assistant_text: str) -> None:
        entry = self._store[user_id]
        entry["messages"].append({"role": "user", "content": user_text})
        entry["messages"].append({"role": "assistant", "content": assistant_text})
        # user/assistant 한 쌍이 1턴 — 최근 N턴만 유지
        entry["messages"] = entry["messages"][-MAX_HISTORY_TURNS * 2 :]
        entry["updated_at"] = time.time()

    def clear(self, user_id: str) -> None:
        self._store.pop(user_id, None)


memory = ConversationMemory()
