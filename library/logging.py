from functools import wraps
from typing import Literal
from .templates import timenow

class Logger:
    def __init__(self, filename: str, style: Literal["default", "path", "tree", "tml"]):
        self.filename = filename.title()
        self.style = style
    
    def command(self):
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                inter = args[1]
                guild_id = inter.guild.id if inter.guild else "DM"
                gname = inter.guild.name
                channel_id = inter.channel_id if inter.guild else "DM"
                cname = inter.channel.name
                user_id = inter.user.id
                uname = inter.user.display_name
                operation = func.__name__.title()
                if self.style == 'tml':
                    print(
                        f"|──> At {timenow()}",
                        f"|    └─> Action {operation} [{self.filename}]",
                        f"|    └─> By {uname} [{user_id}]",
                        f"|    └─> In {cname} [{channel_id}]",
                        f"|    └─> On {gname} [{guild_id}]\n|",
                        sep='\n'
                    )
                elif self.style == 'path':
                    print(f"[ {timenow()} ] : /{guild_id}/{user_id}/{self.filename}/{operation}")
                elif self.style == 'tree':
                    print(
                        f"{self.filename.capitalize()}/{operation}",
                        f"└── Time: {timenow()}",
                        f"└── Guild: {guild_id}",
                        f"└── Channel: {channel_id}",
                        f"└── User: {user_id}",
                        sep="\n"
                    )
                else:
                    print(timenow()+f"File[{self.filename}] Command[{operation}] in Guild[{guild_id}] at Channel[{channel_id}] by User[{user_id}]")

                return await func(*args, **kwargs)
            return wrapper
        return decorator
