"""Cumulative word budgets; delivery delays never produce catch-up bursts."""

import re
from dataclasses import dataclass, field


def question_text(question):
    text = question.text
    if question.choices:
        text += "\n\n" + "\n".join(f"{key}) {value}" for key, value in question.choices.items())
    return text


@dataclass
class Reading:
    text: str
    wpm: int
    position: int = 0
    credit: float = 0
    units: list[tuple[int, int]] = field(init=False)

    def __post_init__(self):
        self.units = []
        depth = words = 0
        for match in re.finditer(r"\S+\s*", self.text):
            words += 1
            # Keep balanced parenthesized expressions (including fractions) together.
            depth = max(0, depth + match.group().count("(") - match.group().count(")"))
            if depth == 0:
                self.units.append((match.end(), words))
                words = 0
        if words:
            self.units.append((len(self.text), words))

    @property
    def done(self):
        return self.position == len(self.units)

    @property
    def visible(self):
        return self.text[: self.units[self.position - 1][0]] if self.position else ""

    def step(self):
        self.credit += self.wpm / 60
        while not self.done and self.units[self.position][1] <= self.credit + 1e-9:
            self.credit -= self.units[self.position][1]
            self.position += 1

    def finish(self):
        self.position = len(self.units)
