from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Rule:
    """
    Represents a single classification rule.
    """
    name: str
    pattern: str
    value: str
    priority: int = 100
    confidence: float = 1.0 

    def matches(self, text: str) -> bool:
        """
        Token-boundary substring match.

        The pattern matches only when it appears delimited by
        non-alphanumeric characters (or the start/end of the filename),
        so a short pattern such as "ts" cannot match inside a larger
        token such as "dts", "yts" or "kitsune", while a standalone "ts"
        token (for example a ".ts" extension or a "TS" source token)
        still matches. All occurrences are considered.
        """

        start = 0

        while True:

            index = text.find(
                self.pattern,
                start,
            )

            if index == -1:
                return False

            before = (
                text[index - 1]
                if index > 0
                else ""
            )

            after_index = index + len(self.pattern)

            after = (
                text[after_index]
                if after_index < len(text)
                else ""
            )

            if (
                not before.isalnum()
                and not after.isalnum()
            ):
                return True

            start = index + 1