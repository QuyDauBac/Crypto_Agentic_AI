# Cảnh báo & Scheduled Jobs — CryptoPilot

> Các tác vụ chạy nền bằng **APScheduler** (`AsyncIOScheduler` — chạy chung event loop với FastAPI,
> nên job có thể `await` gọi CoinGecko/Gemini bình thường).
>
> Mọi thông báo tới user đều ghi vào bảng **`notifications`** (xem `03-database.md`).

---

## Danh sách jobs

| Job | Lịch chạy (mặc định) | Mô tả |
|---|---|---|
| `price_check` | mỗi 10 phút | Kiểm tra alert giá chạm ngưỡng → tạo notification, cập nhật `coins.last_price` |
| `proactive_agent` | mỗi 6 giờ | Agent phân tích danh mục từng user → tạo notification nếu có điều đáng lưu ý |
| `refresh_coins` | mỗi 24 giờ | Làm mới bảng `coins` từ CoinGecko `/coins/list` (map symbol → id) |

> Lịch chạy để trong `settings` / `.env` (vd `alert.default_check_interval_minutes`) để chỉnh
> không cần sửa code. Số ở trên là gợi ý cân bằng giữa "kịp thời" và "tiết kiệm rate limit".

---

## Khởi động scheduler

```python
# app/main.py
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app):
    scheduler.add_job(price_check,     "interval", minutes=10, id="price_check")
    scheduler.add_job(proactive_agent, "interval", hours=6,    id="proactive_agent")
    scheduler.add_job(refresh_coins,   "interval", hours=24,   id="refresh_coins")
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)
```

> Mỗi job bọc `try/except` ở trong: một lần lỗi chỉ bỏ qua chu kỳ đó, **không** làm app sập
> hay dừng scheduler.

---

## Job 1 — `price_check` (cảnh báo giá)

```
price_check():
  alerts = đọc alerts WHERE is_active = true        (DB)
  if not alerts: return

  coin_ids = tập hợp coin_id duy nhất của các alert
  prices   = await MarketService.get_prices(coin_ids)   ← 1 call gộp, không gọi từng coin

  for alert in alerts:
      price = prices[alert.coin.coingecko_id]
      hit = (alert.condition == "above" and price >= alert.threshold_price)
         or (alert.condition == "below" and price <= alert.threshold_price)
      if hit:
          alert.triggered_at = now
          alert.is_active    = false                 ← one-shot, tránh lặp thông báo
          tạo Notification(
              user_id = alert.user_id,
              type    = "price_alert",
              title   = f"{coin} chạm ngưỡng",
              message = f"{coin} hiện {price}$, {condition} ngưỡng {threshold}$ bạn đặt.",
              alert_id = alert.id,
          )

  # tiện thể cập nhật cache giá
  cập nhật coins.last_price từ prices
```

> **Gộp 1 call giá cho tất cả alert** (không lặp từng coin) — quan trọng vì CoinGecko free chỉ
> ~30 calls/phút. Tính idempotent: alert đã trigger thì `is_active=false` nên chu kỳ sau không tạo lại.

---

## Job 2 — `proactive_agent` (Agent chủ động)

```
proactive_agent():
  users = đọc user đang active VÀ có holdings        (bỏ qua user danh mục rỗng → tiết kiệm quota)

  for user in users:
      snapshot = {
        summary    : PortfolioService.get_summary(user),
        allocation : PortfolioService.get_allocation(user),
        movers     : coin biến động mạnh 24h trong danh mục,
        news       : await NewsService.get_filtered(user, limit=3),
      }
      text = await gemini.generate([PROACTIVE_PROMPT, snapshot_as_text])   ← 1 call/user
      if text.strip() != "NONE":
          tạo Notification(
              user_id = user.id,
              type    = "agent_insight",
              title   = "Nhận định từ trợ lý",
              message = text,
          )
```

> Nhắc lại quyết định ở `05-ai-agent.md`: proactive **gửi snapshot dựng sẵn, 1 call Gemini/user**,
> **không** chạy full vòng ReAct cho từng user — để không đốt quota free tier. `PROACTIVE_PROMPT`
> yêu cầu Agent trả `NONE` nếu không có gì đáng báo (tránh spam thông báo vô nghĩa).

> **Chống trùng (nice-to-have):** có thể bỏ qua nếu user đã nhận `agent_insight` trong X giờ gần đây,
> tránh lặp cùng một nhận định. MVP có thể chưa cần.

---

## Job 3 — `refresh_coins` (làm mới cache coin)

```
refresh_coins():
  data = await MarketService.get_coin_list()    ← CoinGecko /coins/list (1 call)
  upsert vào bảng coins: coingecko_id, symbol, name
```

> Coin mới được list liên tục → refresh 24h/lần để map `symbol → coingecko_id` luôn đúng
> (đúng khuyến nghị của CoinGecko). Tra cứu lúc user nhập giao dịch dùng bảng local này,
> **không** tốn rate limit.

---

## Hiển thị notification cho user

- Badge số thông báo chưa đọc (`is_read = false`) trên navbar
- Trang/dropdown danh sách notification: mới nhất trước, phân biệt `price_alert` vs `agent_insight`
- Click vào → đánh dấu `is_read = true`
- (Mở rộng ngoài MVP) gửi thêm qua email — hiện tại chỉ in-app

---

## Lưu ý vận hành

| Vấn đề | Cách xử lý |
|---|---|
| Job đụng rate limit CoinGecko | Gộp call (1 lần cho nhiều coin), giãn lịch, cache giá |
| Quota Gemini (proactive) | Bỏ qua user danh mục rỗng; 1 call/user; giãn xuống mỗi 6–12h nếu cần |
| Job chạy lâu hơn chu kỳ | APScheduler mặc định không chạy chồng (`max_instances=1`); để vậy |
| App restart | Job `interval` tự lên lịch lại khi `lifespan` chạy; không cần job store bền (MVP) |
| 1 user lỗi trong proactive | `try/except` quanh từng user → 1 user lỗi không chặn các user còn lại |

---

## Liên kết file khác

- Bảng `alerts`, `notifications` ở `03-database.md`
- `MarketService` / `NewsService` / `PortfolioService` ở `04-architecture.md`
- `PROACTIVE_PROMPT` + lý do dùng snapshot ở `05-ai-agent.md`
- Thông số rate limit / quota ở `06-api-integration.md`
