from datetime import datetime

def leaderboard_template(toppers: list, view: str='display_name') -> str:
    length = len(toppers)
    if length < 3:
        return "Sorry, very less people to rank"
    else:
        header = """**`===================================`**
**`| X  |        Name        | Score |`**
**`-----------------------------------`**
"""
        name = toppers[0][view]
        if len(name) > 18:
            name = name[:15] + "..."
        seconds = toppers[0]['time']
        mins = seconds//60
        hours = seconds//3600
        mins = mins%60
        hours, mins = int(hours), int(mins)
        first = f"**|**   :first_place: **`| {name.ljust(18)} |  "+ f"{hours}:{mins}".rjust(6)+"|`**\n"

        name = toppers[1][view]
        if len(name) > 18:
            name = name[:15] + "..."
        seconds = toppers[1]['time']
        mins = seconds//60
        hours = seconds//3600
        mins = mins%60
        hours, mins = int(hours), int(mins)
        second = f"**|**   :second_place: **`| {name.ljust(18)} |  "+ f"{hours}:{mins}".rjust(6)+"|`**\n"

        name = toppers[2][view]
        if len(name) > 18:
            name = name[:15] + "..."
        seconds = toppers[2]['time']
        mins = seconds//60
        hours = seconds//3600
        mins = mins%60
        hours, mins = int(hours), int(mins)
        third = f"**|**   :third_place: **`| {name.ljust(18)} |  "+ f"{hours}:{mins}".rjust(6)+"|`**\n"

        seperator = "**`-----------------------------------`**\n"
        top4plus = ''
        for idx in range(3,length):
            name = toppers[idx][view]
            if len(name) > 18:
                name = name[:15] + "..."
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