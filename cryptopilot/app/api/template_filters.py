"""Jinja filters/globals dùng chung cho các router server-rendered.

Mỗi router tạo Jinja2Templates instance riêng (portfolio, market...) — filter đăng ký
ở instance này KHÔNG tự có ở instance kia. Module này gom một chỗ; router nào cần thì
gọi register(templates.env) ngay sau khi khởi tạo.
"""

from jinja2 import Environment


def _usd(value, decimals=2):
    if value is None:
        return "—"
    return f"${float(value):,.{decimals}f}"


def _usd_signed(value):
    if value is None:
        return "—"
    return f"{float(value):+,.2f}"


def _qty(value):
    if value is None:
        return "—"
    s = f"{float(value):,.6f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _pct(value, decimals=2):
    if value is None:
        return "—"
    return f"{float(value):+.{decimals}f}%"


def _coin_color(symbol):
    palette = [
        "#f7931a",
        "#627eea",
        "#14b8a6",
        "#2a5ada",
        "#3468d1",
        "#e84142",
        "#e6007a",
        "#8247e5",
        "#3b4552",
        "#c2a633",
    ]
    idx = sum(ord(c) for c in symbol) % len(palette)
    return palette[idx]


def register(env: Environment) -> None:
    env.filters["usd"] = _usd
    env.filters["usd_signed"] = _usd_signed
    env.filters["qty"] = _qty
    env.filters["pct"] = _pct
    env.globals["coin_color"] = _coin_color
