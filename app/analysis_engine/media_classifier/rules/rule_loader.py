from .rule_registry import RuleRegistry
from .rule_set import RuleSet


class RuleLoader:
    """
    Placeholder for future external rule loading (JSON/YAML/DB).
    """

    @staticmethod
    def load_into_registry() -> None:
        # Future:
        # - load JSON files
        # - validate schema
        # - register into RuleRegistry
        pass