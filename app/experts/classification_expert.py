"""
Classification Expert.

Interprets collected classification evidence.

Responsibilities:

- Group evidence by domain
- Apply configurable evidence trust
- Detect agreement
- Detect conflicts
- Measure source diversity
- Produce explainable reasoning
- Calculate confidence

The Expert never performs classification.
It only interprets evidence.
"""

from collections import defaultdict

from app.experts.base_expert import BaseExpert
from app.models.expert_result import ExpertResult
from app.models.expert_reasoning import (
    AgreementState,
    AlternativeInterpretation,
    DomainAnalysis,
    EvidenceReference,
    EvidenceRole,
    ExpertData,
)
from app.models.analysis_context import AnalysisContext
from app.services.evidence_weight_service import (
    EvidenceWeightService,
)


class ClassificationExpert(BaseExpert):

    name = "classification_expert"
    domain = "classification"

    # 1.1.0: evidence-weighting configuration semantics corrected.
    # Only active evidence sources carry weights (filename today);
    # placeholder sources are reserved, and the unknown-source default
    # became an explicit, snapshotted policy value. The weighting
    # algorithm itself is unchanged.
    semantic_version = "1.1.0"


    def __init__(self):

        self.weight_service = EvidenceWeightService()


    def analyze(
        self,
        context: AnalysisContext,
    ) -> ExpertResult:

        observations = {}
        confidence_values = []
        reasoning = []

        expert_data = ExpertData()


        # ---------------------------------
        # Evidence availability guard
        #
        # ClassificationExpert requires
        # EvidenceCollection. If unavailable,
        # return a valid empty result rather
        # than failing the entire expert.
        # ---------------------------------

        if not context.evidence.all():
            return ExpertResult(
                expert_name=self.name,
                observations={},
                confidence=0.0,
                notes="No classification evidence available",
                expert_data=ExpertData(),
            )


        domains = defaultdict(list)

        for evidence in context.evidence.all():
            domains[evidence.domain].append(evidence)


        for domain, evidences in domains.items():

            result = self._interpret_domain(
                domain,
                evidences
            )

                        # ---------------------------------
            # Preserve the structured reasoning
            # for this domain.
            #
            # This complements the human-readable
            # notes without replacing them.
            #
            # Future FusionEngine iterations can
            # consume this directly instead of
            # attempting to parse text.
            # ---------------------------------

            expert_data.domains[domain] = result["analysis"]

            observations[domain] = result["value"]

            confidence_values.append(
                result["confidence"]
            )

            reasoning.append(
                result["reasoning"]
            )


        confidence = (
            sum(confidence_values)
            /
            len(confidence_values)
            if confidence_values
            else 0.0
        )

        return ExpertResult(
            expert_name=self.name,
            observations=observations,
            confidence=confidence,
            notes="\n\n".join(reasoning),
            expert_data=expert_data,
        )


    def _weighted_confidence(
        self,
        evidence
    ):

        weight = self.weight_service.get_source_weight(
            evidence.source
        )

        return evidence.confidence * weight


    def _interpret_domain(
        self,
        domain,
        evidences
    ):

        grouped = defaultdict(list)


        for evidence in evidences:
            grouped[evidence.value].append(evidence)


        ranked = sorted(
            grouped.items(),
            key=lambda item: sum(
                self._weighted_confidence(e)
                for e in item[1]
            ),
            reverse=True,
        )


        selected_value, selected_evidence = ranked[0]

        # ---------------------------------
        # Structured expert interpretation.
        #
        # Every expert produces human-readable
        # reasoning for logs and UI, but also
        # preserves the same reasoning in a
        # structured form for downstream
        # pipeline stages.
        #
        # The structure of this payload is
        # owned entirely by this expert.
        # ---------------------------------

        analysis = {
            "selected_value": selected_value,
            "confidence": 0.0,
            "agreement": "single",
            "has_conflict": False,
            "selected_evidence": [],
            "rejected_evidence": [],
            "alternatives": {},
            "uncertainty": 0.0,
        }

        weighted_scores = [
            self._weighted_confidence(e)
            for e in selected_evidence
        ]

        # ---------------------------------
        # Confidence begins with the
        # strongest supporting evidence.
        #
        # Additional agreement and conflicts
        # adjust this baseline below.
        # ---------------------------------

        confidence = max(weighted_scores)

        unique_sources = {
            e.source
            for e in selected_evidence
        }

        # ---------------------------------
        # Preserve the evidence supporting
        # the selected interpretation.
        #
        # Unlike notes, this information is
        # intended to be consumed directly by
        # FusionEngine and other experts.
        # ---------------------------------

        for evidence in selected_evidence:

            analysis["selected_evidence"].append({
                "source": evidence.source,
                "confidence": evidence.confidence,
                "weighted_confidence": (
                    self._weighted_confidence(evidence)
                ),
                "evidence_id": evidence.evidence_id,
                "matched_text": evidence.matched_text,
            })

        lines = [
            f"{domain}: {selected_value}",
            "",
            "Supporting evidence:"
        ]


        for evidence in selected_evidence:

            weighted = self._weighted_confidence(
                evidence
            )

            detail = (
                f"- {evidence.source}"
            )

            if evidence.evidence_id:
                detail += (
                    f" [{evidence.evidence_id}]"
                )

            if evidence.matched_text:
                detail += (
                    f" matched '{evidence.matched_text}'"
                )

            detail += (
                f" raw={evidence.confidence:.2f}"
                f" weighted={weighted:.2f}"
            )

            lines.append(detail)


        # ---------------------------------
        # Agreement bonus
        # ---------------------------------

        if len(selected_evidence) > 1:

            if len(unique_sources) > 1:

                analysis["agreement"] = (
                "independent"
                )

                confidence += 0.05

                lines.append("")
                lines.append(
                    "Independent source agreement detected."
                )

            else:
                analysis["agreement"] = (
                    "same_source"
                )
                confidence += 0.02

                lines.append("")
                lines.append(
                    "Multiple rules agree from same source."
                )

        else:

            lines.append("")
            lines.append(
                "Single supporting evidence item."
            )


        # ---------------------------------
        # Conflict penalty
        # ---------------------------------

        if len(grouped) > 1:

            analysis["has_conflict"] = True

            confidence -= 0.10

            lines.append("")
            lines.append(
                "Conflict detected."
            )

            lines.append("")
            lines.append(
                "Rejected evidence:"
            )

            for value, evidence_list in grouped.items():

                if value == selected_value:
                    continue

                analysis["alternatives"][value] = []

                for evidence in evidence_list:

                    analysis["rejected_evidence"].append({
                        "value": value,
                        "source": evidence.source,
                        "confidence": evidence.confidence,
                        "weighted_confidence": (
                            self._weighted_confidence(
                                evidence
                            )
                        ),
                        "evidence_id": evidence.evidence_id,
                        "matched_text": evidence.matched_text,
                    })

                    analysis["alternatives"][value].append({
                        "source": evidence.source,
                        "confidence": evidence.confidence,
                    })

                    detail = f"- {value}"

                    detail += (
                        f" via {evidence.source}"
                    )

                    if evidence.evidence_id:
                        detail += (
                            f" [{evidence.evidence_id}]"
                        )

                    if evidence.matched_text:
                        detail += (
                            f" matched '{evidence.matched_text}'"
                        )

                    lines.append(detail)

            lines.append("")
            lines.append(
                "Confidence reduced due to conflicting evidence."
            )


        confidence = max(
            0.0,
            min(confidence, 1.0)
        )

        # ---------------------------------
        # Finalise the structured analysis.
        #
        # Human-readable notes remain the
        # primary explanation, while this
        # payload preserves the reasoning
        # for later machine interpretation.
        # ---------------------------------

        analysis["confidence"] = confidence

        analysis["uncertainty"] = round(
            1.0 - confidence,
            3,
        )

        lines.append("")
        lines.append(
            f"Unique sources: {len(unique_sources)}"
        )

        lines.append(
            f"Final confidence: {confidence:.2f}"
        )

        return {
            "value": selected_value,
            "confidence": confidence,
            "reasoning": "\n".join(lines),
            "analysis": DomainAnalysis(
                selected_value=analysis["selected_value"],
                confidence=analysis["confidence"],
                agreement=AgreementState(
                    analysis["agreement"]
                ),
                has_conflict=analysis["has_conflict"],
                uncertainty=analysis["uncertainty"],
                selected_references=tuple(
                    EvidenceReference(
                        source=item["source"],
                        raw_confidence=item["confidence"],
                        weighted_confidence=item["weighted_confidence"],
                        role=EvidenceRole.PRIMARY,
                        evidence_id=item["evidence_id"],
                        matched_text=item["matched_text"],
                    )
                    for item in analysis["selected_evidence"]
                ),
                rejected_references=tuple(
                    EvidenceReference(
                        source=item["source"],
                        raw_confidence=item["confidence"],
                        weighted_confidence=item["weighted_confidence"],
                        role=EvidenceRole.REJECTED,
                        evidence_id=item["evidence_id"],
                        matched_text=item["matched_text"],
                    )
                    for item in analysis["rejected_evidence"]
                ),
                alternatives=tuple(
                    AlternativeInterpretation(
                        value=value,
                        confidence=max(
                            evidence["confidence"]
                            for evidence in evidence_list
                        ),
                        support_count=len(evidence_list),
                    )
                    for value, evidence_list
                    in analysis["alternatives"].items()
                ),
            ),
        }