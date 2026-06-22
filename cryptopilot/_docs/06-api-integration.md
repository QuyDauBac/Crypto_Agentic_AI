# Tích hợp API ngoài — CryptoPilot

> Thông số cập nhật theo tài liệu chính thức tháng 6/2026. Số liệu free tier (rate limit, model)
> có thể đổi — bạn nên check lại trang docs của từng bên trước khi nộp.
>
> **Ba dịch vụ ngoài, đều theo cùng nguyên tắc:**
> - Gọi **async** (`httpx.AsyncClient` hoặc `client.aio` của Gemini)
> - Bọc sau **Adapter** (đổi provider không phải sửa service)
> - Có **cache** + **graceful degradation** (lỗi không làm sập app)
> - Key lưu trong `.env`, **không hardcode**

| Dịch vụ | Vai trò | Adapter |
|---|---|---|
| CoinGecko | Giá & lịch sử thị trường | `CoinGeckoAdapter` (`MarketDataInterface`) |
| Google Gemini | AI Agent (function calling) | `gemini_client` trong `agent/` |
| CryptoPanic | Tin tức crypto (lọc theo coin) | `CryptoPanicAdapter` (`NewsInterface`) |

---

## 1. CoinGecko — Market Data

| Thuộc tính | Giá trị |
|---|---|
| Kiểu | REST (GET, JSON) |
| Base URL | `https://api.coingecko.com/api/v3` |
| Auth (free) | **Demo API key** qua param `x_cg_demo_api_key=<KEY>` hoặc header `x-cg-demo-api-key` |
| Rate limit (Demo) | ~30 calls/phút, trần ~10.000 calls/tháng → **bắt buộc cache** |
| Đăng ký | coingecko.com/en/api/pricing → "Create Free Account" |

### Endpoints dùng

| Endpoint | Dùng cho | Tham số chính |
|---|---|---|
| `/simple/price` | Giá hiện tại nhiều coin | `ids=bitcoin,ethereum&vs_currencies=usd` |
| `/coins/markets` | Giá + % thay đổi 24h (tối đa 250 coin/lần) | `vs_currency=usd&ids=...` |
| `/coins/{id}/market_chart` | Lịch sử giá N ngày | `vs_currency=usd&days=30` |
| `/coins/list` | Toàn bộ coin (id, symbol, name) | — |
| `/search` | Tìm coin theo tên/symbol | `query=bitcoin` |

### .env

```env
COINGECKO_BASE_URL=https://api.coingecko.com/api/v3
COINGECKO_DEMO_KEY=
```

### Cách gọi (adapter)

```python
# app/adapters/coingecko_adapter.py
async def get_prices(self, ids: list[str]) -> dict[str, float]:
    params = {"ids": ",".join(ids), "vs_currencies": "usd",
              "x_cg_demo_api_key": settings.coingecko_demo_key}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{self.base}/simple/price", params=params)
        r.raise_for_status()
        data = r.json()                       # {"bitcoin": {"usd": 67420}, ...}
    return {cid: data[cid]["usd"] for cid in data}
```

### Vấn đề symbol → id (lý do có bảng `coins`)

CoinGecko nhận **id** (`"bitcoin"`), không nhận symbol (`"btc"`) — và nhiều coin trùng symbol.
Cách chuẩn (theo chính docs CoinGecko):

> Gọi `/coins/list` **một lần**, lưu vào bảng `coins`, tra cứu local để map `btc → bitcoin`.
> Refresh lại ~24h/lần (coin mới list liên tục). Tra local = **không tốn rate limit**.

### Caching & graceful degradation

- Cache giá trong vài chục giây–vài phút (giảm số call, tránh đụng rate limit 30/phút)
- CoinGecko **không trừ credit** nếu response cache giống lần trước → poll nhẹ nhàng vẫn ổn
- Nếu API lỗi/timeout → fallback `coins.last_price` (giá cache cuối) + cờ "dữ liệu cũ"

---

## 2. Google Gemini — AI Agent

| Thuộc tính | Giá trị |
|---|---|
| SDK | **`google-genai`** (`pip install google-genai`) — **không** dùng `google-generativeai` (đã deprecated) |
| Import | `from google import genai` / `from google.genai import types` |
| Model | **`gemini-2.5-flash`** (stable, hợp free tier). *Lưu ý: `gemini-2.0-flash` đã shut down 1/6/2026.* |
| Auth | Env `GEMINI_API_KEY` — SDK tự đọc |
| Free tier | Có quota (Flash ~10 request/phút) → **đây là lý do proactive dùng snapshot, xem 05** |
| Function calling | Có sẵn — đúng cái Agent cần |
| Async | `client.aio.models.generate_content(...)` |

### .env

```env
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
```

