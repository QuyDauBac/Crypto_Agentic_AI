# AI Agent — CryptoPilot

> **File trọng tâm của đồ án.** Thiết kế chi tiết AI Agent: tools, system prompt, vòng ReAct,
> chế độ chủ động (proactive) và các giới hạn an toàn.
>
> Provider: **Google Gemini API** (`google-genai` SDK). Agent được **hand-roll** — tự viết vòng
> ReAct và xử lý function call, **không** dùng framework như LangChain (để chứng minh hiểu bản chất).

---

## Agent này khác chatbot ở chỗ nào?

Một chatbot thường: nhận câu hỏi → trả lời bằng kiến thức có sẵn (và dễ **bịa** số liệu).

Agent của CryptoPilot: nhận câu hỏi → **tự quyết định cần dữ liệu gì** → **gọi tool** để lấy
dữ liệu thật → đọc kết quả → nếu cần thì gọi tool tiếp → **tổng hợp** thành câu trả lời.
Nó không bịa giá hay số dư — mọi con số đều đến từ tool (DB hoặc CoinGecko).

Agent chạy ở **2 chế độ**:
- **Reactive** — trả lời khi user chat (vòng ReAct theo yêu cầu)
- **Proactive** — tự chạy theo lịch, phát hiện rủi ro/tin quan trọng và cảnh báo mà user không cần hỏi

---

## 4 khái niệm nền (áp vào dự án này)

| Khái niệm | Trong CryptoPilot là gì |
|---|---|
| **Tool Use / Function Calling** | Agent gọi `get_portfolio_summary`, `get_coin_price`... thay vì tự bịa dữ liệu |
| **ReAct (Reason + Act)** | Vòng lặp: *nghĩ* cần gì → *gọi tool* → *đọc* kết quả → nghĩ tiếp → trả lời |
| **System Prompt** | Đoạn text định nghĩa vai trò, luật, danh sách tool — "tính cách" của Agent |
| **Context Window** | Giới hạn token mỗi lượt → chỉ gửi N tin nhắn gần nhất + dữ liệu cần thiết, không dump cả DB |

---

## Tools — Agent có thể tự gọi gì

Agent được trao **5 tools**. Mỗi tool là một hàm Python, có khai báo (declaration) gửi cho Gemini
để nó biết tool tồn tại và cách gọi.

| Tool | Mô tả (Gemini đọc cái này để quyết) | Tham số | Trả về |
|---|---|---|---|
| `get_portfolio_summary` | Danh mục hiện tại của user: coin, số lượng, giá vốn, giá trị, lãi/lỗ | — | list holdings + tổng P&L |
| `get_portfolio_allocation` | Tỷ trọng % từng coin trong danh mục (phát hiện tập trung rủi ro) | — | list { coin, percent } |
| `get_coin_price` | Giá USD hiện tại của một coin | `coingecko_id` | giá hiện tại |
| `get_coin_history` | Lịch sử giá N ngày (đánh giá xu hướng lên/xuống) | `coingecko_id`, `days` | list điểm giá |
| `get_crypto_news` | Tin tức crypto gần đây, lọc theo coin user quan tâm | `coingecko_ids?`, `limit` | list headline + nguồn |

> **Quan trọng:** Agent **không nhận `user_id` làm tham số**. Tool dispatcher tự gắn user đang
> đăng nhập (xem mục Dispatcher) → Agent **không thể** đọc danh mục người khác kể cả khi bị "dụ".

### Ví dụ một declaration (định dạng google-genai)

```python
# app/agent/tools.py
from google.genai import types

get_coin_history_decl = types.FunctionDeclaration(
    name="get_coin_history",
    description=(
        "Lấy lịch sử giá của một coin trong N ngày gần nhất, "
        "dùng để đánh giá xu hướng tăng/giảm. Gọi khi user hỏi về "
        "biến động, xu hướng, hoặc 'coin X dạo này thế nào'."
    ),
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "coingecko_id": types.Schema(type="STRING", description="id CoinGecko, vd 'bitcoin'"),
            "days": types.Schema(type="INTEGER", description="Số ngày, vd 7, 30, 90"),
        },
        required=["coingecko_id", "days"],
    ),
)
```

