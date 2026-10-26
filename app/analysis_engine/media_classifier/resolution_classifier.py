from .rules.rule_registry import RuleRegistry
from .rules.rule_engine import RuleEngine


_engine = RuleEngine(
    RuleRegistry.get("resolution"),
    classifier="resolution",
)


def classify_resolution(name: str) -> str | None:
    return _engine.evaluate(name)