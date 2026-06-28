"""Schemas cho Alerts (Phase 5).

AlertCreate: dữ liệu user nhập khi đặt cảnh báo giá. coin nhận qua coingecko_id (+ symbol/name
để tạo Coin nếu chưa có, giống TransactionCreate). condition giới hạn above|below.
"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class AlertCreate(BaseModel):
    coingecko_id: str = Field(min_length=1, max_length=100)
    symbol: str = ""
    name: str = ""
    condition: Literal["above", "below"]
    threshold_price: Decimal = Field(gt=0)
