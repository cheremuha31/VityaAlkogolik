from dataclasses import dataclass
import random


@dataclass(frozen=True)
class Outcome:
    name: str
    weight: int
    power_min: int
    power_max: int
    messages: tuple[str, ...]

    def roll_power(self) -> int:
        return random.randint(self.power_min, self.power_max)

    def message(self) -> str:
        return random.choice(self.messages)


@dataclass(frozen=True)
class EventSpec:
    event_type: str
    title: str
    description: str
    button_text: str
    power_multiplier: float = 1.0
    cooldown_multiplier: float = 1.0