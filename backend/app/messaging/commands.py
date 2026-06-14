from dataclasses import dataclass


@dataclass(frozen=True)
class MessagingCommand:
    name: str
    args: str = ""
    raw_name: str = ""


COMMAND_HELP = """Settra commands:
/new - start a fresh chat
/clear - clear the current chat
/delete - delete the current chat
/help - show this message"""

_ALIASES = {
    "start": "help",
    "help": "help",
    "new": "new",
    "reset": "new",
    "clear": "clear",
    "delete": "delete",
    "del": "delete",
}


def parse_messaging_command(text: str) -> MessagingCommand | None:
    stripped = text.strip()

    if not stripped.startswith("/"):
        return None

    token, _, args = stripped.partition(" ")
    raw_name = token[1:].split("@", 1)[0].strip().lower()

    if not raw_name:
        return None

    return MessagingCommand(
        name=_ALIASES.get(raw_name, "unknown"),
        args=args.strip(),
        raw_name=raw_name,
    )
