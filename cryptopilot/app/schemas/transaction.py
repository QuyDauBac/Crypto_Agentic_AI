"""Schemas Phase 3 — transaction input + holdings/dashboard output.

Dùng Decimal cho input số lượng/giá (chính xác), float cho output hiển thị.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class TransactionCreate(BaseModel):
    """Dữ liệu user nhập khi thêm/sửa giao dịch.

    coin được nhận diện qua coingecko_id (lấy từ ô search Phase 2); symbol/name đi kèm để
    get-or-create bản ghi Coin nếu chưa có.
    """

    coingecko_id: str
    symbol: str = ""
    name: str = ""
    type: Literal["buy", "sell"]
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(ge=0)
    fee: Decimal | None = Field(default=None, ge=0)
    note: str | None = None
    executed_at: datetime


class HoldingView(BaseModel):
    """Một dòng holding đã tính lãi/lỗ."""

    coingecko_id: str
    symbol: str
    name: str
    net_quantity: float
    avg_cost_price: float
    current_price: float | None
    cost_basis: float
    current_value: float | None
    unrealized_pnl: float | None
    pnl_pct: float | None
    allocation_pct: float | None


class BtcBenchmark(BaseModel):
    """So sánh đơn giản: hiệu suất danh mục vs BTC trong N ngày."""

    days: int
    portfolio_return_pct: float | None
    btc_change_pct: float | None


class DashboardView(BaseModel):
    """Toàn cảnh danh mục để render dashboard."""

    holdings: list[HoldingView]
    total_value: float
    total_cost: float
    total_pnl: float
    total_pnl_pct: float | None
    stale: bool = False  # giá đang là dữ liệu cũ (CoinGecko lỗi)
    as_of: datetime | None = None
    benchmark: BtcBenchmark | None = None
