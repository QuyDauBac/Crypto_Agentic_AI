"""ProactiveAgentService — Agent chủ động phân tích danh mục (Phase 5).

Khác chế độ reactive (vòng ReAct nhiều bước): proactive **dựng sẵn snapshot** rồi gửi Gemini
**1 call/user** (không cho gọi tool vòng vòng) — quyết định ở 05-ai-agent.md để không đốt quota.

Gemini trả "NONE" nếu không có gì đáng báo → bỏ qua (tránh spam). Ngược lại → text nhận định.

Lưu ý "movers": tính từ pnl_pct (biến động so với GIÁ VỐN) lấy sẵn trong get_summary —
KHÔNG tốn thêm API call. Biến động 24h thật cần thêm call/coin nên để Phase mở rộng.
"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.gemini_client import LLMClient
from app.agent.prompts import PROACTIVE_PROMPT
from app.models.transaction import Transaction
from app.models.user import User
from app.services.news_service import NewsService
from app.services.portfolio_service import PortfolioService

logger = logging.getLogger(__name__)


class ProactiveAgentService:
    def __init__(
        self,
        db: Session,
        portfolio_service: PortfolioService,
        news_service: NewsService,
        client: LLMClient,
    ) -> None:
        self.db = db
        self.portfolio = portfolio_service
        self.news = news_service
        self.client = client

    def users_with_holdings(self) -> list[User]:
        """User đang active VÀ có ít nhất 1 giao dịch (bỏ user danh mục rỗng → tiết kiệm quota)."""
        user_ids = list(
            self.db.execute(select(Transaction.user_id).distinct()).scalars()
        )
        if not user_ids:
            return []
        return list(
            self.db.execute(
                select(User).where(User.id.in_(user_ids), User.is_active.is_(True))
            ).scalars()
        )

    async def _snapshot_text(self, user: User) -> str:
        summary = await self.portfolio.get_summary(user.id)
        allocation = await self.portfolio.get_allocation(user.id)
        news = await self.news.get_filtered(user, limit=3)

        # movers: top biến động so với giá vốn (từ summary, không tốn thêm call)
        movers = sorted(
            (
                {
                    "symbol": h["symbol"],
                    "pnl_pct": h["pnl_pct"],
                }
                for h in summary.get("holdings", [])
                if h.get("pnl_pct") is not None
            ),
            key=lambda x: abs(x["pnl_pct"] or 0),
            reverse=True,
        )[:3]

        snapshot = {
            "summary": summary,
            "allocation": allocation,
            "movers_vs_cost": movers,
            "news": news,
        }
        return json.dumps(snapshot, ensure_ascii=False, default=str)

    async def insight_for_user(self, user: User) -> str | None:
        """Trả text nhận định, hoặc None nếu Gemini bảo NONE / chưa cấu hình / lỗi."""
        if not self.client.is_configured:
            return None
        try:
            snapshot = await self._snapshot_text(user)
            resp = await self.client.generate(
                system_instruction=PROACTIVE_PROMPT,
                turns=[{"role": "user", "text": snapshot}],
                tool_specs=[],
            )
        except Exception as exc:  # noqa: BLE001 — 1 user lỗi không chặn job
            logger.warning("proactive insight lỗi (user %s): %s", user.id, exc)
            return None

        text = (resp.text or "").strip()
        if not text or text.upper() == "NONE":
            return None
        return text
