"""Time normalization for check-in / check-out (plan §11).

Examples:
  "15:00"                  -> start "15:00", end None,  display "15:00"
  "15:00-19:00"            -> start "15:00", end "19:00", display "15:00-19:00"
  "16:00-"                 -> start "16:00", end None,  display "16:00-"
  "1500 15:00以前対応可"    -> start "15:00", notes "15:00以前対応可"
  "適宜" / "随時"          -> start/end None, notes "適宜"
"""

import re

from henroyado.normalize.text import normalize_digits

SEP = r"[-~〜～–]"


def _opt(value):
    value = value.strip()
    return value if value else None


def _hhmm(h, m):
    return "%02d:%02d" % (h, m)


def _collapse(text):
    return re.sub(r"\s+", " ", text.replace("\n", " ").replace("\xa0", " ")).strip()


def _range_match(t):
    return re.match(r"(\d{1,2}):(\d{2})\s*%s\s*(\d{1,2}):(\d{2})" % SEP, t)


def _single_match(t):
    return re.match(r"(\d{1,2}):(\d{2})", t)


def parse_time_range(text):
    """Extract a leading time expression from text.

    Returns (start, end, display, notes):
      start  - "HH:MM" or None
      end    - "HH:MM" or None (open-ended ranges have end None)
      display- canonical string ("15:00", "15:00-19:00", "16:00-")
      notes  - remaining text after the time expression
    """
    if not text:
        return None, None, None, None
    t = _collapse(normalize_digits(text))

    m = _range_match(t)
    if m:
        s = _hhmm(int(m.group(1)), int(m.group(2)))
        e = _hhmm(int(m.group(3)), int(m.group(4)))
        return s, e, s + "-" + e, _opt(t[m.end():])

    m = _single_match(t)
    if m:
        s = _hhmm(int(m.group(1)), int(m.group(2)))
        end = m.end()
        # swallow a dangling separator (open-ended "15:00-", not a range)
        sep = re.match(r"\s*%s\s*" % SEP, t[end:])
        display = s + "-" if sep else s
        if sep:
            end += sep.end()
        return s, None, display, _opt(t[end:])

    # 4-digit HHMM ("1500" -> "15:00")
    m = re.match(r"(\d{2})(\d{2})(?![0-9])", t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if h <= 23 and mi <= 59:
            s = _hhmm(h, mi)
            return s, None, s, _opt(t[m.end():])

    return None, None, None, t


def find_time_range(text):
    """Find a time expression anywhere in text. Returns (start, end, display)."""
    if not text:
        return None, None, None
    t = normalize_digits(text)
    m = re.search(r"(\d{1,2}):(\d{2})\s*%s\s*(\d{1,2}):(\d{2})" % SEP, t)
    if m:
        s = _hhmm(int(m.group(1)), int(m.group(2)))
        e = _hhmm(int(m.group(3)), int(m.group(4)))
        return s, e, s + "-" + e
    m = re.search(r"(\d{1,2}):(\d{2})", t)
    if m:
        s = _hhmm(int(m.group(1)), int(m.group(2)))
        end = m.end()
        sep = re.match(r"\s*%s\s*" % SEP, t[end:])
        display = s + "-" if sep else s
        return s, None, display
    return None, None, None
