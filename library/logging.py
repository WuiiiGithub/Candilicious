from typing import Literal, Union
from .templates import timenow

_ANSI_COLORS = {
    # Success (Final/High)
    100: "\x1b[32m",       # Green
    # Success (Step)
    75: "\x1b[36m",        # Cyan
    # Success (Sub-Call)
    50: "\x1b[38;5;39m",   # Light Blue
    # Information (Neutral/Waiting)
    0: "\x1b[0m",          # Default/White
    # Minor Issue (Warning/Missing)
    -25: "\x1b[33m",       # Yellow
    # Service/Resource Unavailable
    -50: "\x1b[38;5;208m",  # Orange
    # Step Failure
    -75: "\x1b[31m",       # Red
    # Critical Failure (Fatal)
    -100: "\x1b[1;31m"     # Bright Red
}

def _get_ansi_color(status_code: int) -> str:
    return _ANSI_COLORS.get(status_code, "\x1b[0m")


class CogLogger:
    def __init__(self, filename: str):
        self.name = filename.replace('_', ' ').title()

    def _format_log_block(self, header_type: str, header_name: str, status_code: int, details: str = None) -> str:
        time = timenow()
        color_code = _get_ansi_color(status_code)
        reset_code = "\x1b[0m"

        lines = [
            f"|──> {color_code}{header_type.title()} {header_name.title()}{reset_code} [{self.name}]",
            f"|    └─> At {time}",
        ]
        
        if details:
            lines.append(f"|    └─> Details:")
            for line_detail in details.splitlines():
                lines.append(f"|        └─ {line_detail}")

        return '\n'.join(lines) + '\n|'

    def log_cog(
        self, 
        action: Literal["loaded", "unloaded", "error", "syncing", "starting", "stopping"], 
        status_code: int, 
        details: str = None
    ):
        log_block = self._format_log_block(
            "Cog Event", 
            f"{self.name} {action}", 
            status_code, 
            details
        )
        print(log_block)

    def log_important(self, event_name: str, status_code: int, details: str = None):
        log_block = self._format_log_block(
            "Important Event", event_name, status_code, details
        )
        print(log_block)

