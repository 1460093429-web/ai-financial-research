from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Company:
    name: str
    segment: str
    symbol: str
    aliases: List[str]
    notes: str = ""