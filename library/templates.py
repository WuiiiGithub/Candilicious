from datetime import datetime

def leaderboard_template(toppers: list) -> str:
    length = len(toppers)
    if len<3:
        return "Sorry, very less people to rank"
    else:
        header = """**`===================================`**
**`| X  |        Name        | Score |`**
**`-----------------------------------`**
"""
        first = f"**|**   :first_place: **`| {toppers[0]['name'].ljust(18)} |  "+ f"{toppers[0]['time']:.2f}".rjust(6)+" |`**\n"
        second = f"**|**   :second_place: **`| {toppers[1]['name'].ljust(18)} |  "+ f"{toppers[1]['time']:.2f}".rjust(6)+" |`**\n"
        third = f"**|**   :third_place: **`| {toppers[2]['name'].ljust(18)} |  "+ f"{toppers[2]['time']:.2f}".rjust(6)+" |`**\n"

        seperator = "**`-----------------------------------`**\n"

        for idx, toppers in range(3,length):
            top4plus += f"**`| {str(idx+1).ljust(2)} | {toppers[idx]['name'].ljust(18)} |  "+ f"{toppers[idx]['time']:.2f}".rjust(6)+" |`**\n"

        footer = "**`===================================`**\n"

        return header+first+second+third+seperator+top4plus+footer

def timenow():
    return datetime.now().strftime("[ %d %b %Y | %H:%M:%S ] ")