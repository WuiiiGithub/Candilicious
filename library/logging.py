from typing import Literal
from .templates import timenow

_ANSI_COLORS = {
    # Success
    100: "\x1b[32m",   
    # Step Success
    75: "\x1b[33m",    
    # Call Success
    50: "\x1b[90m",     
    # Step Fail
    -75: "\x1b[38;5;208m", 
    # Info
    0: "\x1b[38;5;196m", 
    # Service Unavailable
    -50: "\x1b[36m",    
    # Resource Unavailable
    -25: "\x1b[41m\x1b[97m",
    # Failure
    -100: "\x1b[31m"   
}

def _get_ansi_color(status_code: int) -> str:
    return _ANSI_COLORS.get(status_code, "\x1b[0m")


class CogLogger:
    def __init__(self, filename: str):
        self.filename = filename.title()

    def _format_log_block(self, header_type: str, header_name: str, status_code: int, details: str = None) -> str:
        time = timenow()
        color_code = _get_ansi_color(status_code)
        reset_code = "\x1b[0m"

        lines = [
            f"|──> At {time}",
            f"|    └─> {color_code}{header_type.title()}: {header_name.title()}{reset_code}",
        ]
        
        if details:
            lines.append(f"|    └─> Details:")
            for line_detail in details.splitlines():
                lines.append(f"|        └─ {line_detail}")

        return '\n'.join(lines) + '\n|'

    def log_cog(self, cog_name: str, action: Literal["loaded", "unloaded", "error"], status_code: int, details: str = None):
        log_block = self._format_log_block(
            "Cog Event", f"{cog_name} {action}", status_code, details
        )
        print(log_block)

    def log_important(self, event_name: str, status_code: int, details: str = None):
        log_block = self._format_log_block(
            "Important Event", event_name, status_code, details
        )
        print(log_block)

class CommandLogger:
    def __init__(self, filename: str, inter):
        self.filename = filename.title()
        self.command_start_time = timenow()
        self.inter_details = {
            "guild_id": inter.guild.id if inter.guild else "DM",
            "gname": inter.guild.name if inter.guild else "DM",
            "channel_id": inter.channel.id if inter.channel else "DM",
            "cname": inter.channel.name if inter.channel else "DM",
            "user_id": inter.user.id,
            "uname": inter.user.display_name,
            "operation": inter.command.name.title() if inter.command else "Unknown Command"
        }
        self._logs = []

    def _add_step(self, status_code: int, message: str, details: str = None):
        self._logs.append({
            'time': timenow(),
            'status_code': status_code,
            'message': message,
            'details': details
        })

    def loading(self, status_code: int, message: str, details: str = None):
        self._add_step(status_code, message, details)

    def connection(self, status_code: int, message: str, details: str = None):
        self._add_step(status_code, message, details)

    def process(self, status_code: int, name: str, details: str = None):
        self._add_step(status_code, name, details)
    
    def command_step(self, status_code: int, message: str, details: str = None):
        self._add_step(status_code, message, details)

    def subroutine(self, status_code: int, message: str, details: str = None):
        self._add_step(status_code, message, details)

    def send(self):
        command_header_lines = [
            f"|──> At {self.command_start_time}",
            f"|    └─> Action {self.inter_details['operation']} [{self.filename}]",
            f"|    └─> By {self.inter_details['uname']} [{self.inter_details['user_id']}]",
            f"|    └─> In {self.inter_details['cname']} [{self.inter_details['channel_id']}]",
            f"|    └─> On {self.inter_details['gname']} [{self.inter_details['guild_id']}]"
        ]
        
        command_header_lines.append(f"|    └─> Details:")
        for step in self._logs:
            time = step['time']
            status_code = step['status_code']
            message = step['message']
            details = step['details']

            color_code = _get_ansi_color(status_code)
            reset_code = "\x1b[0m"

            # Concatenate message and details if details exist
            full_message = f"[{message}] "
            if details:
                full_message += f" {details}" 

            command_header_lines.append(f"|        └─ {color_code}{full_message}{reset_code}")
        
        print('\n'.join(command_header_lines))
        print("|\n")
        self.flush()

    def flush(self):
        self._logs = []