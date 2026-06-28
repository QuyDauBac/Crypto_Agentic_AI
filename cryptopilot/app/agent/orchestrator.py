"""AgentOrchestrator — vòng ReAct (Reason + Act) hand-rolled cho CryptoPilot (Phase 4).

Thiết kế lai (đã chốt với người dùng):
  - Dùng FUNCTION CALLING của Gemini để lấy độ ổn định (model trả tên tool + tham số
    có cấu trúc, khỏi tự parse text "Thought/Action" dễ vỡ).
  - Nhưng TỰ viết vòng lặp tường minh bao quanh, log đủ mỗi bước (tool gọi → kết quả →
    bước tiếp) → vừa chạy ổn vừa "khoe" được cơ chế agent khi demo.

Vòng lặp (tối đa MAX_STEPS, tránh lặp vô hạn):
    resp = client.generate(system, turns, tools)
    nếu resp có tool_calls:  thực thi qua dispatch() → đưa kết quả lại → lặp
    ngược lại:               resp.text là câu trả lời cuối → dừng

Graceful: chưa cấu hình key / Gemini lỗi → trả câu trả lời fallback (degraded=True),
KHÔNG ném ra ngoài → route không bao giờ 500, phần portfolio vẫn dùng được.
"""

import logging

from app.agent import tools as tools_mod
from app.agent.gemini_client import LLMClient
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import ToolContext
from app.models.user import User
from app.schemas.chat import ToolStep

logger = logging.getLogger(__name__)

MAX_STEPS = 5  # số vòng tool tối đa cho một câu hỏi

_NOT_CONFIGURED = (
    "AI Agent chưa được cấu hình (thiếu GEMINI_API_KEY trong .env). "
    "Phần danh mục và giá vẫn hoạt động bình thường."
)
_GENERIC_ERROR = (
    "Xin lỗi, hiện chưa thể xử lý yêu cầu do trợ lý AI gặp sự cố (có thể hết quota "
    "hoặc lỗi mạng). Bạn thử lại sau nhé — phần danh mục vẫn xem được bình thường."
)


class AgentResult:
    def __init__(
        self, reply: str, tool_steps: list[ToolStep], degraded: bool = False
    ) -> None:
        self.reply = reply
        self.tool_steps = tool_steps
        self.degraded = degraded


class AgentOrchestrator:
    def __init__(self, client: LLMClient, ctx: ToolContext) -> None:
        self.client = client
        self.ctx = ctx

    @staticmethod
    def _history_to_turns(history: list[dict]) -> list[dict]:
        """[{role:user|assistant, content}] → turns provider-agnostic ([role:user|model])."""
        turns: list[dict] = []
        for m in history:
            role = "model" if m["role"] == "assistant" else "user"
            turns.append({"role": role, "text": m["content"]})
        return turns

    async def run(self, user: User, message: str, history: list[dict]) -> AgentResult:
        if not self.client.is_configured:
            return AgentResult(_NOT_CONFIGURED, [], degraded=True)

        turns = self._history_to_turns(history)
        turns.append({"role": "user", "text": message})
        tool_steps: list[ToolStep] = []

        try:
            for step in range(MAX_STEPS):
                resp = await self.client.generate(
                    system_instruction=SYSTEM_PROMPT,
                    turns=turns,
                    tool_specs=tools_mod.TOOL_SPECS,
                )

                if resp.tool_calls:
                    for call in resp.tool_calls:
                        logger.info(
                            "ReAct step %d: gọi tool %s args=%s",
                            step + 1,
                            call.name,
                            call.args,
                        )
                        result = await tools_mod.dispatch(
                            call.name, call.args, self.ctx
                        )
                        tool_steps.append(
                            ToolStep(
                                name=call.name,
                                args=call.args,
                                ok="error" not in result,
                            )
                        )
                        # đưa cặp (model xin gọi tool, kết quả tool) vào hội thoại
                        turns.append(
                            {
                                "role": "model",
                                "tool_call": {"name": call.name, "args": call.args},
                            }
                        )
                        turns.append(
                            {"role": "tool", "name": call.name, "response": result}
                        )
                    continue  # cho Gemini "đọc" kết quả ở vòng sau

                # không còn tool call → câu trả lời cuối
                reply = resp.text or "Mình chưa có câu trả lời rõ ràng cho yêu cầu này."
                return AgentResult(reply, tool_steps)

            # chạm trần MAX_STEPS → ép trả lời với dữ liệu đang có (không cho gọi tool nữa)
            turns.append(
                {
                    "role": "user",
                    "text": (
                        "Hãy tổng hợp câu trả lời cuối cùng dựa trên dữ liệu đã có, "
                        "không gọi thêm tool."
                    ),
                }
            )
            final = await self.client.generate(
                system_instruction=SYSTEM_PROMPT, turns=turns, tool_specs=[]
            )
            reply = (
                final.text or "Mình đã thu thập dữ liệu nhưng chưa thể tổng hợp gọn."
            )
            return AgentResult(reply, tool_steps)

        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.warning("Agent lỗi: %s", exc)
            return AgentResult(_GENERIC_ERROR, tool_steps, degraded=True)
