"""ChatService — persistence cho hội thoại AI Agent (Phase 4).

Trách nhiệm:
  - get_or_create_conversation: lấy phiên chat (scope theo user) hoặc tạo mới
  - load_history: lấy N tin gần nhất → quản lý context window (xem 05-ai-agent.md)
  - save_exchange: lưu CẶP (user message, assistant message) sau một lượt trả lời

Chỉ persist nội dung user/assistant. Tool call trong vòng ReAct KHÔNG lưu (đúng 03-database.md).
Mọi truy vấn scope theo user_id — user A không đọc được hội thoại của user B.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.message import Message


class ChatService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_create_conversation(
        self, user_id: int, conversation_id: int | None
    ) -> Conversation:
        if conversation_id is not None:
            conv = (
                self.db.execute(
                    select(Conversation).where(
                        Conversation.id == conversation_id,
                        Conversation.user_id == user_id,  # scope bảo mật
                    )
                )
                .scalars()
                .first()
            )
            if conv is not None:
                return conv
        # không truyền id, hoặc id không thuộc user → tạo phiên mới
        conv = Conversation(user_id=user_id)
        self.db.add(conv)
        self.db.commit()
        self.db.refresh(conv)
        return conv

    def load_history(self, conversation: Conversation, last_n: int = 10) -> list[dict]:
        """N tin gần nhất, trả về [{role, content}] theo thứ tự thời gian tăng dần."""
        rows = list(
            self.db.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.id.desc())
                .limit(last_n)
            ).scalars()
        )
        rows.reverse()  # về lại thứ tự cũ → mới
        return [{"role": m.role, "content": m.content} for m in rows]

    def save_exchange(
        self, conversation: Conversation, user_text: str, assistant_text: str
    ) -> None:
        self.db.add_all(
            [
                Message(
                    conversation_id=conversation.id, role="user", content=user_text
                ),
                Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=assistant_text,
                ),
            ]
        )
        self.db.commit()
