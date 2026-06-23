# Chạy CryptoPilot (dev)

```bash
# 1. Tạo & kích hoạt virtualenv
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Cài dependencies
pip install -r requirements.txt

# 3. Tạo .env từ mẫu rồi điền key
cp .env.example .env            # đặt JWT_SECRET, các API key

# 4. Chạy dev server
uvicorn app.main:app --reload

# 5. Mở http://127.0.0.1:8000  và  http://127.0.0.1:8000/health
# Chạy test:
pytest
```
