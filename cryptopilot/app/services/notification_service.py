"""NotificationService — hộp thông báo in-app (Phase 5).

Gom cả price_alert (job giá) lẫn agent_insight (proactive agent). Mọi truy vấn scope theo
user_id. Badge navbar đọc unread_count(); trang thông báo đọc list_for_user().
"""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.notification import Notification


class NotificationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        user_id: int,
        type_: str,
        message: str,
        title: str | None = None,
        alert_id: int | None = None,
    ) -> Notification:
        notif = Notification(
            user_id=user_id,
            type=type_,
            message=message,
            title=title,
            alert_id=alert_id,
        )
        self.db.add(notif)
        self.db.commit()
        self.db.refresh(notif)
        return notif

    def list_for_user(self, user_id: int, limit: int = 50) -> list[Notification]:
        return list(
            self.db.execute(
                select(Notification)
                .where(Notification.user_id == user_id)
                .order_by(Notification.id.desc())
                .limit(limit)
            ).scalars()
        )

    def unread_count(self, user_id: int) -> int:
        return int(
            self.db.execute(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.user_id == user_id,
                    Notification.is_read.is_(False),
                )
            ).scalar_one()
        )

    def mark_read(self, user_id: int, notif_id: int) -> bool:
        notif = (
            self.db.execute(
                select(Notification).where(
                    Notification.id == notif_id,
                    Notification.user_id == user_id,  # scope bảo mật
                )
            )
            .scalars()
            .first()
        )
        if notif is None:
            return False
        notif.is_read = True
        self.db.commit()
        return True

    def mark_all_read(self, user_id: int) -> int:
        result = self.db.execute(
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
            )
            .values(is_read=True)
        )
        self.db.commit()
        return int(getattr(result, "rowcount", 0) or 0)
