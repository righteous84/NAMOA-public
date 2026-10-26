from .rule_definitions import RULE_DEFINITIONS
from .rule_set import RuleSet


class RuleRegistry:
    """
    Central registry for all classification rules.

    This is the SINGLE source of truth for rule access.
    """

    _cache: dict[str, RuleSet] = RULE_DEFINITIONS.copy()

    @classmethod
    def get(cls, domain: str) -> RuleSet:
        rules = cls._cache.get(domain)
        if rules is None:
            raise ValueError(f"No rule set registered for domain: {domain}")
        return rules

    @classmethod
    def register(cls, domain: str, rule_set: RuleSet) -> None:
        cls._cache[domain] = rule_set

    @classmethod
    def all_domains(cls) -> list[str]:
        return list(cls._cache.keys())