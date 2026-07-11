"""OKXService — quản lý kết nối ví OKX và đồng bộ giao dịch về Transaction (Phase 8).

Luồng chính:
  connect()    → validate key bằng cách gọi thử OKX (get_balance), mã hóa rồi lưu DB
  disconnect() → xóa connection của user (KHÔNG xóa transactions đã sync trước đó)
  get_status() → is_connected + last_synced_at (KHÔNG BAO GIỜ trả key)
  sync()       → lấy fills-history từ OKX → map symbol → coingecko_id → tạo Transaction
                 (bỏ qua fill đã sync trước đó, xem OKXSyncedFill)

Bảo mật: user_id LUÔN lấy từ tham số do route truyền vào (route lấy từ JWT session,
không bao giờ từ request body/param) — service này không tự ý đọc user nào khác.
"""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.okx_adapter import OKXAdapter, OKXAPIError
from app.core.encryption import decrypt, encrypt
from app.models.coin import Coin
from app.models.okx_connection import OKXConnection
from app.models.okx_synced_fill import OKXSyncedFill
from app.schemas.okx import OKXConnectRequest, OKXStatusView, OKXSyncResult
from app.schemas.transaction import TransactionCreate
from app.services.market_service import MarketService
from app.services.portfolio_service import PortfolioService


class OKXConnectError(RuntimeError):
    """Không kết nối được — key/secret/passphrase sai hoặc OKX từ chối."""


class OKXNotConnectedError(RuntimeError):
    """User gọi sync() nhưng chưa connect ví OKX."""


class OKXService:
    def __init__(self, db: Session, market_service: MarketService) -> None:
        self.db = db
        self.market = market_service

    # ────────────────────────── Connect / Disconnect ──────────────────────────
    def _get_connection(self, user_id: int) -> OKXConnection | None:
        return (
            self.db.execute(
                select(OKXConnection).where(OKXConnection.user_id == user_id)
            )
            .scalars()
            .first()
        )

    async def connect(self, user_id: int, data: OKXConnectRequest) -> OKXStatusView:
        adapter = OKXAdapter(data.api_key, data.api_secret, data.passphrase)
        try:
            await adapter.get_balance()
        except Exception as exc:  # noqa: BLE001 — bất kỳ lỗi nào từ OKX đều coi là key sai
            raise OKXConnectError(
                "Không kết nối được tới OKX — kiểm tra lại API Key/Secret/Passphrase "
                "và đảm bảo đã bật quyền Read trên OKX."
            ) from exc

        conn = self._get_connection(user_id)
        if conn is None:
            conn = OKXConnection(user_id=user_id)
            self.db.add(conn)
        conn.api_key_encrypted = encrypt(data.api_key)
        conn.api_secret_encrypted = encrypt(data.api_secret)
        conn.passphrase_encrypted = encrypt(data.passphrase)
        self.db.commit()
        self.db.refresh(conn)
        return OKXStatusView(is_connected=True, last_synced_at=conn.last_synced_at)

    def disconnect(self, user_id: int) -> bool:
        conn = self._get_connection(user_id)
        if conn is None:
            return False
        self.db.delete(conn)
        self.db.commit()
        return True

    def get_status(self, user_id: int) -> OKXStatusView:
        conn = self._get_connection(user_id)
        if conn is None:
            return OKXStatusView(is_connected=False, last_synced_at=None)
        return OKXStatusView(is_connected=True, last_synced_at=conn.last_synced_at)

    # ────────────────────────── Sync ──────────────────────────
    def _adapter_for(self, conn: OKXConnection) -> OKXAdapter:
        return OKXAdapter(
            decrypt(conn.api_key_encrypted),
            decrypt(conn.api_secret_encrypted),
            decrypt(conn.passphrase_encrypted),
        )

    def _already_synced(self, user_id: int, okx_fill_id: str) -> bool:
        return (
            self.db.execute(
                select(OKXSyncedFill).where(
                    OKXSyncedFill.user_id == user_id,
                    OKXSyncedFill.okx_fill_id == okx_fill_id,
                )
            )
            .scalars()
            .first()
            is not None
        )

    async def _resolve_coin(self, symbol: str) -> Coin | None:
        """Map symbol OKX (vd 'BTC') → Coin nội bộ. Tra local trước, không có thì search
        CoinGecko (tốn 1 call mạng) rồi upsert — giống cách MarketService đã làm ở nơi khác.
        """
        sym = symbol.strip().lower()
        local = (
            self.db.execute(select(Coin).where(Coin.symbol == sym)).scalars().first()
        )
        if local:
            return local
        results = await self.market.search_coins(symbol)
        for r in results:
            if r.symbol.strip().lower() == sym:
                return (
                    self.db.execute(
                        select(Coin).where(Coin.coingecko_id == r.coingecko_id)
                    )
                    .scalars()
                    .first()
                )
        return None

    async def sync(self, user_id: int) -> OKXSyncResult:
        conn = self._get_connection(user_id)
        if conn is None:
            raise OKXNotConnectedError("Chưa kết nối ví OKX.")

        adapter = self._adapter_for(conn)
        try:
            fills = await adapter.get_fills_history()
        except OKXAPIError as exc:
            raise OKXConnectError(f"OKX từ chối yêu cầu: {exc}") from exc

        portfolio = PortfolioService(self.db, self.market)
        imported = 0

        for fill in fills:
            fill_id = str(fill.get("tradeId") or fill.get("billId") or "")
            if not fill_id or self._already_synced(user_id, fill_id):
                continue

            inst_id = str(fill.get("instId", ""))  # vd "BTC-USDT"
            base_symbol = inst_id.split("-")[0] if "-" in inst_id else inst_id
            if not base_symbol:
                continue

            coin = await self._resolve_coin(base_symbol)
            if coin is None:
                continue  # không map được coin lạ → bỏ qua, không chặn cả lần sync

            try:
                quantity = Decimal(str(fill.get("fillSz", "0")))
                price = Decimal(str(fill.get("fillPx", "0")))
            except InvalidOperation:
                continue
            if quantity <= 0 or price < 0:
                continue

            side = str(fill.get("side", "buy")).lower()
            tx_type = "sell" if side == "sell" else "buy"

            ts_raw = fill.get("ts") or ""
            try:
                executed_at = datetime.fromtimestamp(int(ts_raw) / 1000, tz=UTC)
            except (TypeError, ValueError):
                executed_at = datetime.now(UTC)

            tx = portfolio.add_transaction(
                user_id,
                TransactionCreate(
                    coingecko_id=coin.coingecko_id,
                    symbol=coin.symbol,
                    name=coin.name,
                    type=tx_type,  # type: ignore[arg-type]
                    quantity=quantity,
                    price=price,
                    note="Đồng bộ từ OKX",
                    executed_at=executed_at,
                ),
            )
            self.db.add(
                OKXSyncedFill(
                    user_id=user_id, okx_fill_id=fill_id, transaction_id=tx.id
                )
            )
            imported += 1

        conn.last_synced_at = datetime.now(UTC)
        self.db.commit()
        return OKXSyncResult(imported=imported, total_fills=len(fills))
