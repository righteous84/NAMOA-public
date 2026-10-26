from .rules.rule_registry import RuleRegistry
from .rules.rule_engine import RuleEngine


_engine = RuleEngine(
    RuleRegistry.get("audio"),
    classifier="audio",
)


def classify_audio(name: str) -> str | None:
    return _engine.evaluate(name)