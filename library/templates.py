from datetime import datetime

RESOURCE_LABELS = {
    "wood": ("\U0001fab5", "Wood"),
    "iron": ("\U0001f529", "Iron"),
}


def leaderboard_template(toppers: list, view: str = 'display_name', resource: str = 'wood') -> str:
    length = len(toppers)
    if length < 3:
        return "Sorry, very less people to rank"

    emoji, label = RESOURCE_LABELS.get(resource, RESOURCE_LABELS["wood"])
    title = f"{emoji} {label}"

    def _name(u):
        v = u.get(view) or u.get("name") or u.get("_id", "Unknown")
        if len(v) > 18:
            v = v[:15] + "..."
        return v

    def _score(u):
        amount = u.get("amount") or u.get("value") or 0
        return f"{int(amount):,}"

    header = f"""**`===================================`**
**`| X  |        Name        | {title.rjust(8)} |`**
**`-----------------------------------`**
"""
    name = _name(toppers[0])
    first = f"**|**   :first_place: **`| {name.ljust(18)} |  "+ f"{_score(toppers[0]).rjust(6)}"+ "|`**\n"

    name = _name(toppers[1])
    second = f"**|**   :second_place: **`| {name.ljust(18)} |  "+ f"{_score(toppers[1]).rjust(6)}"+ "|`**\n"

    name = _name(toppers[2])
    third = f"**|**   :third_place: **`| {name.ljust(18)} |  "+ f"{_score(toppers[2]).rjust(6)}"+ "|`**\n"

    seperator = "**`-----------------------------------`**\n"
    top4plus = ''
    for idx in range(3,length):
        name = _name(toppers[idx])
        top4plus += f"**`| {str(idx+1).ljust(2)}| {name.ljust(18)} |  "+ f"{_score(toppers[idx]).rjust(6)}"+ "|`**\n"

    footer = "**`===================================`**\n"

    return header+first+second+third+seperator+top4plus+footer

def timenow():
    return datetime.now().strftime("[ %d %b %Y | %H:%M:%S ] ")