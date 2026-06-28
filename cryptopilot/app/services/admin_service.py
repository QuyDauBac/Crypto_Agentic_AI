"""AdminService — thống kê hệ thống + quản lý user (Phase 6).

Chỉ admin gọi (route bảo vệ bằng get_current_admin). Có chốt an toàn: admin không tự
khóa / tự thu quyền admin của chính mình (tránh tự khóa mình khỏi hệ thống).
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.coin import Coin
from app.models.notification import Notification
from app.models.transaction import Transaction
from app.models.user import User


class AdminService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _count(self, model) -> int:
        return int(
            self.db.execute(select(func.count()).select_from(model)).scalar_one()
        )

    def stats(self) -> dict:
        active_users = int(
            self.db.execute(
                select(func.count()).select_from(User).where(User.is_active.is_(True))
            ).scalar_one()
        )
        total_users = self._count(User)
        return {
            "total_users": total_users,
            "active_users": active_users,
            "locked_users": total_users - active_users,
            "total_transactions": self._count(Transaction),
            "total_alerts": self._count(Alert),
            "active_alerts": int(
                self.db.execute(
                    select(func.count())
                    .select_from(Alert)
                    .where(Alert.is_active.is_(True))
                ).scalar_one()
            ),
            "total_notifications": self._count(Notification),
            "total_coins": self._count(Coin),
        }

    def list_users(self) -> list[User]:
        return list(self.db.execute(select(User).order_by(User.id)).scalars())

    def toggle_active(self, target_user_id: int, acting_admin: User) -> bool:
        """Khóa/mở tài khoản. Không cho admin tự khóa mình. True nếu đổi thành công."""
        if target_user_id == acting_admin.id:
            return False
        user = self.db.get(User, target_user_id)
        if user is None:
            return False
        user.is_active = not user.is_active
        self.db.commit()
        return True

    def toggle_admin(self, target_user_id: int, acting_admin: User) -> bool:
        """Cấp/thu quyền admin. Không cho admin tự thu quyền của mình."""
        if target_user_id == acting_admin.id:
            return False
        user = self.db.get(User, target_user_id)
        if user is None:
            return False
        user.is_admin = not user.is_admin
        self.db.commit()
        return True
