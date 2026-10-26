from .rules.rule_registry import RuleRegistry
from .rules.rule_engine import RuleEngine


_engine = RuleEngine(
    RuleRegistry.get("video_codec"),
    classifier="video_codec",
)


def classify_video_codec(name: str) -> str | None:
    return _engine.evaluate(name)