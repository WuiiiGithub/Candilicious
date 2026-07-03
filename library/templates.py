from datetime import datetime

def leaderboard_template(toppers: list, view: str='display_name') -> str:
    length = len(toppers)
    if length < 3:
        return "Sorry, very less people to rank"

    def _name(u):
        v = u.get(view) or u.get("name") or u.get("_id", "Unknown")
        if len(v) > 18:
            v = v[:15] + "..."
        return v

    header = """**`===================================`**
**`| X  |        Name        | Score |`**
**`-----------------------------------`**
"""
    name = _name(toppers[0])
    seconds = toppers[0]['time']
    mins = seconds//60
    hours = seconds//3600
    mins = mins%60
    hours, mins = int(hours), int(mins)
    first = f"**|**   :first_place: **`| {name.ljust(18)} |  "+ f"{hours}:{mins}".rjust(6)+"|`**\n"

    name = _name(toppers[1])
    seconds = toppers[1]['time']
    mins = seconds//60
    hours = seconds//3600
    mins = mins%60
    hours, mins = int(hours), int(mins)
    second = f"**|**   :second_place: **`| {name.ljust(18)} |  "+ f"{hours}:{mins}".rjust(6)+"|`**\n"

    name = _name(toppers[2])
    seconds = toppers[2]['time']
    mins = seconds//60
    hours = seconds//3600
    mins = mins%60
    hours, mins = int(hours), int(mins)
    third = f"**|**   :third_place: **`| {name.ljust(18)} |  "+ f"{hours}:{mins}".rjust(6)+"|`**\n"

    seperator = "**`-----------------------------------`**\n"
    top4plus = ''
    for idx in range(3,length):
        name = _name(toppers[idx])
        seconds = toppers[idx]['time']
        mins = seconds//60
        hours = seconds//3600
        mins = mins%60
        hours, mins = int(hours), int(mins)
        top4plus += f"**`| {str(idx+1).ljust(2)}| {name.ljust(18)} |  "+ f"{hours}:{mins}".rjust(6)+"|`**\n"

    footer = "**`===================================`**\n"

    return header+first+second+third+seperator+top4plus+footer

def timenow():
    return datetime.now().strftime("[ %d %b %Y | %H:%M:%S ] ")