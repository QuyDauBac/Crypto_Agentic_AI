# Kiến trúc ứng dụng — CryptoPilot

> FastAPI + Jinja2 (server-rendered). Phân tầng rõ: **route (thin) → service (fat) →
> adapter / model**. AI Agent là một tầng riêng, gọi xuống service chứ không chạm adapter/DB
> trực tiếp.
>
> Quyết định nền (đã chốt):
> - **DB**: sync SQLAlchemy. **External API** (CoinGecko, Gemini): async (`httpx`/SDK).
> - **Auth**: JWT lưu trong **httpOnly cookie**.
> - **Agent**: hand-roll vòng ReAct bằng `google-genai` SDK, **không** dùng LangChain.

---

## Cấu trúc thư mục (dự kiến)

```
app/
├── main.py                      ← khởi tạo FastAPI, mount routers, start APScheduler
├── core/
│   ├── config.py                ← pydantic-settings, load .env
│   ├── security.py              ← hash password, tạo/verify JWT, set/clear cookie
│   └── database.py              ← engine, SessionLocal, Base, get_db()
├── models/                      ← SQLAlchemy models (xem 03-database.md)
│   ├── user.py
│   ├── coin.py
│   ├── transaction.py
│   ├── alert.py
│   ├── notification.py          ← Notification (price_alert + agent_insight)
│   └── chat.py                  ← Conversation, Message
├── schemas/                     ← Pydantic request/response
│   ├── auth.py
│   ├── transaction.py
│   ├── alert.py
│   └── chat.py
├── api/                         ← routers — THIN, chỉ validate + gọi service
│   ├── deps.py                  ← get_current_user (đọc JWT từ cookie)
│   ├── auth.py                  ← register / login / logout
│   ├── portfolio.py             ← dashboard, CRUD transactions
│   ├── market.py                ← search coin, giá real-time
│   ├── alerts.py                ← CRUD alerts, notification list
│   └── agent.py                 ← chat với AI Agent
├── services/                    ← business logic — FAT
│   ├── portfolio_service.py     ← gộp holdings từ transactions, tính P&L
│   ├── market_service.py        ← gọi adapter, cache, graceful degradation
│   ├── alert_service.py         ← kiểm tra ngưỡng, trigger alert, tạo notification
│   ├── news_service.py          ← lấy tin lọc theo coin user giữ (CryptoPanic)
│   └── chat_service.py          ← lưu/đọc conversations + messages
├── adapters/                    ← tích hợp ngoài, bọc sau interface
│   ├── market_data.py           ← MarketDataInterface (contract)
│   ├── coingecko_adapter.py     ← implement CoinGecko
│   └── cryptopanic_adapter.py   ← NewsInterface → CryptoPanic
├── agent/                       ← AI Agent — TRỌNG TÂM (chi tiết: 05-ai-agent.md)
│   ├── gemini_client.py         ← wrap google-genai SDK
│   ├── orchestrator.py          ← vòng ReAct: gửi → tool call → thực thi → tổng hợp
│   ├── tools.py                 ← function declarations + dispatcher → service
│   └── prompts.py               ← system prompt
└── jobs/
    ├── price_checker.py         ← job kiểm tra giá → trigger alert → notification
    ├── proactive_agent.py       ← job Agent chủ động → notification (agent_insight)
    └── refresh_coins.py         ← job làm mới bảng coins (24h, /coins/list)

templates/                       ← Jinja2 + Bootstrap 5
├── base.html
├── auth/ (login.html, register.html)
├── portfolio/ (dashboard.html, transactions.html)
├── alerts/ (list.html)
└── agent/ (chat.html)

static/  (css/, js/)

tests/
├── test_portfolio.py
├── test_agent.py
└── test_adapters.py

requirements.txt
.env.example
README.md
```

---

## Trách nhiệm từng tầng