class CommandLogger:
    def __init__(self, filename: str, inter):
        self.filename = filename.replace('_', ' ').title()
        self.command_start_time = timenow()
        self.inter_details = {
            "guild_id": inter.guild.id if inter.guild else "DM",
            "gname": inter.guild.name if inter.guild else "DM",
            "channel_id": inter.channel.id if inter.channel else "DM",
            "cname": inter.channel.name if inter.channel else "DM",
            "user_id": inter.user.id,
            "uname": inter.user.display_name,
            "operation": inter.command.name.replace('_', ' ').title() if inter.command else "Unknown Command"
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
        color_code = _get_ansi_color(0) # Default Info color for header
        reset_code = "\x1b[0m"
        
        command_header_lines = [
            f"|──> {color_code}Command {self.inter_details['operation']}{reset_code} [{self.filename}]",
            f"|    └─> At {self.command_start_time}",
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

            step_color = _get_ansi_color(status_code)

            # Concatenate message and details if details exist
            full_message = f"[{message}] "
            if details:
                full_message += f" {details}" 

            command_header_lines.append(f"|        └─ {step_color}{full_message}{reset_code}")
        
        print('\n'.join(command_header_lines))
        print("|\n")
        self.flush()

    def flush(self):
        self._logs = []

class TaskLogger:
    def __init__(self, filename: str, task_name: str):
        self.filename = filename.replace('_', ' ').title()
        self.task_name = task_name.replace('_', ' ').title()
        self.start_time = timenow()
        self._logs = []

    def _add_step(self, status_code: int, message: str, details: str = None):
        self._logs.append({
            'time': timenow(),
            'status_code': status_code,
            'message': message,
            'details': details
        })

    def before(self, status_code: int, message: str, details: str = None):
        self._add_step(status_code, f"Before: {message}", details)

    def during(self, status_code: int, message: str, details: str = None):
        self._add_step(status_code, f"During: {message}", details)

    def after(self, status_code: int, message: str, details: str = None):
        self._add_step(status_code, f"After: {message}", details)

    def step(self, status_code: int, message: str, details: str = None):
        self._add_step(status_code, message, details)

    def process(self, status_code: int, message: str, details: str = None):
        self._add_step(status_code, message, details)

    def process(self, status_code: int, message: str, details: str = None):
        self._add_step(status_code, message, details)

    def send(self):
        color_code = _get_ansi_color(0)
        reset_code = "\x1b[0m"

        header_lines = [
            f"|──> {color_code}Task {self.task_name}{reset_code} [{self.filename}]",
            f"|    └─> At {self.start_time}",
            f"|    └─> Details:"
        ]

        for step in self._logs:
            step_color = _get_ansi_color(step['status_code'])
            full_message = f"[{step['message']}]"
            if step['details']:
                full_message += f" {step['details']}"
            header_lines.append(f"|        └─ {step_color}{full_message}{reset_code}")

        print('\n'.join(header_lines))
        print("|\n")
        self._logs = []


class ListenerLogger:
    def __init__(self, filename: str, event_name: str):
        self.filename = filename.replace('_', ' ').title()
        self.event_name = event_name.replace('_', ' ').title()
        self.start_time = timenow()
        self._logs = []

    def _add_step(self, status_code: int, message: str, details: str = None):
        self._logs.append({
            'time': timenow(),
            'status_code': status_code,
            'message': message,
            'details': details
        })

    def process(self, status_code: int, message: str, details: str = None):
        self._add_step(status_code, message, details)

    def error(self, status_code: int, message: str, details: str = None):
        self._add_step(status_code, f"Error: {message}", details)

    def complete(self, status_code: int, message: str, details: str = None):
        self._add_step(status_code, f"Complete: {message}", details)

    def send(self):
        color_code = _get_ansi_color(0)
        reset_code = "\x1b[0m"

        header_lines = [
            f"|──> {color_code}Listener {self.event_name}{reset_code} [{self.filename}]",
            f"|    └─> At {self.start_time}",
            f"|    └─> Details:"
        ]

        for step in self._logs:
            step_color = _get_ansi_color(step['status_code'])
            full_message = f"[{step['message']}]"
            if step['details']:
                full_message += f" {step['details']}"
            header_lines.append(f"|        └─ {step_color}{full_message}{reset_code}")

        print('\n'.join(header_lines))
        print("|\n")
        self._logs = []


class SystemLogger:
    def __init__(self, filename: str):
        self.filename = filename.replace('_', ' ').title()
        self.start_time = timenow()
        self._logs = []

    def _add_step(self, status_code: int, message: str, details: str = None):
        self._logs.append({
            'time': timenow(),
            'status_code': status_code,
            'message': message,
            'details': details
        })

    def loading(self, status_code: int, message: str, details: str = None):
        self._add_step(status_code, f"Loading: {message}", details)

    def connection(self, status_code: int, message: str, details: str = None):
        self._add_step(status_code, f"Connection: {message}", details)

    def process(self, status_code: int, message: str, details: str = None):
        self._add_step(status_code, message, details)

    def error(self, status_code: int, message: str, details: str = None):
        self._add_step(status_code, f"Error: {message}", details)

    def complete(self, status_code: int, message: str, details: str = None):
        self._add_step(status_code, f"Complete: {message}", details)

    def send(self, header_name: str = "System Event"):
        color_code = _get_ansi_color(0)
        reset_code = "\x1b[0m"

        header_lines = [
            f"|──> {color_code}{header_name.title()}{reset_code} [{self.filename}]",
            f"|    └─> At {self.start_time}",
            f"|    └─> Details:"
        ]

        for step in self._logs:
            step_color = _get_ansi_color(step['status_code'])
            full_message = f"[{step['message']}]"
            if step['details']:
                full_message += f" {step['details']}"
            header_lines.append(f"|        └─ {step_color}{full_message}{reset_code}")

        print('\n'.join(header_lines))
        print("|\n")
        self._logs = []