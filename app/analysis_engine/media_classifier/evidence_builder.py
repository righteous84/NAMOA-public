from app.models.evidence_collection import EvidenceCollection

from .rules.rule_registry import RuleRegistry
from .rules.rule_engine import RuleEngine


class ClassificationEvidenceBuilder:
    """
    Converts filename information into structured evidence.

    This is the bridge between:

    Knowledge Layer:
        Rules

    and:

    Interpretation Layer:
        Experts

    All matching evidence is preserved.
    """

    DOMAINS = [
        "source",
        "release",
        "resolution",
        "video_codec",
        "audio",
        "hdr",
        "dolby_vision",
    ]


    def build(
        self,
        filename: str
    ) -> EvidenceCollection:

        collection = EvidenceCollection()

        filename = filename.lower()


        for domain in self.DOMAINS:

            rule_set = RuleRegistry.get(domain)

            engine = RuleEngine(
                rule_set,
                classifier=domain
            )

            evidences = engine.evaluate_evidence(
                filename
            )


            for evidence in evidences:
                collection.add(evidence)


        return collection