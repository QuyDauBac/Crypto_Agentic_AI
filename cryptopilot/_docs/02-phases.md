# Lộ trình phát triển — CryptoPilot

> Lộ trình chia theo phase, sắp xếp theo thứ tự phụ thuộc: nền tảng chạy được trước,
> sau đó tới dữ liệu thị trường, danh mục, rồi mới đến AI Agent (trọng tâm đồ án),
> cảnh báo và cuối cùng là admin + hoàn thiện.
>
> Mỗi phase là một mốc demo được — kết thúc phase là có thứ chạy thật để show.

---

## Phase 1 — Foundation ⬜

**Mục tiêu:** Dự án chạy được, auth hoạt động, database sẵn sàng.

- [ ] Scaffold FastAPI project (cấu trúc `app/` theo `04-architecture.md`)
- [ ] Cấu hình `requirements.txt`: `fastapi`, `uvicorn`, `sqlalchemy`, `jinja2`, `python-jose` (JWT), `passlib[bcrypt]`, `httpx`, `apscheduler`, `google-genai`
- [ ] Setup SQLite + SQLAlchemy: `engine`, `SessionLocal`, `Base`, dependency `get_db()`
- [ ] Models cơ bản: `User` (id, email, hashed_password, created_at, is_active)
- [ ] Auth: register / login / logout với JWT (access token), hash password bằng bcrypt
- [ ] Dependency `get_current_user()` để bảo vệ route
- [ ] Layout Bootstrap 5 + Jinja2: `base.html`, navbar, trang login/register
- [ ] File `.env.example` + load config qua `pydantic-settings`
- [ ] Tests: đăng ký, đăng nhập, truy cập route được bảo vệ khi chưa/đã login

---

## Phase 2 — Market Data Integration ⬜

**Mục tiêu:** Lấy được giá crypto real-time qua CoinGecko, bọc qua Adapter để dễ thay nhà cung cấp.

- [ ] `MarketDataInterface` (contract) + `CoinGeckoAdapter` (implement) — Adapter pattern
- [ ] `get_price(coin_ids)` — giá hiện tại nhiều coin một lần (`/simple/price`)
- [ ] `search_coins(query)` — tìm coin theo tên/symbol (`/search`)
- [ ] `get_market_history(coin_id, days)` — lịch sử giá cho phân tích xu hướng
- [ ] `get_coin_list()` — danh sách coin hỗ trợ (cache để map symbol → coin_id)
- [ ] Caching ngắn hạn (in-memory hoặc SQLite) để tránh vượt rate limit free tier
- [ ] **Graceful degradation**: nếu CoinGecko lỗi/timeout → trả dữ liệu cache cuối + cờ "stale", không làm sập app
- [ ] Trang demo: search coin + hiển thị giá real-time
- [ ] Tests: adapter trả đúng format, xử lý đúng khi API lỗi (mock `httpx`)

---

## Phase 3 — Portfolio Management ⬜

**Mục tiêu:** User nhập giao dịch và xem lãi/lỗ danh mục theo giá thị trường.

- [ ] Models: `Transaction` (user_id, coin_id, type [buy/sell], quantity, price, executed_at), `Holding` (tính toán hoặc view)
- [ ] CRUD giao dịch: thêm / sửa / xóa giao dịch mua-bán
- [ ] `PortfolioService`: tổng hợp holdings từ transactions (gộp theo coin, tính số lượng ròng + giá vốn trung bình)
- [ ] Tính **lãi/lỗ real-time**: giá vốn vs giá hiện tại (gọi `MarketDataInterface`)
- [ ] Dashboard danh mục: tổng giá trị, tổng P/L, P/L từng coin
- [ ] Tỷ trọng phân bổ (allocation) — % mỗi coin trong danh mục
- [ ] So sánh hiệu suất danh mục với Bitcoin (benchmark đơn giản)
- [ ] Tests: tính holdings đúng sau nhiều giao dịch, tính P/L đúng

---

## Phase 4 — AI Agent ⬜ ⭐

**Mục tiêu:** Agent dùng Function Calling tự lấy dữ liệu và phân tích danh mục — đây là trọng tâm đồ án.

> Chi tiết thiết kế tools, system prompt và flow nằm trong `05-ai-agent.md`.

- [ ] Tích hợp Gemini API (`google-genai`) — gửi message, nhận response, xử lý function call
- [ ] Định nghĩa **tools** (function declarations) cho Agent:
  - `get_portfolio_summary()` — đọc danh mục + P/L của user hiện tại
  - `get_coin_price(coin_id)` — giá hiện tại một coin
  - `get_coin_history(coin_id, days)` — lịch sử giá để đánh giá xu hướng
  - `get_portfolio_allocation()` — tỷ trọng từng coin (phát hiện tập trung rủi ro)
  - `get_crypto_news(coingecko_ids?, limit)` — tin tức lọc theo coin user giữ (CryptoPanic)
