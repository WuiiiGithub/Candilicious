from datetime import datetime
import re
import unicodedata

CRITERION_LABELS = {
    "time": ("\u23f1\ufe0f", "Time"),
    "wood": ("\U0001fab5", "Wood"),
    "iron": ("\U0001f529", "Iron"),
}


def _visible_width(s: str) -> int:
    """Return the monospace display width of *s*, accounting for wide chars
    (CJK, emoji) and Discord custom emojis like ``<:name:id>``."""
    width = 0
    i = 0
    n = len(s)
    while i < n:
        # Discord custom emoji  <a:name:id> or <:name:id>
        if s[i] == "<" and i + 1 < n and s[i + 1] in ("a", ":"):
            end = s.find(">", i)
            if end != -1:
                width += 2
                i = end + 1
                continue
        cp = ord(s[i])
        # Skip zero-width / combining marks (they add no width themselves)
        cat = unicodedata.category(s[i])
        if cat.startswith("M") or cat in ("Cf", "Cc", "Cs"):
            i += 1
            continue
        eaw = unicodedata.east_asian_width(s[i])
        width += 2 if eaw in ("W", "F") else 1
        i += 1
    return width


def _ljust(s: str, width: int) -> str:
    """Left-justify *s* so its visible width equals *width*."""
    return s + " " * max(0, width - _visible_width(s))


def _rjust(s: str, width: int) -> str:
    """Right-justify *s* so its visible width equals *width*."""
    return " " * max(0, width - _visible_width(s)) + s


def format_duration(secs):
    secs = int(secs or 0)
    hours, rem = divmod(secs, 3600)
    mins = rem // 60
    if hours >= 100:
        return f"{hours}h"
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def leaderboard_template(toppers: list, view: str = 'display_name', criterion: str = 'time') -> str:
    length = len(toppers)
    if length < 3:
        return "Sorry, very less people to rank"

    _, label = CRITERION_LABELS.get(criterion, CRITERION_LABELS["time"])
    title = label

    def _name(u):
        v = u.get(view) or u.get("name") or u.get("_id", "Unknown")
        if _visible_width(v) > 18:
            # Truncate greedily, appending "..." (3 visible chars → 15 + "...")
            out = ""
            w = 0
            for ch in v:
                cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
                if w + cw > 15:
                    break
                out += ch
                w += cw
            v = out + "..."
        return v

    def _score(u):
        amount = u.get("amount") or u.get("value") or 0
        if criterion == "time":
            return format_duration(amount)
        return f"{int(amount):,}"

    header = f"""**`===================================`**
**`| X  |        Name        | {_rjust(title, 8)} |`**
**`-----------------------------------`**
"""
    name = _name(toppers[0])
    first = f"**|**   :first_place: **`| {_ljust(name, 18)} |  "+ f"{_rjust(_score(toppers[0]), 6)}"+ "|`**\n"

    name = _name(toppers[1])
    second = f"**|**   :second_place: **`| {_ljust(name, 18)} |  "+ f"{_rjust(_score(toppers[1]), 6)}"+ "|`**\n"

    name = _name(toppers[2])
    third = f"**|**   :third_place: **`| {_ljust(name, 18)} |  "+ f"{_rjust(_score(toppers[2]), 6)}"+ "|`**\n"

    seperator = "**`-----------------------------------`**\n"
    top4plus = ''
    for idx in range(3,length):
        name = _name(toppers[idx])
        top4plus += f"**`| {_ljust(str(idx+1), 2)}| {_ljust(name, 18)} |  "+ f"{_rjust(_score(toppers[idx]), 6)}"+ "|`**\n"

    footer = "**`===================================`**\n"

    return header+first+second+third+seperator+top4plus+footer

def timenow():
    return datetime.now().strftime("[ %d %b %Y | %H:%M:%S ] ")