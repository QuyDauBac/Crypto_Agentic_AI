# Database Schema — CryptoPilot

> SQLite + SQLAlchemy. Schema cố ý giữ gọn, đúng phạm vi MVP.
>
> Ba quyết định lõi (đã chốt):
> - **Chat**: lưu tin nhắn user + agent (không lưu tool calls)
> - **Holdings**: tính động từ `transactions`, **không** có bảng holdings riêng
> - **Alerts**: chỉ hỗ trợ ngưỡng giá (above / below)

---

## Users

```
users
  id              INTEGER PK
  email           VARCHAR(255) UNIQUE NOT NULL
  hashed_password VARCHAR(255) NOT NULL   ← bcrypt (passlib)
  display_name    VARCHAR(100) nullable
  is_active       BOOL default true
  is_admin        BOOL default false      ← admin đơn giản bằng cờ, không RBAC đầy đủ
  created_at      TIMESTAMP
  updated_at      TIMESTAMP
```

> Phân quyền chỉ có 2 mức (user / admin) qua cờ `is_admin` — đủ cho scope đồ án.

---

## Coins (cache CoinGecko)

```
coins
  id              INTEGER PK
  coingecko_id    VARCHAR(100) UNIQUE NOT NULL   ← id chuẩn của CoinGecko, e.g. "bitcoin"
  symbol          VARCHAR(20)  NOT NULL          ← e.g. "btc"
  name            VARCHAR(100) NOT NULL          ← e.g. "Bitcoin"
  image_url       VARCHAR(500) nullable
  last_price      DECIMAL(20,8) nullable         ← giá USD lần sync gần nhất
  last_synced_at  TIMESTAMP nullable
  created_at      TIMESTAMP
```

> Bảng này là **cache/reference**, không phải nguồn chân lý về giá. Giá real-time vẫn lấy
> trực tiếp từ CoinGecko qua Adapter; `last_price` chỉ để hiển thị nhanh + fallback khi API lỗi
> (graceful degradation). `transactions` và `alerts` tham chiếu coin qua FK tới bảng này để
> chuẩn hóa, thay vì rải chuỗi `coingecko_id` khắp nơi.

---

## Transactions

```
transactions
  id              INTEGER PK
  user_id         FK → users NOT NULL
  coin_id         FK → coins NOT NULL
  type            ENUM(buy, sell) NOT NULL
  quantity        DECIMAL(20,8) NOT NULL    ← số lượng coin
  price           DECIMAL(20,8) NOT NULL    ← giá USD/coin tại thời điểm giao dịch (user nhập)
  fee             DECIMAL(20,8) nullable    ← phí giao dịch (optional, có thể bỏ qua ở MVP)
  note            VARCHAR(255) nullable
  executed_at     TIMESTAMP NOT NULL        ← thời điểm giao dịch thực tế (user nhập)
  created_at      TIMESTAMP                 ← thời điểm tạo bản ghi
```

> Đây là **nguồn chân lý** của danh mục. Mọi số liệu holdings/P&L đều suy ra từ bảng này.

---

## Holdings — tính động (KHÔNG có bảng)

> Theo quyết định: holdings được **tính từ `transactions`** trong `PortfolioService`,
> không lưu bảng riêng. Lợi: dữ liệu luôn nhất quán, không lo sync lệch. Logic gộp:

```python
# Với mỗi coin của user, gộp toàn bộ transactions:
#   net_quantity   = Σ(buy.quantity) − Σ(sell.quantity)
#   total_cost     = Σ(buy.quantity × buy.price)   ← chỉ tính lệnh mua (giá vốn)
#   avg_cost_price = total_cost / Σ(buy.quantity)
#
# Giá trị & lãi/lỗ hiện tại:
#   current_value  = net_quantity × current_price   ← current_price từ CoinGecko Adapter
#   unrealized_pnl = current_value − (net_quantity × avg_cost_price)
#
# Chỉ hiển thị coin có net_quantity > 0.
```

> Cách tính giá vốn dùng **average cost** (giá vốn trung bình) cho đơn giản — không dùng
> FIFO/LIFO. Phù hợp scope năm 2; nếu cần chuẩn kế toán hơn thì nâng cấp sau.