> Để model trong `.env` → khi Google ra model mới (vd `gemini-3.5-flash`) chỉ đổi config, không sửa code.

### Khởi tạo + gọi (async, có tools)

```python
# app/agent/gemini_client.py
from google import genai
from google.genai import types

client = genai.Client()                       # tự đọc GEMINI_API_KEY

async def generate(contents, tools):
    return await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=contents,
        config=types.GenerateContentConfig(
            tools=[types.Tool(function_declarations=tools)],
            system_instruction=SYSTEM_PROMPT,
        ),
    )
```

> Cách định nghĩa tool declarations + xử lý `response...function_call` + vòng ReAct: **xem `05-ai-agent.md`**.
> Lưu ý quota: chạy nhiều vòng tool cho mỗi câu hỏi tốn nhiều request → giữ `MAX_STEPS` thấp,
> và proactive gửi snapshot 1 lần thay vì loop từng user.

---

## 3. CryptoPanic — Tin tức

| Thuộc tính | Giá trị |
|---|---|
| Kiểu | REST (GET, JSON) |
| Base URL | `https://cryptopanic.com/api/<plan>/v2/posts/` (`<plan>` = tên gói, vd `developer`) |
| Auth | Param `auth_token=<TOKEN>` (lấy trong dashboard sau khi đăng ký) |
| Lọc theo coin | Param `currencies=BTC,ETH` (CSV symbol) — **khớp đúng nhu cầu lọc theo coin user giữ** |
| Filter khác | `filter` (rising/hot/bullish/bearish/important), `kind` (news/media/all), `regions=en` |
| Rate limit | ~5 req/giây/IP; server cache ~30s → **không gọi quá 1 lần/30s** |
| Free plan | Tin bị **delay** (không real-time) — chấp nhận được cho use case này |

### .env

```env
CRYPTOPANIC_BASE_URL=https://cryptopanic.com/api/developer/v2
CRYPTOPANIC_TOKEN=
```

### Cách gọi (adapter)

```python
# app/adapters/cryptopanic_adapter.py
async def get_news(self, symbols: list[str], limit: int = 5) -> list[dict]:
    params = {"auth_token": settings.cryptopanic_token, "public": "true"}
    if symbols:
        params["currencies"] = ",".join(s.upper() for s in symbols)   # ["btc"] → "BTC"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{self.base}/posts/", params=params)
        r.raise_for_status()
        results = r.json().get("results", [])[:limit]
    return [{"title": p["title"], "url": p["url"],
             "source": p["source"]["title"], "published_at": p["published_at"]}
            for p in results]
```

### Luồng dùng trong Agent

```
NewsService.get_filtered(user, limit):
  → lấy symbol các coin user đang giữ (từ holdings)
  → CryptoPanicAdapter.get_news(symbols, limit)
  → trả về cho tool get_crypto_news → Agent đọc & lọc tiếp khi tổng hợp
```

> **Lưu ý branding:** CryptoPanic không cho dùng tên/logo của họ làm thương hiệu app — chỉ
> dùng dữ liệu, ghi nguồn. Không ảnh hưởng code, nhưng nên biết.

---

## Tổng hợp .env

```env
# CoinGecko
COINGECKO_BASE_URL=https://api.coingecko.com/api/v3
COINGECKO_DEMO_KEY=

# Gemini
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

# CryptoPanic
CRYPTOPANIC_BASE_URL=https://cryptopanic.com/api/developer/v2
CRYPTOPANIC_TOKEN=

# App
JWT_SECRET=
JWT_EXPIRE_MINUTES=60
```

---

## Graceful degradation — tóm tắt

| Lỗi | Hệ thống làm gì |
|---|---|
| CoinGecko timeout/429 | Dùng `coins.last_price` + cờ "dữ liệu cũ"; nhập giao dịch vẫn chạy |
| Gemini lỗi/hết quota | Báo lỗi thân thiện trong chat; portfolio & alerts không ảnh hưởng |
| CryptoPanic lỗi | Agent vẫn trả lời phần phân tích giá; chỉ thiếu phần tin tức |

---

## Ảnh hưởng tới kế hoạch

| Vấn đề | Điều chỉnh |
|---|---|
| Cả 3 đều có rate limit free tier | **Bắt buộc cache** + giới hạn tần suất poll |
| CoinGecko nhận id không nhận symbol | Bảng `coins` + seed từ `/coins/list`, refresh 24h |
| Gemini free tier quota thấp | Proactive dùng snapshot 1 lần/user; `MAX_STEPS` thấp |
| CryptoPanic free delay tin | Chấp nhận tin trễ; nếu cần real-time là gói trả phí (ngoài scope) |
| Model Gemini hay đổi/deprecate | Đặt model trong `.env`, pin bản stable |
