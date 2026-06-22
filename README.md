<div align="center">

# 🚀 CryptoPilot

### Quản lý danh mục crypto cá nhân — tích hợp **AI Agent** thực thụ

*Đồ án cuối kỳ môn Software Engineering for AI*

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white)
![Gemini](https://img.shields.io/badge/Google_Gemini-8E75B2?style=flat-square&logo=googlegemini&logoColor=white)
![Bootstrap](https://img.shields.io/badge/Bootstrap_5-7952B3?style=flat-square&logo=bootstrap&logoColor=white)
![Status](https://img.shields.io/badge/status-in_development-yellow?style=flat-square)

</div>

---

## 📑 Mục lục

- [Giới thiệu](#-giới-thiệu)
- [Điểm nhấn: AI Agent](#-điểm-nhấn-ai-agent)
- [Kiến trúc tổng thể](#-kiến-trúc-tổng-thể)
- [Actors](#-actors)
- [Tính năng](#-tính-năng)
- [Tech Stack](#-tech-stack)
- [Cấu trúc thư mục](#-cấu-trúc-thư-mục)
- [Cài đặt & Chạy](#-cài-đặt--chạy)
- [Tài liệu kỹ thuật](#-tài-liệu-kỹ-thuật)
- [Phạm vi dự án](#-phạm-vi-dự-án)

---

## 🎯 Giới thiệu

**CryptoPilot** là web app giúp **nhà đầu tư crypto cá nhân, không chuyên** theo dõi danh mục mà
không cần ngồi canh giá liên tục. Người dùng nhập giao dịch thủ công (mua/bán coin, số lượng, giá),
hệ thống tự tính lãi/lỗ theo giá thị trường real-time, và quan trọng nhất — một **AI Agent** đóng vai
trợ lý phân tích: trả lời câu hỏi về danh mục, cảnh báo rủi ro, lọc tin tức và chủ động báo khi phát
hiện điều đáng lưu ý.

Dự án giải quyết **3 nỗi đau** của nhà đầu tư cá nhân:

| 😟 Nỗi đau | 💡 CryptoPilot giải quyết |
|---|---|
| Không biết khi nào nên lo cho danh mục | AI Agent phân tích rủi ro tập trung, xu hướng, lãi/lỗ |
| Quá tải tin tức crypto | Agent lọc tin **chỉ liên quan coin bạn đang giữ** |
| Không có thời gian canh giá | Job nền theo dõi giá + cảnh báo chủ động |

---

## 🤖 Điểm nhấn: AI Agent

Khác với chatbot thường (trả lời bằng kiến thức có sẵn, dễ **bịa số**), Agent của CryptoPilot **tự
quyết định cần dữ liệu gì → gọi tool lấy dữ liệu thật → tổng hợp**. Đây là vòng **ReAct** với
**Function Calling** — trọng tâm học thuật của đồ án.

```mermaid
flowchart LR
    Q["❓ Câu hỏi user<br/>'Danh mục tôi có rủi ro không?'"] --> G{"🤖 Gemini<br/>cần dữ liệu?"}
    G -- "gọi tool" --> T["🔧 Tools<br/>portfolio · price<br/>history · news"]
    T --> D["📥 Dữ liệu thật<br/>từ DB / CoinGecko"]
    D --> G
    G -- "đủ dữ liệu" --> ANS["💬 Câu trả lời<br/>tổng hợp nhiều nguồn"]

    style Q fill:#e3f2fd,stroke:#1976d2
    style G fill:#f3e5f5,stroke:#8e24aa
    style ANS fill:#e8f5e9,stroke:#43a047
```

Agent chạy **2 chế độ**:
- **Reactive** — trả lời khi user chat (vòng ReAct theo yêu cầu)
- **Proactive** — tự chạy theo lịch, phát hiện rủi ro/tin quan trọng và cảnh báo *không cần được hỏi*

```mermaid
sequenceDiagram
    participant J as ⏰ Scheduled Job
    participant P as 📊 Portfolio/News Service
    participant AI as 🤖 Gemini
    participant N as 🔔 Notifications

    J->>P: Dựng snapshot danh mục (mỗi user)
    P-->>J: holdings + allocation + movers + news
    J->>AI: "Có gì user nên biết? (1 call/user)"
    AI-->>J: Nhận định ngắn  hoặc  "NONE"
    alt Có điều đáng lưu ý
        J->>N: Tạo notification (agent_insight)
    end
```

---

## 🏗️ Kiến trúc tổng thể

Phân tầng rõ ràng: **route (thin) → service (fat) → adapter / model**. AI Agent là tầng riêng,
gọi xuống service chứ không chạm DB trực tiếp. Mọi call ra ngoài đều **async** + bọc **Adapter**.

```mermaid
flowchart TB
    subgraph Client["🖥️ Client (Bootstrap 5 + Jinja2)"]
        U["👤 User"]
        A["🛡️ Admin"]
    end

    subgraph App["⚙️ FastAPI Application"]
        direction TB
        R["🌐 API Routes — thin"]
        S["🧠 Services — fat<br/>portfolio · market · alert · news"]
        AG["🤖 AI Agent<br/>orchestrator + tools"]
        AD["🔌 Adapters"]
        J["⏰ Jobs — APScheduler"]
    end

    DB[("🗄️ SQLite + SQLAlchemy")]

    subgraph Ext["☁️ External APIs"]
        CG["📈 CoinGecko"]
        GM["✨ Gemini"]
        CP["📰 CryptoPanic"]
    end

    U --> R
    A --> R
    R --> S
    R --> AG
    AG --> S
    S --> AD
    S --> DB
    AG --> GM
    AD --> CG
    AD --> CP
    J --> S

    style AG fill:#f3e5f5,stroke:#8e24aa,stroke-width:2px
    style DB fill:#fff3e0,stroke:#fb8c00
```

---

## 👥 Actors

| Actor | Vai trò |
|---|---|
| 👤 **User** | Nhập giao dịch, xem danh mục & lãi/lỗ, chat với Agent, đặt cảnh báo, nhận thông báo |
| 🛡️ **Admin** | Xem thống kê hệ thống, quản lý users, cấu hình ngưỡng cảnh báo mặc định |
| 🤖 **AI Agent** | *Actor độc lập:* tự gọi tools để lấy dữ liệu, phân tích danh mục, **chủ động** cảnh báo |

> AI Agent được liệt kê như một **actor** vì nó **tự hành động**, không chỉ phản ứng thụ động như một API.

---

## ✨ Tính năng

**📊 Quản lý danh mục**
- Nhập giao dịch mua/bán (coin, số lượng, giá, ngày)
- Tự tính holdings + giá vốn trung bình + lãi/lỗ real-time
- Tỷ trọng phân bổ danh mục, so sánh hiệu suất với Bitcoin

**🤖 Trợ lý AI (Agent)**
- Chat phân tích danh mục (vòng ReAct, function calling)
- Lọc tin tức crypto **chỉ liên quan coin bạn giữ**
- Chủ động cảnh báo rủi ro mà không cần được hỏi

**🔔 Cảnh báo & theo dõi**
- Đặt ngưỡng giá (above/below) cho coin quan tâm
- Job nền kiểm tra giá định kỳ → thông báo khi chạm ngưỡng
- Hộp thông báo thống nhất (cảnh báo giá + nhận định Agent)

**🔐 Tài khoản**
- Đăng ký / đăng nhập, xác thực JWT qua httpOnly cookie

---

## 🛠️ Tech Stack

| Thành phần | Lựa chọn | Lý do |
|---|---|---|
| Ngôn ngữ | **Python 3.11+** | Ecosystem AI mạnh nhất, cú pháp gọn, hợp sinh viên |
| Backend | **FastAPI** | Async tốt (quan trọng khi gọi API ngoài), docs rõ, học nhanh |
| Frontend | **Bootstrap 5 + Jinja2** | Server-rendered, đủ cho MVP, giảm độ phức tạp |
| Database | **SQLite + SQLAlchemy** | Không cần cài server, đủ cho scope đồ án |
| AI Agent | **Google Gemini** (`google-genai`) | Free tier + hỗ trợ Function Calling, dễ deploy |
| Dữ liệu thị trường | **CoinGecko API** | Free Demo tier, không cần tài khoản sàn |
| Tin tức | **CryptoPanic API** | Lọc tin theo coin (param `currencies`), có free tier |
| Lập lịch | **APScheduler** | Job nền: kiểm tra giá, proactive, refresh cache |
| Auth | **JWT** (httpOnly cookie) | Hợp app server-rendered |

---

## 📁 Cấu trúc thư mục

```
app/
├── main.py              # FastAPI app + khởi động APScheduler
├── core/                # config, security (JWT), database
├── models/              # SQLAlchemy: user, coin, transaction, alert, chat, notification
├── schemas/             # Pydantic request/response
├── api/                 # routes (thin) — auth, portfolio, market, alerts, agent
├── services/            # business logic (fat)
├── adapters/            # CoinGecko, CryptoPanic (sau interface)
├── agent/               # 🤖 orchestrator, tools, prompts, gemini_client
└── jobs/                # price_checker, proactive_agent, refresh_coins
templates/               # Jinja2 + Bootstrap 5
static/                  # CSS, JS
tests/                   # pytest
requirements.txt · .env.example · README.md
```

---

## ⚡ Cài đặt & Chạy

**1. Clone & tạo môi trường ảo**
```bash
git clone <repo-url> && cd cryptopilot
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**2. Lấy API keys (đều miễn phí)**
- 🔑 **CoinGecko** — đăng ký Demo API key tại coingecko.com/en/api/pricing
- 🔑 **Gemini** — tạo key tại Google AI Studio
- 🔑 **CryptoPanic** — đăng ký lấy `auth_token` trong dashboard

**3. Cấu hình `.env`** (copy từ `.env.example`)
```env
COINGECKO_BASE_URL=https://api.coingecko.com/api/v3
COINGECKO_DEMO_KEY=your_key
GEMINI_API_KEY=your_key
GEMINI_MODEL=gemini-2.5-flash
CRYPTOPANIC_BASE_URL=https://cryptopanic.com/api/developer/v2
CRYPTOPANIC_TOKEN=your_token
JWT_SECRET=your_random_secret
JWT_EXPIRE_MINUTES=60
```

**4. Chạy**
```bash
uvicorn app.main:app --reload
```
> Mở http://127.0.0.1:8000 — đăng ký tài khoản, nhập vài giao dịch, rồi thử chat với Agent.

---

## 📚 Tài liệu kỹ thuật

| File | Nội dung |
|---|---|
| [01-overview.md](_docs/01-overview.md) | Tổng quan, mục tiêu, tech stack, actors |
| [02-phases.md](_docs/02-phases.md) | Lộ trình phát triển theo phase |
| [03-database.md](_docs/03-database.md) | Schema database (users, transactions, alerts, notifications, chat) |
| [04-architecture.md](_docs/04-architecture.md) | Kiến trúc, phân tầng, adapter & service, async/sync, JWT |
| [05-ai-agent.md](_docs/05-ai-agent.md) | 🤖 Thiết kế AI Agent: tools, system prompt, ReAct, proactive |
| [06-api-integration.md](_docs/06-api-integration.md) | Tích hợp CoinGecko, Gemini, CryptoPanic |
| [07-alerts-jobs.md](_docs/07-alerts-jobs.md) | Cảnh báo & scheduled jobs (APScheduler) |

---

## 🎯 Phạm vi dự án

<table>
<tr><th>✅ Trong phạm vi (MVP)</th><th>❌ Ngoài phạm vi</th></tr>
<tr><td valign="top">

- Nhập giao dịch thủ công + tính lãi/lỗ
- AI Agent phân tích danh mục (reactive + proactive)
- Lọc tin tức theo coin đang giữ
- Cảnh báo ngưỡng giá
- Admin cơ bản (cờ `is_admin`)

</td><td valign="top">

- Kết nối ví crypto thật
- Tự động giao dịch thay user
- Futures / Derivatives / DeFi
- Thanh toán, gói trả phí
- Mobile app

</td></tr>
</table>

---

<div align="center">

*CryptoPilot — đồ án học thuật. Mọi nhận định của AI Agent mang tính tham khảo, không phải lời khuyên đầu tư.*

</div>