- [ ] `AgentOrchestrator`: vòng lặp ReAct — gửi câu hỏi → Agent gọi tool → thực thi tool → trả kết quả về → Agent tổng hợp câu trả lời
- [ ] System prompt: định nghĩa vai trò (trợ lý phân tích danh mục), giới hạn (không tư vấn đầu tư khẳng định, không bịa số liệu), danh sách tools
- [ ] **Tool handler layer**: map tên function Agent gọi → service tương ứng, validate tham số, scope dữ liệu theo `user_id` (Agent chỉ thấy danh mục của user đang hỏi)
- [ ] Giao diện chat (`chat.html`): user hỏi, hiển thị câu trả lời + (optional) các bước tool Agent đã gọi để minh họa cho người chấm
- [ ] **Async**: gọi Gemini + tools không block giao diện
- [ ] **Graceful degradation**: Gemini lỗi → báo lỗi thân thiện, không crash; phần portfolio vẫn xem được
- [ ] Tests: mock Gemini, kiểm tra orchestrator gọi đúng tool và tổng hợp đúng

---

## Phase 5 — Alerts & Scheduled Jobs ⬜

**Mục tiêu:** Theo dõi giá liên tục và chủ động cảnh báo — giải quyết pain point "không có thời gian canh giá".

> Chi tiết cơ chế job nằm trong `07-alerts-jobs.md`.

- [ ] Model `Alert` (user_id, coin_id, condition [above/below], threshold_price, is_active, triggered_at)
- [ ] Model `Notification` (user_id, type [price_alert/agent_insight], message, alert_id?, is_read)
- [ ] CRUD cảnh báo: user đặt ngưỡng giá cho coin quan tâm
- [ ] APScheduler: job `price_check` định kỳ (5–15 phút) kiểm tra giá vs ngưỡng
- [ ] `AlertService`: phát hiện ngưỡng chạm → one-shot trigger → tạo `Notification` (type=price_alert)
- [ ] Hộp thông báo trong app: list + badge chưa đọc (gom price_alert + agent_insight)
- [ ] **Agent chủ động (proactive)**: job dựng snapshot danh mục/user → Gemini phân tích → tạo `Notification` (type=agent_insight) nếu có điều đáng lưu ý
- [ ] **News filtering**: tích hợp CryptoPanic → tool `get_crypto_news` lọc tin theo coin user giữ
- [ ] Job `refresh_coins` (24h): làm mới bảng `coins` từ CoinGecko `/coins/list`
- [ ] Tests: job trigger đúng khi giá vượt ngưỡng, không trigger lặp

---

## Phase 6 — Admin & Hoàn thiện ⬜

**Mục tiêu:** Quản trị hệ thống, kiểm thử và sẵn sàng demo/nộp bài.

- [ ] Role admin đơn giản (cờ `is_admin` trên `User` — đủ cho scope đồ án, không cần RBAC đầy đủ)
- [ ] Admin dashboard: thống kê hệ thống (số user, số giao dịch, số alert)
- [ ] Admin quản lý users (xem danh sách, khóa/mở tài khoản)
- [ ] Cấu hình ngưỡng cảnh báo mặc định toàn hệ thống
- [ ] Hoàn thiện UI/UX, xử lý empty state và error state
- [ ] Test coverage cho các luồng chính (`test_portfolio.py`, `test_agent.py`, `test_adapters.py`)
- [ ] Viết README (cài đặt, chạy, biến môi trường, demo flow)
- [ ] Chuẩn bị slide/demo: nhấn mạnh phần AI Agent (vòng ReAct + Function Calling)

---

## Backlog / Ngoài phạm vi (Future)

> Các mục dưới đây **cố ý không làm** trong MVP — ghi rõ để bảo vệ scope khi thuyết trình.

- ❌ Kết nối ví crypto thật (read on-chain balance) — quá phức tạp
- ❌ Tự động giao dịch / đặt lệnh thay user
- ❌ Hỗ trợ Futures / Derivatives / DeFi
- ❌ Thanh toán, gói trả phí
- ❌ Mobile app (đã chốt làm web app)
- ⏳ Multi-currency (chỉ USD trong MVP)
- ⏳ Nhiều nguồn dữ liệu thị trường (chỉ CoinGecko)
- ⏳ Nhiều LLM provider (chỉ Gemini; nhưng đã bọc Adapter nên dễ thêm sau)
- ⏳ Cảnh báo qua email / push (chỉ in-app notification trong MVP)