---

## Alerts

```
alerts
  id              INTEGER PK
  user_id         FK → users NOT NULL
  coin_id         FK → coins NOT NULL
  condition       ENUM(above, below) NOT NULL   ← giá vượt lên trên / xuống dưới ngưỡng
  threshold_price DECIMAL(20,8) NOT NULL         ← ngưỡng giá USD
  is_active       BOOL default true
  triggered_at    TIMESTAMP nullable             ← null = chưa kích hoạt
  created_at      TIMESTAMP
```

> **One-shot**: khi giá chạm điều kiện → set `triggered_at`, đặt `is_active = false`, đồng thời
> job kiểm tra giá **tạo một bản ghi `notifications`** (type=`price_alert`) để hiển thị cho user.
> User có thể tạo lại alert mới nếu muốn theo dõi tiếp.

---

## Notifications

> Một "hộp thông báo" thống nhất cho user, gom **cả 2 nguồn**: cảnh báo giá (từ alert chạm ngưỡng)
> và nhận định chủ động của AI Agent (proactive insight — dạng văn bản tự do, không nhét vừa bảng `alerts`).

```
notifications
  id              INTEGER PK
  user_id         FK → users NOT NULL
  type            ENUM(price_alert, agent_insight) NOT NULL
                  price_alert   = từ job kiểm tra giá (alert chạm ngưỡng)
                  agent_insight = từ Agent proactive (nhận định văn bản)
  title           VARCHAR(200) nullable
  message         TEXT NOT NULL            ← nội dung hiển thị cho user
  alert_id        FK → alerts (nullable)   ← liên kết alert gốc nếu type=price_alert
  is_read         BOOL default false
  created_at      TIMESTAMP
```

> Chi tiết job sinh notification (kiểm tra giá + proactive Agent) ở `07-alerts-jobs.md`.

---

## Chat (AI Agent)

```
conversations
  id              INTEGER PK
  user_id         FK → users NOT NULL
  title           VARCHAR(200) nullable    ← tóm tắt/đặt tên phiên chat (optional)
  created_at      TIMESTAMP
  updated_at      TIMESTAMP

messages
  id              INTEGER PK
  conversation_id FK → conversations NOT NULL
  role            ENUM(user, assistant) NOT NULL
  content         TEXT NOT NULL
  created_at      TIMESTAMP
```

> Chỉ lưu **nội dung tin nhắn** của user và agent (đúng lựa chọn). Các tool call mà Agent thực
> hiện trong vòng ReAct **không** được persist — chúng diễn ra trong runtime của một lượt trả lời.
> Nếu sau này muốn show "Agent đã gọi tool gì" cho người chấm, có thể thêm bảng `message_tool_calls`
> mà không phá schema hiện tại.

---

## Settings (system defaults — optional)

```
settings
  id              INTEGER PK
  key             VARCHAR(100) UNIQUE NOT NULL
  value           TEXT
  updated_at      TIMESTAMP

  Key dự kiến:
    alert.default_check_interval_minutes   ← chu kỳ job kiểm tra giá (Phase 5)
    market.cache_ttl_seconds               ← TTL cache giá CoinGecko
```

> Phục vụ mục "cấu hình ngưỡng cảnh báo mặc định" của Admin ở Phase 6. Có thể bỏ nếu bạn muốn
> hardcode trong `.env` cho gọn — tôi để đây như tùy chọn.

---

## Quan hệ tóm tắt

```
User
 ├── has many Transactions
 ├── has many Alerts
 ├── has many Conversations
 └── has many Notifications

Coin
 ├── has many Transactions
 └── has many Alerts

Transaction
 ├── belongs to User
 └── belongs to Coin

Alert
 ├── belongs to User
 └── belongs to Coin

Conversation
 ├── belongs to User
 └── has many Messages

Message
 └── belongs to Conversation

Notification
 ├── belongs to User
 └── belongs to Alert (nullable — chỉ khi type=price_alert)

Holdings  ← KHÔNG phải bảng; tính động từ Transactions trong PortfolioService
```