> `description` viết càng rõ thì Gemini càng chọn đúng tool. Đây là phần "prompt engineering"
> quan trọng — tool mô tả mơ hồ → Agent gọi sai hoặc không gọi.

---

## System Prompt

Đoạn text này gửi kèm mọi lượt chat, định nghĩa "con người" của Agent:

```text
You are CryptoPilot Assistant, a portfolio analysis assistant for an individual
crypto investor. You help the user understand their own portfolio.

RULES:
- Always answer in Vietnamese (the user's language).
- NEVER invent numbers. Every price, balance, or percentage MUST come from a tool
  result. If you don't have data, call the appropriate tool.
- You analyze and explain. You do NOT give definitive buy/sell advice. You may point
  out risks (e.g. heavy concentration in one coin) but always note this is not
  financial advice and the final decision is the user's.
- Only reason about THIS user's portfolio. Never reference other users.
- Be concise and concrete. Prefer specific figures from tools over vague statements.

TOOLS AVAILABLE:
- get_portfolio_summary: the user's holdings and profit/loss
- get_portfolio_allocation: percentage weight of each coin
- get_coin_price: current price of a coin
- get_coin_history: price history to judge a trend
- get_crypto_news: recent crypto news, filtered to coins the user holds

When a question needs data, call tools first, then answer based on the results.
```

> Hai luật quan trọng nhất khi thuyết trình: **(1) không bịa số** (chống hallucination), và
> **(2) không tư vấn mua/bán khẳng định** (an toàn pháp lý + đạo đức). Cả hai đều dễ bị thầy/cô hỏi.

---

## Chế độ Reactive — vòng ReAct khi chat

```
POST /agent/chat  (async)
  history = ChatService.load_history(conversation, last_n=10)   ← context window

  orchestrator.run(user, message, history):
    contents = [system_prompt] + history + [message]
    loop (tối đa MAX_STEPS, vd 5 vòng — tránh lặp vô hạn):
        resp = await gemini.generate(contents, tools=ALL_TOOLS)
        if resp có function_call:
            result = tools.dispatch(fc.name, fc.args, user)   ← gọi service
            contents += [fc, function_response(result)]
            continue                                          ← cho Gemini "đọc" kết quả
        else:
            return resp.text                                  ← câu trả lời cuối

  ChatService.save(user_msg, assistant_msg)
```

### Ví dụ chạy thật — *"Danh mục tôi có đang rủi ro không?"*

```
1. Gemini nghĩ: cần biết tỷ trọng danh mục
   → gọi get_portfolio_allocation()
   → kết quả: BTC 75%, ETH 15%, DOGE 10%

2. Gemini nghĩ: BTC chiếm 75% — khá tập trung. Xem xu hướng BTC gần đây
   → gọi get_coin_history("bitcoin", 30)
   → kết quả: giảm 12% trong 30 ngày

3. Gemini nghĩ: đủ dữ liệu → tổng hợp
   → trả lời: "Danh mục của bạn đang khá tập trung: BTC chiếm 75%, nghĩa là biến động
      của bạn gần như phụ thuộc hoàn toàn vào Bitcoin. 30 ngày qua BTC giảm ~12%...
      (đây là phân tích, không phải lời khuyên đầu tư)."
```

> Đây chính là cảnh bạn nên **demo trực tiếp** — nó cho thấy Agent **lý luận nhiều bước** và
> **kết hợp nhiều nguồn dữ liệu**, thứ mà if-else không làm linh hoạt được.

---

## Chế độ Proactive — Agent tự cảnh báo

Một job (APScheduler — xem `07-alerts-jobs.md`) chạy định kỳ. Với mỗi user đang hoạt động:

