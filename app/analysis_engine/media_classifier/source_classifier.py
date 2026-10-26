from .rules.rule_registry import RuleRegistry
from .rules.rule_engine import RuleEngine


_engine = RuleEngine(
    RuleRegistry.get("source"),
    classifier="source",
)


def classify_source(name: str) -> str | None:
    return _engine.evaluate(name)