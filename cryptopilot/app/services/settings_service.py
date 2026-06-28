"""SettingsService — đọc/ghi cấu hình hệ thống (Phase 6).

Mỗi key có DEFAULT trong code → thiếu row trong DB vẫn chạy được (lazy default).
Admin chỉnh qua trang /admin/settings; các nơi khác đọc qua get/get_bool/get_float.

Key có tác dụng thật:
  alert.default_threshold_usd : pre-fill ngưỡng trong form cảnh báo
  proactive.enabled           : bật/tắt job proactive_agent
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.setting import Setting

# Mô tả từng key cho UI admin + giá trị mặc định
DEFAULTS: dict[str, dict[str, str]] = {
    "alert.default_threshold_usd": {
        "value": "",
        "label": "Ngưỡng giá gợi ý sẵn trong form cảnh báo (USD)",
        "type": "number",
    },
    "proactive.enabled": {
        "value": "true",
        "label": "Bật trợ lý chủ động (job proactive_agent)",
        "type": "bool",
    },
}


class SettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, key: str, default: str | None = None) -> str | None:
        row = (
            self.db.execute(select(Setting).where(Setting.key == key)).scalars().first()
        )
        if row is not None and row.value is not None:
            return row.value
        if default is not None:
            return default
        spec = DEFAULTS.get(key)
        return spec["value"] if spec else None

    def get_bool(self, key: str, default: bool = False) -> bool:
        raw = self.get(key)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    def get_float(self, key: str, default: float | None = None) -> float | None:
        raw = self.get(key)
        if raw is None or raw == "":
            return default
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    def set(self, key: str, value: str) -> None:
        row = (
            self.db.execute(select(Setting).where(Setting.key == key)).scalars().first()
        )
        if row is None:
            row = Setting(key=key, value=value)
            self.db.add(row)
        else:
            row.value = value
        self.db.commit()

    def all_for_admin(self) -> list[dict]:
        """Trả về danh sách key + value hiện tại + nhãn/loại (để render form admin)."""
        out = []
        for key, spec in DEFAULTS.items():
            out.append(
                {
                    "key": key,
                    "label": spec["label"],
                    "type": spec["type"],
                    "value": self.get(key) or "",
                }
            )
        return out
