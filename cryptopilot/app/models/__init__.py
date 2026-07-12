"""Đăng ký mọi model với Base để create_all() nhận diện.

Thêm model mới ở các phase sau thì import vào đây:
  Coin (Phase 2), Transaction (Phase 3), Conversation/Message (Phase 4),
  Alert/Notification (Phase 5), Setting (Phase 6), OKXConnection/OKXSyncedFill (Phase 8),
  PortfolioSnapshot (Phase 9).
"""

from app.models.user import User
from app.models.coin import Coin  # noqa: F401
from app.models.transaction import Transaction  # noqa: F401
from app.models.conversation import Conversation  # noqa: F401
from app.models.message import Message  # noqa: F401
from app.models.alert import Alert  # noqa: F401
from app.models.notification import Notification  # noqa: F401
from app.models.setting import Setting  # noqa: F401
from app.models.okx_connection import OKXConnection  # noqa: F401
from app.models.okx_synced_fill import OKXSyncedFill  # noqa: F401
from app.models.portfolio_snapshot import PortfolioSnapshot  # noqa: F401

__all__ = ["User"]