```
proactive_check(user):
  snapshot = {
    summary    : PortfolioService.get_summary(user),
    allocation : PortfolioService.get_allocation(user),
    movers     : các coin biến động mạnh 24h,
    news       : NewsService lọc tin liên quan coin user giữ,
  }
  resp = await gemini.generate([PROACTIVE_PROMPT, snapshot_as_text])
  if resp != "NONE":
      tạo notification cho user (lưu DB) + (optional) gửi email
```

`PROACTIVE_PROMPT` yêu cầu: *"Dựa trên snapshot, có điều gì user nên biết ngay không (rủi ro
tập trung, biến động lớn, tin quan trọng)? Nếu có, viết 1–2 câu cảnh báo ngắn. Nếu không, trả về
đúng chữ NONE."*

> **Quyết định tôi đã làm (vì lý do chi phí — bạn xem có đồng ý không):** ở chế độ proactive,
> job **dựng sẵn snapshot rồi gửi 1 lần** thay vì để Agent gọi tool vòng vòng cho từng user.
> Lý do: nếu mỗi user mỗi chu kỳ đều chạy full ReAct loop thì **đốt quota Gemini free tier rất
> nhanh**. Cách "snapshot 1 phát" giới hạn ~1 lần gọi Gemini / user / chu kỳ. Nếu bạn muốn
> proactive cũng "agentic" đầy đủ (cho gọi tool), tôi đổi lại được — chỉ cần chấp nhận tốn quota hơn.

---

## Tool Dispatcher — map function call → service

```python
# app/agent/tools.py
async def dispatch(name: str, args: dict, user: User) -> dict:
    # user KHÔNG đến từ Gemini — gắn từ session, đây là lớp bảo mật
    match name:
        case "get_portfolio_summary":
            return portfolio_service.get_summary(user)
        case "get_portfolio_allocation":
            return portfolio_service.get_allocation(user)
        case "get_coin_price":
            return await market_service.get_price(args["coingecko_id"])
        case "get_coin_history":
            return await market_service.get_history(args["coingecko_id"], args["days"])
        case "get_crypto_news":
            return await news_service.get_filtered(user, args.get("limit", 5))
        case _:
            return {"error": "unknown tool"}
```

> Agent **chỉ phát tên tool + tham số**; việc *thực thi* nằm ở code mình kiểm soát hoàn toàn.
> Validate tham số ở đây, và luôn scope theo `user` — Agent không bao giờ tự chọn được user khác.

---

## Quản lý Context Window

- Mỗi lượt chat gửi: `system_prompt` + **10 tin nhắn gần nhất** + tin hiện tại + kết quả tool.
- Không gửi toàn bộ lịch sử (tốn token, dễ vượt giới hạn) và **không dump cả danh mục/DB** vào
  prompt — dữ liệu chỉ vào context khi tool trả về.
- Nếu hội thoại quá dài: cắt còn N tin gần nhất (MVP). Nâng cấp sau: tóm tắt các tin cũ.

---

## An toàn & xử lý lỗi

| Tình huống | Xử lý |
|---|---|
| Gemini lỗi / hết quota | Báo lỗi thân thiện trong khung chat; portfolio & alerts vẫn chạy (graceful degradation) |
| Agent gọi tool với tham số sai | Dispatcher validate → trả `{"error": ...}` để Gemini tự sửa ở vòng sau |
| Agent lặp gọi tool không dừng | Giới hạn `MAX_STEPS` (vd 5) → cắt vòng, trả lời với dữ liệu đang có |
| User cố "dụ" xem danh mục người khác | Không thể — `user` gắn từ session, không từ tham số Agent |
| User hỏi "nên mua coin gì" | Agent giải thích + phân tích, **không** ra lệnh mua/bán, kèm disclaimer |

---

## Liên kết file khác

- Tools gọi xuống service ở `04-architecture.md`
- Nguồn dữ liệu (Gemini, CoinGecko, news) ở `06-api-integration.md`
- Job proactive + lịch chạy ở `07-alerts-jobs.md`
- Bảng `conversations` / `messages` ở `03-database.md`