| Tầng | Làm gì | KHÔNG làm gì |
|---|---|---|
| **api/** (routes) | Validate input (Pydantic), đọc user từ cookie, gọi service, render template/JSON | Không chứa business logic, không gọi adapter trực tiếp |
| **services/** | Toàn bộ logic nghiệp vụ: gộp holdings, tính P&L, kiểm tra ngưỡng | Không biết về HTTP request/response |
| **adapters/** | Gọi API ngoài, chuẩn hóa response về kiểu nội bộ | Không chứa logic nghiệp vụ |
| **agent/** | Điều phối Agent, định nghĩa tools, dispatch tool → service | Không tự query DB; mọi dữ liệu lấy qua service |
| **models/** | Định nghĩa bảng SQLAlchemy | Không chứa logic |

> Nguyên tắc vàng: **Agent tools gọi service**, service gọi adapter/model. Nhờ vậy logic
> phân tích danh mục viết một lần ở `PortfolioService`, vừa dùng cho UI vừa dùng cho Agent.

---

## Ranh giới async / sync

Đây là điểm dễ bị hỏi khi thuyết trình — nắm rõ để trả lời:

```
External API call (CoinGecko, Gemini)  → ASYNC
  - httpx.AsyncClient, await response
  - đây là I/O chờ lâu nhất → async giúp không block khi đợi

DB access (SQLAlchemy)                 → SYNC
  - SessionLocal đồng bộ, đơn giản, đủ nhanh với SQLite

Quy tắc khai báo route:
  - Route chỉ đụng DB (CRUD transactions/alerts)  → khai báo `def`
      → FastAPI tự chạy trong threadpool, không block event loop
  - Route gọi external API (market, agent)        → khai báo `async def`
      → await httpx/Gemini bình thường
      → phần đọc DB trong route này gọi qua `run_in_threadpool(...)`
        (hoặc tách ra service sync chạy trước/sau await)
```

> Lý do không async hóa DB: SQLite + scope đồ án không cần; async SQLAlchemy thêm phức tạp
> (aiosqlite, async session) mà lợi ích không đáng. Async chỉ áp ở chỗ thực sự chờ lâu = call API ngoài.

---

## Adapter Pattern — Market Data

```python
# app/adapters/market_data.py
from abc import ABC, abstractmethod

class MarketDataInterface(ABC):
    """Contract cho nguồn dữ liệu thị trường. Đổi CoinGecko → provider khác chỉ cần
    viết adapter mới implement interface này, không sửa service."""

    @abstractmethod
    async def get_prices(self, coingecko_ids: list[str]) -> dict[str, float]:
        """Giá USD hiện tại cho nhiều coin. cmd tương đương /simple/price."""

    @abstractmethod
    async def search_coins(self, query: str) -> list[dict]:
        """Tìm coin theo tên/symbol. /search."""

    @abstractmethod
    async def get_market_history(self, coingecko_id: str, days: int) -> list[dict]:
        """Lịch sử giá để phân tích xu hướng. /coins/{id}/market_chart."""

    @abstractmethod
    async def get_coin_list(self) -> list[dict]:
        """Toàn bộ coin hỗ trợ → seed/cache bảng coins. /coins/list."""


# app/adapters/coingecko_adapter.py
class CoinGeckoAdapter(MarketDataInterface):
    async def get_prices(self, coingecko_ids: list[str]) -> dict[str, float]:
        async with httpx.AsyncClient(timeout=10) as client:
            ...   # gọi CoinGecko, chuẩn hóa về { "bitcoin": 67420.0, ... }
```

> Bind interface → adapter một chỗ duy nhất (vd trong `market_service.py` hoặc qua FastAPI
> dependency). Đây là điểm dễ ăn điểm "thiết kế mở rộng" khi chấm.

---

## Flow: User xem danh mục

```
GET /portfolio  (async def, đã auth qua cookie)
  → PortfolioService.get_dashboard(user)
      → đọc transactions của user (DB, sync)
      → gộp holdings: net_quantity, avg_cost_price  (xem 03-database.md)
      → MarketService.get_prices(coin_ids)  → CoinGeckoAdapter (await)
          → nếu CoinGecko lỗi: fallback coins.last_price + cờ "stale"
      → tính current_value, unrealized_pnl mỗi coin
  → render dashboard.html (Jinja2)
```

---

## Flow: User chat với AI Agent

```
POST /agent/chat  (async def)
  → ChatService.load_history(conversation)         ← messages cũ (DB)
  → AgentOrchestrator.run(user, message, history)
      ┌─ gửi message + tool declarations → Gemini (await)
      │   Gemini trả về: function_call(name, args)
      ├─ tools.dispatch(name, args, user)          ← map → service tương ứng
      │     get_portfolio_summary → PortfolioService
      │     get_coin_price        → MarketService
      │     get_coin_history      → MarketService
      │   (scope theo user.id — Agent chỉ thấy danh mục user đang hỏi)
      ├─ gửi tool result trở lại Gemini (await)
      └─ lặp tới khi Gemini trả lời cuối (no more function_call)
  → ChatService.save(user_msg, assistant_msg)      ← lưu messages (DB)
  → trả câu trả lời cho UI
```

> Chi tiết vòng lặp, định nghĩa tools, system prompt → `05-ai-agent.md`.

---

## Flow: Job kiểm tra giá (scheduled)

```
APScheduler (mỗi N phút, N trong settings)
  → price_checker.run()
      → đọc alerts is_active = true  (DB)
      → gom coin_ids → MarketService.get_prices()  (await)
      → AlertService.evaluate(alert, current_price):
          above: current_price >= threshold → trigger
          below: current_price <= threshold → trigger
      → trigger: set triggered_at, is_active = false  (one-shot)
```

---

## Authentication — JWT qua httpOnly cookie

```
POST /login
  → verify email + password (bcrypt)
  → tạo JWT (sub = user.id, exp)
  → set cookie:  Set-Cookie: access_token=<jwt>;
                 HttpOnly; Secure; SameSite=Lax; Path=/
  → redirect về /portfolio

Mỗi request sau đó:
  → browser TỰ gửi cookie
  → deps.get_current_user(): đọc cookie → verify JWT → load User
      → fail (thiếu/hết hạn/sai) → redirect /login

POST /logout
  → xóa cookie (set max-age=0)
```

> **HttpOnly** = JS không đọc được token (chống XSS đánh cắp token).
> **SameSite=Lax** + **CSRF token** cho các form POST đổi dữ liệu — vì cookie tự gửi nên
> cookie-based auth có rủi ro CSRF; cần CSRF token cho POST/PUT/DELETE. (Đây là điểm
> bảo mật nên nêu khi thuyết trình.)

---

## Graceful degradation

| Dịch vụ lỗi | Hệ thống xử lý |
|---|---|
| CoinGecko timeout/lỗi | Dùng `coins.last_price` (giá cache) + hiển thị cờ "dữ liệu cũ"; phần nhập giao dịch vẫn chạy |
| Gemini lỗi/hết quota | Báo lỗi thân thiện trong khung chat; portfolio + alerts không bị ảnh hưởng |
| Job kiểm tra giá lỗi 1 lần | Bỏ qua chu kỳ đó, log lại, chu kỳ sau chạy tiếp; không crash app |

> Nguyên tắc: **một dịch vụ ngoài lỗi không được làm sập toàn app**. Mỗi external call bọc
> try/except, có đường lui rõ ràng.

---

## Security notes

- JWT secret + API keys (Gemini, CoinGecko) lưu trong `.env`, **không hardcode**, không commit
- Cookie: `HttpOnly` + `Secure` (production) + `SameSite=Lax`
- CSRF token cho mọi form đổi dữ liệu (do dùng cookie-based auth)
- Validate input bằng Pydantic schema ở mọi route
- Password hash bằng bcrypt (passlib), không bao giờ lưu plaintext
- Agent tools luôn scope theo `user.id` — Agent **không** được đọc danh mục user khác
- Rate limit endpoint search/chat (tránh đốt quota CoinGecko/Gemini)
```
