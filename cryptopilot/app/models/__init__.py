"""Đăng ký mọi model với Base để create_all() nhận diện.

Thêm model mới ở các phase sau thì import vào đây:
  Coin (Phase 2), Transaction (Phase 3), Alert/Notification, Conversation/Message...
"""

from app.models.user import User

__all__ = ["User"]
