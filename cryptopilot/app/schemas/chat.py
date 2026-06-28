"""Schemas cho AI Agent chat (Phase 4).

ChatRequest  : body POST /agent/chat từ frontend
ToolStep     : 1 bước tool Agent đã gọi trong vòng ReAct (để minh họa cho người chấm)
ChatReply    : response trả về frontend (câu trả lời + conversation_id + các bước tool)

Lưu ý: ToolStep CHỈ tồn tại trong runtime của một lượt trả lời — không persist vào DB
(đúng quyết định ở 03-database.md: messages chỉ lưu nội dung user/assistant).
"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: int | None = None


class ToolStep(BaseModel):
    """Một lần Agent gọi tool: tên + tham số + tóm tắt kết quả (cho UI demo)."""

    name: str
    args: dict
    ok: bool = True


class ChatReply(BaseModel):
    reply: str
    conversation_id: int
    tool_steps: list[ToolStep] = Field(default_factory=list)
    degraded: bool = False  # True nếu Agent lỗi/chưa cấu hình → câu trả lời là fallback
