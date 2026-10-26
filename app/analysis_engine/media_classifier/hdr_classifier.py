from .rules.rule_registry import RuleRegistry
from .rules.rule_engine import RuleEngine


_hdr_engine = RuleEngine(
    RuleRegistry.get("hdr"),
    classifier="hdr",
)

_dv_engine = RuleEngine(
    RuleRegistry.get("dolby_vision"),
    classifier="dolby_vision",
)


def classify_hdr(name: str) -> tuple[bool, bool]:
    hdr = _hdr_engine.evaluate(name) is not None
    dv = _dv_engine.evaluate(name) is not None

    return hdr, dv