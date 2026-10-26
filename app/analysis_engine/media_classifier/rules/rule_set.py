from .rule import Rule


class RuleSet:
    """
    Container for ordered classification rules.
    """

    def __init__(self, rules: list[Rule]):
        # Higher priority first
        self.rules = sorted(rules, key=lambda r: r.priority, reverse=True)

    def get_rules(self) -> list[Rule]:
        return self.rules