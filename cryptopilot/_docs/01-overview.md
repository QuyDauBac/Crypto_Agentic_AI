# Tổng quan dự án — CryptoPilot

> Ứng dụng quản lý danh mục crypto cá nhân tích hợp Agentic AI.
> Đồ án cuối kỳ — môn *Software Engineering for AI*.

---

## Mục tiêu

Xây dựng web app giúp **nhà đầu tư crypto cá nhân, không chuyên** theo dõi danh mục đầu tư mà không
cần ngồi canh giá liên tục. Người dùng nhập giao dịch thủ công (mua/bán coin, số lượng, giá, ngày),
hệ thống tự tính lãi/lỗ theo giá thị trường real-time, và quan trọng nhất — một **AI Agent** đóng vai
trợ lý phân tích: trả lời câu hỏi về danh mục, cảnh báo rủi ro, lọc tin tức liên quan và chủ động báo
khi phát hiện điều đáng lưu ý.

Dự án tập trung vào luồng cốt lõi (theo dõi danh mục → phân tích bằng AI → cảnh báo), không hướng tới
một sàn giao dịch hay ví crypto. Mục tiêu cuối là chứng minh cách áp dụng **kỹ thuật phần mềm bài bản**
(adapter pattern, thin routes/fat services, async, graceful degradation) vào một sản phẩm có thành phần
AI Agent thực thụ.

---

## Lý do cần AI Agent

Một bảng giá real-time bình thường chỉ trả lời được *"giá bao nhiêu?"*. Nhưng nhà đầu tư không chuyên
cần trả lời những câu hỏi **đa bước, mang tính ngữ cảnh cá nhân**: *"Danh mục của tôi có đang quá tập
trung không?"*, *"Tin hôm nay ảnh hưởng gì tới coin tôi giữ?"*, *"So với Bitcoin thì tôi đang làm tốt
hay tệ?"*. Để trả lời, hệ thống phải **tự quyết định cần dữ liệu gì** → **gọi đúng tool** → **tổng hợp
thành nhận định** — đúng định nghĩa một Agent dùng Function Calling. Đây là lý do AI Agent là trọng tâm
đồ án, không phải một chatbot trả lời cố định.

---

## Phạm vi (MVP)

**Làm:**
- ✅ Nhập giao dịch thủ công + tính lãi/lỗ real-time
- ✅ AI Agent phân tích danh mục (reactive + proactive)
- ✅ Lọc tin tức theo coin đang giữ
- ✅ Cảnh báo ngưỡng giá + hộp thông báo

**Không làm:**
- ❌ Kết nối ví crypto thật
- ❌ Tự động giao dịch thay user
- ❌ Futures / Derivatives / DeFi
- ❌ Thanh toán, gói trả phí
- ❌ Mobile app

---

## Tech Stack

| Thành phần | Lựa chọn | Lý do |
|---|---|---|
| Ngôn ngữ | **Python 3.11+** | Ecosystem AI mạnh nhất, cú pháp gọn, hợp sinh viên năm 2 |
| Backend | **FastAPI** | Async tốt (quan trọng khi gọi API ngoài), docs rõ, học nhanh |
| Frontend | **Bootstrap 5 + Jinja2** | Server-rendered, đủ cho MVP, ít context switch |
| Database | **SQLite + SQLAlchemy** | Không cần cài DB server, đủ cho scope đồ án |
| AI Agent | **Google Gemini** (`google-genai`) | Free tier + hỗ trợ Function Calling, dễ deploy |
| Dữ liệu thị trường | **CoinGecko API** | Free Demo tier, không cần tài khoản sàn |
| Tin tức | **CryptoPanic API** | Lọc tin theo coin (param `currencies`), có free tier |
| Lập lịch | **APScheduler** | Job nền: kiểm tra giá, proactive, refresh cache |
| Auth | **JWT** (httpOnly cookie) | Hợp app server-rendered |

---

## Actors

