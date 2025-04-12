from functools import wraps
from typing import Literal
from .templates import timenow

class Logger:
    def __init__(self, filename: str, style: Literal["default", "path", ]):
        self.filename = filename
        self.styles = style
    
    def command(self):
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                inter = args[1]
                guild_id = inter.guild.id if inter.guild else "DM"
                user_id = inter.user.id
                operation = func.__name__
                print("-"*20)
                print(timenow()+f"File[{self.filename}] Command[{operation}] in Guild[{guild_id}] by User[{user_id}]")
                return await func(*args, **kwargs)
            return wrapper
        return decorator
