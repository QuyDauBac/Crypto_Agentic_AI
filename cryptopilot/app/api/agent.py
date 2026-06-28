"""Router AI Agent (Phase 4) — trang chat + endpoint chat async.

GET  /agent        → trang chat (server-rendered, yêu cầu đăng nhập)
POST /agent/chat   → nhận {message, conversation_id?}, chạy vòng ReAct, trả JSON
                     {reply, conversation_id, tool_steps, degraded}

async def vì có await Gemini + tools (external). DB (qua ChatService) chạy sync trong
threadpool theo đúng quy ước 04-architecture.md. user luôn lấy từ session (Depends) →
Agent không bao giờ chạm danh mục user khác.
"""

from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.adapters.coingecko_adapter import CoinGeckoAdapter
from app.adapters.cryptopanic_adapter import CryptoPanicAdapter
from app.agent.gemini_client import GeminiClient, LLMClient
from app.agent.orchestrator import AgentOrchestrator
from app.agent.tools import ToolContext
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.chat import ChatReply, ChatRequest
from app.services.chat_service import ChatService
from app.services.market_service import MarketService
from app.services.news_service import NewsService
from app.services.portfolio_service import PortfolioService

router = APIRouter(prefix="/agent", tags=["agent"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@dataclass
class AgentDeps:
    """Gom các service + LLM client cho một request (user gắn ở handler)."""

    db: Session
    portfolio: PortfolioService
    market: MarketService
    news: NewsService
    client: LLMClient


def get_agent_deps(db: Session = Depends(get_db)) -> AgentDeps:
    """Bind provider MỘT CHỖ — đổi LLM/registrar/news chỉ sửa ở đây. Test override dep này."""
    market = MarketService(db=db, adapter=CoinGeckoAdapter())
    portfolio = PortfolioService(db=db, market_service=market)
    news = NewsService(db=db, adapter=CryptoPanicAdapter(), portfolio_service=portfolio)
    client = GeminiClient(api_key=settings.GEMINI_API_KEY, model=settings.GEMINI_MODEL)
    return AgentDeps(
        db=db, portfolio=portfolio, market=market, news=news, client=client
    )


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def chat_page(request: Request, user: User = Depends(get_current_user)) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "agent/chat.html",
        {"user": user, "configured": bool(settings.GEMINI_API_KEY)},
    )


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    user: User = Depends(get_current_user),
    deps: AgentDeps = Depends(get_agent_deps),
) -> JSONResponse:
    chat_service = ChatService(deps.db)
    conv = chat_service.get_or_create_conversation(user.id, payload.conversation_id)
    history = chat_service.load_history(conv, last_n=10)

    ctx = ToolContext(
        user=user,
        portfolio_service=deps.portfolio,
        market_service=deps.market,
        news_service=deps.news,
    )
    orchestrator = AgentOrchestrator(client=deps.client, ctx=ctx)
    result = await orchestrator.run(user, payload.message, history)

    # chỉ persist nội dung user/assistant (không lưu tool call) — đúng 03-database.md
    chat_service.save_exchange(conv, payload.message, result.reply)

    reply = ChatReply(
        reply=result.reply,
        conversation_id=conv.id,
        tool_steps=result.tool_steps,
        degraded=result.degraded,
    )
    return JSONResponse(reply.model_dump())
