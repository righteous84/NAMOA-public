from .rules.rule_registry import RuleRegistry
from .rules.rule_engine import RuleEngine


_engine = RuleEngine(
    RuleRegistry.get("release"),
    classifier="release",
)


def classify_release_type(name: str) -> str:
    return _engine.evaluate(name) or "ENCODE"