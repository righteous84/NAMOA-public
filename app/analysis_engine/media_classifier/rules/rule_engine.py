from typing import Optional

from app.models.classification_evidence import ClassificationEvidence

from .rule_set import RuleSet


class RuleEngine:
    """
    Evaluates rules against input text.

    evaluate_evidence() produces structured classification evidence.

    All matching rules are preserved.

    The Knowledge Layer should not discard evidence.
    Interpretation happens later in the Expert Layer.
    """

    def __init__(
        self,
        rule_set: RuleSet,
        classifier: str | None = None,
    ):
        self.rule_set = rule_set
        self.classifier = classifier


    def evaluate_evidence(
        self,
        text: str
    ) -> list[ClassificationEvidence]:

        evidence_items = []


        for rule in self.rule_set.get_rules():

            if rule.matches(text):

                evidence_items.append(
                    ClassificationEvidence(
                        domain=self.classifier or "unknown",
                        value=rule.value,
                        confidence=rule.confidence,
                        source="filename",
                        evidence_id=rule.name,
                        matched_text=rule.pattern,
                    )
                )


        return evidence_items


    def evaluate(
        self,
        text: str
    ) -> Optional[str]:

        evidence = self.evaluate_evidence(text)

        if not evidence:
            return None

        # Preserve existing behaviour:
        # highest priority rule is first
        return evidence[0].value