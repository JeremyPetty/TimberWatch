import html
import math
import re
from datetime import datetime, date
from urllib.parse import urlencode


def esc(value) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def fmt_date(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def to_int(value, default=1, minimum=None, maximum=None):
    try:
        n = int(value)
    except Exception:
        n = default
    if minimum is not None:
        n = max(minimum, n)
    if maximum is not None:
        n = min(maximum, n)
    return n


def clean_snippet(text: str, max_len: int = 360) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "..."


def build_url(path: str, **params) -> str:
    clean = {k: v for k, v in params.items() if v is not None and v != ""}
    return f"{path}?{urlencode(clean)}" if clean else path


def page_count(total: int, per_page: int) -> int:
    if per_page <= 0:
        return 1
    return max(1, math.ceil(total / per_page))
