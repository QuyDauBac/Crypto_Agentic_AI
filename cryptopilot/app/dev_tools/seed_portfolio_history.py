"""seed_portfolio_history — script DEMO/TEST CỤC BỘ, KHÔNG PHẢI job production.

Sinh dữ liệu portfolio_snapshots GIẢ LẬP (random walk +-3%/ngày quanh giá trị hiện tại
của user) để demo chart "Hiệu suất vs Bitcoin" trên /portfolio mà không cần đợi hàng
trăm ngày thật tích lũy qua job app/jobs/portfolio_snapshot.py.

⚠️ CHỈ dùng cục bộ/test — KHÔNG chạy trên môi trường thật. Đặt ở app/dev_tools/ (không
phải app/jobs/) và KHÔNG đăng ký vào scheduler — sẽ không bao giờ tự chạy.

Không bao giờ ghi đè snapshot thật đã có (dữ liệu thật luôn ưu tiên hơn) — ngày nào đã
tồn tại trong portfolio_snapshots thì bỏ qua, chỉ dùng làm mốc neo cho random walk.

Trước khi nộp báo cáo cuối, nếu cần bảng portfolio_snapshots sạch 100% dữ liệu thật:
xoá các dòng do script này tạo (script in ra khoảng ngày đã seed ở cuối mỗi lần chạy;
bảng không có cột đánh dấu is_fake, nên cách đơn giản nhất là xoá theo user + khoảng
ngày đó, hoặc xoá toàn bộ bảng nếu chưa có snapshot thật nào từ job production):
    DELETE FROM portfolio_snapshots WHERE user_id = <id> AND snapshot_date BETWEEN '<start>' AND '<end>';

Chạy:
    python -m app.dev_tools.seed_portfolio_history --email user@example.com --days 365
"""

import argparse
import asyncio
import random
import sys
from datetime import date, timedelta

from app.adapters.coingecko_adapter import CoinGeckoAdapter
from app.core.database import SessionLocal
from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.user import User
from app.services.market_service import MarketService
from app.services.portfolio_service import PortfolioService

_DAILY_CHANGE_RANGE = (
    -0.03,
    0.03,
)  # +-3%/ngày — "không cần chính xác, chỉ cần tự nhiên"
_FLOOR_VALUE = 1.0  # không cho random walk đi âm/về 0


def _existing_values(db, user_id: int, start: date, end: date) -> dict[date, float]:
    rows = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.user_id == user_id,
            PortfolioSnapshot.snapshot_date >= start,
            PortfolioSnapshot.snapshot_date <= end,
        )
        .all()
    )
    return {r.snapshot_date: float(r.total_value) for r in rows}


def _seed_core(
    db,
    portfolio: PortfolioService,
    user_id: int,
    days: int,
    anchor_value: float,
    anchor_cost: float,
    today: date | None = None,
) -> tuple[int, int]:
    """Lõi random-walk — testable (không mở SessionLocal riêng, không gọi CoinGecko).

    Trả (số ngày đã seed giả, số ngày giữ nguyên vì đã có dữ liệu thật).
    """
    today = today or date.today()
    start = today - timedelta(days=days - 1)
    existing = _existing_values(db, user_id, start, today)

    value = existing.get(today, anchor_value)
    seeded, skipped = 0, 0
    d = today
    for _ in range(days):
        if d in existing:
            value = existing[d]  # neo lại về mốc thật — random walk cũ hơn bám sát thật
            skipped += 1
        else:
            pct = random.uniform(*_DAILY_CHANGE_RANGE)
            value = max(value * (1 + pct), _FLOOR_VALUE)
            # total_cost giả lấy CỐ ĐỊNH theo giá vốn thật hiện tại — cost basis chỉ
            # đổi khi có giao dịch mới, không dao động ngày-qua-ngày như market value.
            portfolio.save_snapshot(user_id, d, value, anchor_cost)
            seeded += 1
        d -= timedelta(days=1)
    return seeded, skipped


def seed(email: str, days: int) -> None:
    """Wrapper CLI — mở session thật, tra user qua email, gọi CoinGecko lấy mốc neo."""
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email=email).first()
        if user is None:
            print(f"❌ Không tìm thấy user với email {email!r}.")
            sys.exit(1)

        market = MarketService(db=db, adapter=CoinGeckoAdapter())
        portfolio = PortfolioService(db=db, market_service=market)
        result = asyncio.run(portfolio.get_current_value(user.id))
        if result is None:
            print(
                f"❌ Không tính được giá trị hiện tại cho {email} — cần ít nhất 1 "
                "giao dịch và giá CoinGecko lấy được cho holding đó. Không thể seed."
            )
            sys.exit(1)
        anchor_value, anchor_cost = result

        today = date.today()
        seeded, skipped = _seed_core(
            db, portfolio, user.id, days, anchor_value, anchor_cost, today
        )

        print("⚠️  DỮ LIỆU GIẢ LẬP CHO MỤC ĐÍCH DEMO — KHÔNG PHẢI SỐ LIỆU THẬT")
        print(
            f"Đã seed {seeded} ngày giả cho {email} "
            f"({today - timedelta(days=days - 1)} → {today}), "
            f"giữ nguyên {skipped} ngày đã có dữ liệu thật."
        )
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Seed portfolio_snapshots GIẢ LẬP để demo chart lịch sử — "
            "CHỈ dùng cục bộ/test, không chạy trên môi trường thật."
        )
    )
    parser.add_argument("--email", required=True, help="Email user cần seed")
    parser.add_argument(
        "--days", type=int, default=365, help="Số ngày lùi về trước (mặc định 365)"
    )
    args = parser.parse_args()

    # Console mặc định trên Windows (cp1252) không encode được ⚠️/emoji trong log bên
    # dưới — ép UTF-8 để tránh UnicodeEncodeError làm crash script SAU KHI đã seed
    # xong (dữ liệu vẫn được lưu, chỉ dòng print cuối bị lỗi — nhưng vẫn nên tránh).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    seed(args.email, args.days)


if __name__ == "__main__":
    main()
