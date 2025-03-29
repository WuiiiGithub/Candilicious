def leaderboard_template(toppers: list) -> str:
    return f"""**`===================================`**
**`| X  |        Name        | Score |`**
**`-----------------------------------`**
**|**   :first_place: **`| {toppers[0]['name'].ljust(18)} |  {toppers[0]['time'].rjust(6)} |`**
**|**   :second_place: **`| {toppers[1]['name'].ljust(18)} |  {toppers[1]['time'].rjust(6)} |`**
**|**   :third_place: **`| {toppers[2]['name'].ljust(18)} |  {toppers[2]['time'].rjust(6)} |`**
**`-----------------------------------`**
**`| 4  | {toppers[3]['name'].ljust(18)} |  {toppers[3]['time'].rjust(6)} |`**
**`| 5  | {toppers[4]['name'].ljust(18)} |  {toppers[4]['time'].rjust(6)} |`**
**`| 6  | {toppers[5]['name'].ljust(18)} |  {toppers[5]['time'].rjust(6)} |`**
**`| 7  | {toppers[6]['name'].ljust(18)} |  {toppers[6]['time'].rjust(6)} |`**
**`| 8  | {toppers[7]['name'].ljust(18)} |  {toppers[7]['time'].rjust(6)} |`**
**`| 9  | {toppers[8]['name'].ljust(18)} |  {toppers[8]['time'].rjust(6)} |`**
**`| 10 | {toppers[9]['name'].ljust(18)} |  {toppers[9]['time'].rjust(6)} |`**
**`===================================`**"""