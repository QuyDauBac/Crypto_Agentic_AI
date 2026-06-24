"""PortfolioService — tầng nghiệp vụ danh mục (Phase 3).

Hai nhóm việc:
  1. CRUD transactions (luôn scope theo user_id — user A không đụng được tx của user B)
  2. Tính động holdings + P&L + allocation từ transactions, ghép giá real-time qua MarketService

Holdings KHÔNG có bảng riêng — tính từ transactions theo average-cost (xem 03-database.md).
Logic ở đây dùng chung cho cả UI (dashboard) lẫn AI Agent (Phase 4 tool get_portfolio_summary).
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.coin import Coin
from app.models.transaction import Transaction
from app.schemas.transaction import (
    BtcBenchmark,
    DashboardView,
    HoldingView,
    TransactionCreate,
)
from app.services.market_service import MarketService

_ZERO = Decimal("0")


class _HoldingAgg:
    """Holding nội bộ (Decimal) trước khi ghép giá thị trường."""

    def __init__(self, coin: Coin) -> None:
        self.coin = coin
        self.net_quantity: Decimal = _ZERO
        self.buy_qty: Decimal = _ZERO
        self.buy_cost: Decimal = _ZERO  # Σ(buy.qty × buy.price)

    @property
    def avg_cost_price(self) -> Decimal:
        return (self.buy_cost / self.buy_qty) if self.buy_qty > 0 else _ZERO

    @property
    def cost_basis(self) -> Decimal:
        # giá vốn của phần đang nắm giữ = net_quantity × avg_cost
        return self.net_quantity * self.avg_cost_price


class PortfolioService:
    def __init__(self, db: Session, market_service: MarketService) -> None:
        self.db = db
        self.market = market_service

    # ────────────────────────── CRUD transactions ──────────────────────────
    def list_transactions(self, user_id: int) -> list[Transaction]:
        return list(
            self.db.execute(
                select(Transaction)
                .where(Transaction.user_id == user_id)
                .order_by(Transaction.executed_at.desc(), Transaction.id.desc())
            ).scalars()
        )

    def get_transaction(self, user_id: int, tx_id: int) -> Transaction | None:
        return (
            self.db.execute(
                select(Transaction).where(
                    Transaction.id == tx_id, Transaction.user_id == user_id
                )
            )
            .scalars()
            .first()
        )

    def add_transaction(self, user_id: int, data: TransactionCreate) -> Transaction:
        coin = self._get_or_create_coin(data.coingecko_id, data.symbol, data.name)
        tx = Transaction(
            user_id=user_id,
            coin_id=coin.id,
            type=data.type,
            quantity=data.quantity,
            price=data.price,
            fee=data.fee,
            note=data.note,
            executed_at=data.executed_at,
        )
        self.db.add(tx)
        self.db.commit()
        self.db.refresh(tx)
        return tx

    def update_transaction(
        self, user_id: int, tx_id: int, data: TransactionCreate
    ) -> Transaction | None:
        tx = self.get_transaction(user_id, tx_id)
        if tx is None:
            return None
        coin = self._get_or_create_coin(data.coingecko_id, data.symbol, data.name)
        tx.coin_id = coin.id
        tx.type = data.type
        tx.quantity = data.quantity
        tx.price = data.price
        tx.fee = data.fee
        tx.note = data.note
        tx.executed_at = data.executed_at
        self.db.commit()
        self.db.refresh(tx)
        return tx

    def delete_transaction(self, user_id: int, tx_id: int) -> bool:
        tx = self.get_transaction(user_id, tx_id)
        if tx is None:
            return False
        self.db.delete(tx)
        self.db.commit()
        return True

    def _get_or_create_coin(self, coingecko_id: str, symbol: str, name: str) -> Coin:
        coin = (
            self.db.execute(select(Coin).where(Coin.coingecko_id == coingecko_id))
            .scalars()
            .first()
        )
        if coin is None:
            coin = Coin(
                coingecko_id=coingecko_id,
                symbol=(symbol or coingecko_id).lower(),
                name=name or coingecko_id,
            )
            self.db.add(coin)
            self.db.commit()
            self.db.refresh(coin)
        return coin

    # ────────────────────────── Holdings (tính động) ──────────────────────────
    def get_holdings(self, user_id: int) -> list[_HoldingAgg]:
        """Gộp transactions → holdings. Chỉ trả coin có net_quantity > 0."""
        rows = self.db.execute(
            select(Transaction)
            .join(Coin, Transaction.coin_id == Coin.id)
            .where(Transaction.user_id == user_id)
        ).scalars()

        aggs: dict[int, _HoldingAgg] = {}
        for tx in rows:
            agg = aggs.get(tx.coin_id)
            if agg is None:
                agg = _HoldingAgg(tx.coin)
                aggs[tx.coin_id] = agg
            if tx.type == "buy":
                agg.net_quantity += tx.quantity
                agg.buy_qty += tx.quantity
                agg.buy_cost += tx.quantity * tx.price
            else:  # sell
                agg.net_quantity -= tx.quantity

        return [a for a in aggs.values() if a.net_quantity > 0]

    # ────────────────────────── Dashboard (ghép giá real-time) ──────────────────────────
    async def get_dashboard(
        self, user_id: int, benchmark_days: int = 30
    ) -> DashboardView:
        holdings = self.get_holdings(user_id)
        coin_ids = [h.coin.coingecko_id for h in holdings]
        snapshot = await self.market.get_prices(coin_ids) if coin_ids else None
        prices = snapshot.prices if snapshot else {}

        views: list[HoldingView] = []
        total_value = _ZERO
        total_cost = _ZERO

        for h in holdings:
            cid = h.coin.coingecko_id
            cost_basis = h.cost_basis
            total_cost += cost_basis

            price = prices.get(cid)
            current_value: Decimal | None = None
            unrealized: Decimal | None = None
            pnl_pct: float | None = None
            if price is not None:
                cur = Decimal(str(price)) * h.net_quantity
                current_value = cur
                unrealized = cur - cost_basis
                total_value += cur
                if cost_basis > 0:
                    pnl_pct = float(unrealized / cost_basis * 100)

            views.append(
                HoldingView(
                    coingecko_id=cid,
                    symbol=h.coin.symbol,
                    name=h.coin.name,
                    net_quantity=float(h.net_quantity),
                    avg_cost_price=float(h.avg_cost_price),
                    current_price=float(price) if price is not None else None,
                    cost_basis=float(cost_basis),
                    current_value=float(current_value)
                    if current_value is not None
                    else None,
                    unrealized_pnl=float(unrealized)
                    if unrealized is not None
                    else None,
                    pnl_pct=pnl_pct,
                    allocation_pct=None,  # điền sau khi biết total_value
                )
            )

        # Allocation %: tỷ trọng theo current_value
        if total_value > 0:
            for v in views:
                if v.current_value is not None:
                    v.allocation_pct = round(
                        v.current_value / float(total_value) * 100, 2
                    )

        total_pnl = total_value - total_cost
        total_pnl_pct = float(total_pnl / total_cost * 100) if total_cost > 0 else None

        benchmark = await self._btc_benchmark(benchmark_days, total_pnl_pct)

        return DashboardView(
            holdings=views,
            total_value=float(total_value),
            total_cost=float(total_cost),
            total_pnl=float(total_pnl),
            total_pnl_pct=total_pnl_pct,
            stale=snapshot.stale if snapshot else False,
            as_of=snapshot.as_of if snapshot else datetime.now(timezone.utc),
            benchmark=benchmark,
        )

    async def _btc_benchmark(
        self, days: int, portfolio_return_pct: float | None
    ) -> BtcBenchmark:
        """So sánh đơn giản: % thay đổi BTC trong N ngày (không cùng mốc thời gian với
        danh mục — đây là benchmark thô, có ghi chú trong UI)."""
        btc_change: float | None = None
        history = await self.market.get_history("bitcoin", days)
        if len(history) >= 2:
            first = history[0].price
            last = history[-1].price
            if first:
                btc_change = (last - first) / first * 100
        return BtcBenchmark(
            days=days,
            portfolio_return_pct=portfolio_return_pct,
            btc_change_pct=btc_change,
        )