### 👤 User (khách hàng cuối)
- Đăng ký / đăng nhập, quản lý danh mục
- Nhập giao dịch mua/bán, xem lãi/lỗ & tỷ trọng phân bổ
- Chat với AI Agent để phân tích danh mục
- Đặt cảnh báo ngưỡng giá, nhận thông báo

### 🛡️ Admin
- Xem thống kê hệ thống, quản lý users
- Cấu hình ngưỡng cảnh báo / tham số mặc định
- Phân quyền đơn giản bằng cờ `is_admin` (không RBAC đầy đủ — phù hợp scope)

### 🤖 AI Agent
- Nhận câu hỏi từ User → **tự gọi tools** lấy dữ liệu → phân tích → trả lời (reactive)
- **Chủ động** phát hiện rủi ro / tin quan trọng → gửi cảnh báo (proactive)

> AI Agent được liệt kê như một **actor độc lập** vì nó **tự hành động**, không chỉ phản ứng
> thụ động như một API thông thường — đây là điểm nhấn học thuật của đồ án.

---

## Tính năng cốt lõi (MVP)

1. **Portfolio Management** — nhập giao dịch, tính holdings + giá vốn TB + lãi/lỗ real-time
2. **AI Agent (reactive)** — chat phân tích danh mục qua vòng ReAct + Function Calling
3. **AI Agent (proactive)** — job nền phân tích, chủ động cảnh báo rủi ro
4. **News Filtering** — Agent lọc tin tức chỉ liên quan coin user đang giữ
5. **Price Alerts** — đặt ngưỡng giá, job kiểm tra định kỳ, thông báo khi chạm
6. **Notifications** — hộp thông báo thống nhất (cảnh báo giá + nhận định Agent)
7. **Auth** — đăng ký/đăng nhập, JWT qua httpOnly cookie

---

## Nguyên tắc thiết kế

- **Thin routes, Fat services** — logic nghiệp vụ nằm trong Service classes
- **Adapter pattern** — bọc CoinGecko/CryptoPanic sau interface, dễ thay provider
- **Agent gọi service** — Agent tools không chạm DB/adapter trực tiếp, tái dùng logic
- **Async cho call ngoài** — gọi CoinGecko/Gemini/CryptoPanic không block; DB giữ sync cho gọn
- **Graceful degradation** — một dịch vụ ngoài lỗi không làm sập toàn app
- **Không bịa số** — mọi con số Agent đưa ra đều từ tool (DB/API), chống hallucination
- **Dữ liệu tối giản gửi AI** — chỉ gửi đúng dữ liệu cần, không dump cả DB

---

## Cấu trúc thư mục (dự kiến)

```
app/
├── main.py              # FastAPI app + khởi động APScheduler
├── core/                # config, security (JWT), database
├── models/              # user, coin, transaction, alert, notification, chat
├── schemas/             # Pydantic request/response
├── api/                 # routes (thin): auth, portfolio, market, alerts, agent
├── services/            # portfolio, market, alert, news, chat
├── adapters/            # coingecko, cryptopanic (sau interface)
├── agent/               # 🤖 orchestrator, tools, prompts, gemini_client
└── jobs/                # price_checker, proactive_agent, refresh_coins
templates/               # Jinja2 + Bootstrap 5
static/                  # CSS, JS
tests/                   # pytest
requirements.txt · .env.example · README.md
```

---

## Tài liệu

| File | Nội dung |
|---|---|
| [01-overview.md](01-overview.md) | Tổng quan, mục tiêu, tech stack, actors *(file này)* |
| [02-phases.md](02-phases.md) | Lộ trình phát triển theo phase |
| [03-database.md](03-database.md) | Schema database |
| [04-architecture.md](04-architecture.md) | Kiến trúc hệ thống, adapter & service layer |
| [05-ai-agent.md](05-ai-agent.md) | Thiết kế AI Agent: tools, system prompt, ReAct, proactive |
| [06-api-integration.md](06-api-integration.md) | Tích hợp CoinGecko, Gemini, CryptoPanic |
| [07-alerts-jobs.md](07-alerts-jobs.md) | Cảnh báo & scheduled jobs (APScheduler) |
