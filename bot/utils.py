import random

from .data import EVENT_SPECS, OUTCOMES
from .models import EventSpec, Outcome


def get_user_display(username: str | None, first_name: str | None, user_id: int) -> str:
    if username:
        return f"@{username}"
    if first_name:
        return first_name
    return f"User {user_id}"


def format_cooldown(seconds_left: int) -> str:
    hours = seconds_left // 3600
    minutes = (seconds_left % 3600) // 60
    return f"{hours}ч {minutes}м"


def roll_outcome() -> tuple[Outcome, int]:
    outcome = random.choices(OUTCOMES, weights=[o.weight for o in OUTCOMES], k=1)[0]
    power = outcome.roll_power()
    return outcome, power


def get_event_spec(event_type: str) -> EventSpec:
    for spec in EVENT_SPECS:
        if spec.event_type == event_type:
            return spec
    return EVENT_SPECS[0]


def select_random_event() -> EventSpec:
    return random.choice(EVENT_SPECS)


def extract_command(text: str) -> str | None:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    command = stripped[1:].split(maxsplit=1)[0]
    if "@" in command:
        command = command.split("@", 1)[0]
    return command.lower()
