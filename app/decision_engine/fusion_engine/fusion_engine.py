from typing import List, Optional

from app.decision_engine.signals.decision_signal import DecisionSignal
from app.decision_engine.fusion_engine.recommendation_decision_weights import RULE_WEIGHTS
from app.models.opportunity_assessment import OpportunityAssessment
from app.models.user_policy import UserPolicy, OPPORTUNITY_LEVEL_LABELS


# Signal-direction policy.
#
#   opportunity directions (optimize, remux)
#       Signals that assert optimisation value. These and ONLY these
#       contribute to the fused opportunity score, confidence and
#       savings estimate.
#
#   constraint directions (preserve)
#       Signals that describe preservation requirements or reasons NOT
#       to optimise. They never dilute opportunity magnitude merely by
#       existing. A preserve signal whose `proposition` matches an
#       opportunity signal's proposition SUPPRESSES that opportunity
#       and explains why (Fusion reconciliation, not rule-to-rule
#       communication). Other preserve signals are carried verbatim as
#       constraints.
#
# An unrecognised direction fails clearly instead of silently joining
# either channel.

OPPORTUNITY_DIRECTIONS = frozenset({"optimize", "remux"})

CONSTRAINT_DIRECTIONS = frozenset({"preserve"})


class FusionEngine:
    """
    Combines DecisionSignals into an OpportunityAssessment.

    Responsibilities:
        DecisionSignal[]
              |
              v
        channel separation (opportunity vs preserve)
              |
              v
        reconciliation (suppression by proposition)
              |
              v
        value/confidence combination
              |
              v
        opportunity-level classification
              |
              v
        OpportunityAssessment (+ preservation conclusion)

    Fusion is intentionally stateless.

    It does not:
        - store previous assessments
        - mutate AnalysisContext
        - create Recommendations
        - maintain runtime state

    Semantic distinction (core):
        opportunity_score  = VALUE of the proposition
        confidence         = CERTAINTY of the intelligence

    These are combined independently: a low-confidence valuable
    proposition keeps its value while carrying low certainty.
    """

    # Semantic version of the Fusion aggregation behaviour and policy.
    # 3.0.0: reconciliation semantics. Fusion now suppresses
    # propositions contradicted by an explicit preservation signal of
    # the same proposition, enforces the user-policy risk ceiling,
    # distinguishes opportunity VALUE from CONFIDENCE, classifies an
    # opportunity level (none/weak/meaningful/strong), and can produce
    # an explicit "no worthwhile improvement" preservation assessment.
    # 4.0.0: transformation-aware savings semantics. Fusion no longer
    # derives an estimated saving percentage from the opportunity score
    # (`score * SAVING_PERCENT_FACTOR`). Instead the assessment savings
    # come from the actual proposed transformation: the dominant
    # surviving STORAGE proposition's evidence (expected_saving_percent
    # and expected_saved_bytes). Compatibility-only propositions
    # (container remux) carry no fabricated storage saving. The level
    # gate applies the user-policy worthwhile threshold only to
    # storage-bearing propositions; compatibility improvements are
    # classified by their value score.
    # 4.0.1: transformation/benefit/evidence coherence. The
    # assessment benefit, cost and risk come from the SAME dominant
    # surviving STORAGE proposition that provides the assessment
    # savings (the primary proposed storage transformation), so the
    # selected transformation and its evidence are genuinely the basis
    # for the recommendation. Compatibility-only assessments (no
    # surviving storage proposition) continue to carry the overall
    # dominant proposition's benefit/cost/risk. The merged assessment
    # evidence's transformation-saving keys are aligned with the
    # dominant storage proposition so the evidence cannot contradict
    # the assessment's explicit savings fields when competing
    # storage transformations survive.
    # 4.0.2: dominant-storage metadata alignment (Phase 9 amendment).
    # Where assessment savings come from the dominant surviving
    # storage signal, the merged assessment `basis`, `assumption`,
    # and `modelling_version` keys are overwritten from that same
    # signal, so input ordering cannot misattribute the derivation.
    # Direct-copy semantics: a key the dominant signal does not
    # carry copies as absent-or-null; no value is invented. The
    # compatibility-only branch is untouched.
    semantic_version = "4.0.2"

    # Fusion policy constants, attributable to the fusion version.
    CONFIDENCE_CAP = 0.95

    # Opportunity-level thresholds (documented, versioned):
    # a fused score at or above each threshold is that level.
    LEVEL_STRONG = 0.60
    LEVEL_MEANINGFUL = 0.40
    LEVEL_WEAK = 0.20

    def evaluate(
        self,
        signals: List[DecisionSignal],
        *,
        policy: Optional[UserPolicy] = None,
    ) -> Optional[OpportunityAssessment]:
        """
        Convert decision signals into a combined opportunity
        assessment.

        Returns:
            OpportunityAssessment whenever signals exist. A
            preservation-only (or fully suppressed) input returns an
            assessment with opportunity_level "none": the explicit
            "no worthwhile improvement" conclusion. Empty input
            returns None.
        """

        if not signals:
            return None

        opportunity_signals: List[DecisionSignal] = []
        preserve_signals: List[DecisionSignal] = []

        for signal in signals:

            if signal.direction in OPPORTUNITY_DIRECTIONS:
                opportunity_signals.append(signal)

            elif signal.direction in CONSTRAINT_DIRECTIONS:
                preserve_signals.append(signal)

            else:

                raise ValueError(
                    f"rule '{signal.rule}' produced unrecognised "
                    f"signal direction '{signal.direction}'; "
                    "fusion channels are closed"
                )

        # ---------------------------------------------------------
        # Active-rule weight completeness: every opportunity signal's
        # rule must have an explicit configured weight. This is
        # enforced BEFORE any reconciliation so an unconfigured active
        # rule fails clearly instead of being silently suppressed.
        # ---------------------------------------------------------

        for signal in opportunity_signals:

            if signal.rule not in RULE_WEIGHTS:

                raise ValueError(
                    f"rule '{signal.rule}' has no configured fusion "
                    "weight; active rules must be weighted "
                    "explicitly (see "
                    "recommendation_decision_weights.RULE_WEIGHTS)"
                )

        # ---------------------------------------------------------
        # Reconciliation: a preserve signal suppresses any opportunity
        # signal proposing the same proposition.
        # ---------------------------------------------------------

        suppressed: List[dict] = []
        survivors: List[DecisionSignal] = []

        preserve_by_proposition = {}

        for signal in preserve_signals:

            if signal.proposition:
                preserve_by_proposition.setdefault(
                    signal.proposition,
                    signal,
                )

        for signal in opportunity_signals:

            blocker = (
                preserve_by_proposition.get(
                    signal.proposition,
                    None,
                )
                if signal.proposition
                else None
            )

            if blocker is not None:

                suppressed.append(
                    {
                        "rule": signal.rule,
                        "proposition": signal.proposition,
                        "current_state": signal.current_state,
                        "target_state": signal.target_state,
                        "reason": blocker.reason,
                        "notes": blocker.notes,
                        "risk": signal.risk,
                        "benefit": signal.benefit,
                    }
                )

                continue

            survivors.append(signal)

        # ---------------------------------------------------------
        # User-policy risk ceiling: propositions whose risk exceeds
        # the acceptable ceiling are suppressed as a safety gate.
        # ---------------------------------------------------------

        policy = policy or UserPolicy.default()

        policy_suppressed: List[dict] = []

        remaining: List[DecisionSignal] = []

        for signal in survivors:

            if not policy.risk_acceptable(signal.risk):

                policy_suppressed.append(
                    {
                        "rule": signal.rule,
                        "proposition": signal.proposition,
                        "current_state": signal.current_state,
                        "target_state": signal.target_state,
                        "reason": (
                            f"risk '{signal.risk}' exceeds the "
                            "acceptable ceiling "
                            f"'{policy.effective_max_acceptable_risk()}' "
                            "under user policy"
                        ),
                        "notes": signal.notes,
                        "risk": signal.risk,
                        "benefit": signal.benefit,
                    }
                )

                continue

            remaining.append(signal)

        suppressed.extend(policy_suppressed)

        preservation_reasons = [
            signal.reason
            for signal in preserve_signals
            if signal.reason
        ]

        constraints = [
            {
                "rule": signal.rule,
                "direction": signal.direction,
                "proposition": signal.proposition,
                "confidence": signal.confidence,
                "notes": signal.notes,
                "reason": signal.reason,
                "evidence": dict(signal.evidence or {}),
                "provenance": dict(signal.provenance or {}),
            }
            for signal in preserve_signals
        ]

        if not remaining:

            reasons = [
                "Constraint: " + signal.notes
                for signal in preserve_signals
                if signal.notes
            ]

            for item in suppressed:
                if item["reason"]:
                    reasons.append(
                        "Suppressed: " + item["reason"]
                    )

            if not reasons:
                reasons.append(
                    "No worthwhile improvement was identified."
                )

            return OpportunityAssessment(
                opportunity="none",
                opportunity_level="none",
                priority_label=OPPORTUNITY_LEVEL_LABELS["none"],
                confidence=0.0,
                opportunity_score=0.0,
                estimated_saving_percent=0.0,
                expected_saved_bytes=None,
                evidence=self._merge_evidence(signals),
                reasoning=reasons,
                provenance=self._merge_provenance(signals),
                contributing_rules=[],
                risk="low",
                signals=signals,
                constraints=constraints,
                preservation_reasons=preservation_reasons,
                suppressed_signals=suppressed,
                benefit="none",
                cost="none",
                active_signals=[],
            )

        # ---------------------------------------------------------
        # Value and confidence combination.
        #
        #   score      = weighted mean of proposition VALUES
        #   confidence = weighted mean of intelligence CERTAINTY
        #
        # They are combined independently so value is never disguised
        # as certainty or vice versa.
        # ---------------------------------------------------------

        value_sum = 0.0
        confidence_sum = 0.0
        total_weight = 0.0

        reasons = []
        evidence = {}
        provenance = []
        contributing_rules = []

        dominant = None

        for signal in remaining:

            if signal.rule not in RULE_WEIGHTS:

                raise ValueError(
                    f"rule '{signal.rule}' has no configured fusion "
                    "weight; active rules must be weighted "
                    "explicitly (see "
                    "recommendation_decision_weights.RULE_WEIGHTS)"
                )

            weight = RULE_WEIGHTS[signal.rule]

            value_sum += signal.opportunity_score * weight

            confidence_sum += signal.confidence * weight

            total_weight += weight

            contributing_rules.append(signal.rule)

            if signal.notes:
                reasons.append(signal.notes)

            if signal.evidence:
                evidence.update(signal.evidence)

            if signal.provenance:
                provenance.append(signal.provenance)

            if dominant is None or (
                signal.opportunity_score
                > dominant.opportunity_score
            ):
                dominant = signal

        if total_weight == 0:
            return None

        score = round(value_sum / total_weight, 4)

        confidence = min(
            self.CONFIDENCE_CAP,
            round(confidence_sum / total_weight, 4),
        )

        # Transformation-aware savings (Phase 8). The assessment
        # savings are derived from the ACTUAL proposed transformation,
        # never from the opportunity score. The dominant surviving
        # STORAGE proposition (highest value) carries the expected
        # saving percent and absolute bytes in its evidence, produced
        # by the decision rule from versioned transformation
        # knowledge. Compatibility-only propositions (for example a
        # container remux) have no storage evidence and therefore carry
        # no fabricated storage saving.
        dominant_storage = self._dominant_storage_signal(remaining)

        if dominant_storage is not None:

            estimated_saving_percent = round(
                float(
                    (dominant_storage.evidence or {}).get(
                        "expected_saving_percent", 0.0
                    )
                    or 0.0
                ),
                1,
            )

            expected_saved_bytes = int(
                (dominant_storage.evidence or {}).get(
                    "expected_saved_bytes", 0
                )
                or 0
            )

            if expected_saved_bytes <= 0:
                expected_saved_bytes = None

            # The merged assessment evidence is built from every
            # surviving signal in turn, so when competing storage
            # transformations survive the last writer's saving keys
            # would otherwise contradict the assessment's explicit
            # savings fields. Align them with the dominant storage
            # proposition that genuinely provides the assessment
            # savings.
            evidence["expected_saving_percent"] = (
                estimated_saving_percent
            )
            evidence["expected_saved_bytes"] = (
                expected_saved_bytes
            )

            # Same direct-copy pattern for derivation metadata
            # (Phase 9 amendment): the attribution keys resolve to
            # the same dominant storage signal as the savings,
            # regardless of input order. A key the dominant signal
            # does not carry copies as None; nothing is invented.
            evidence["basis"] = (
                (dominant_storage.evidence or {}).get("basis")
            )
            evidence["assumption"] = (
                (dominant_storage.evidence or {}).get("assumption")
            )
            evidence["modelling_version"] = (
                (dominant_storage.evidence or {}).get(
                    "modelling_version"
                )
            )

        else:

            estimated_saving_percent = 0.0
            expected_saved_bytes = None

        # ---------------------------------------------------------
        # Opportunity-level classification.
        # ---------------------------------------------------------

        level = self._classify_level(
            score,
            estimated_saving_percent,
            policy,
            has_storage_saving=(
                dominant_storage is not None
            ),
        )

        for item in suppressed:
            if item["reason"]:
                reasons.append(
                    "Suppressed: " + item["reason"]
                )

        for constraint in constraints:
            if constraint["notes"]:
                reasons.append(
                    "Constraint: " + constraint["notes"]
                )

        if level == "none":
            reasons.append(
                "No worthwhile improvement under current policy."
            )

        # The transformation that provides the assessment savings
        # also provides its benefit, cost and risk, so the selected
        # transformation and its evidence are genuinely the basis for
        # the recommendation. A compatibility-only assessment (no
        # surviving storage proposition) carries the overall dominant
        # proposition's benefit/cost/risk unchanged.
        basis = (
            dominant_storage
            if dominant_storage is not None
            else dominant
        )

        benefit = (
            basis.benefit
            if basis is not None
            else "none"
        )

        cost = (
            basis.cost
            if basis is not None
            else "none"
        )

        risk = (
            basis.risk
            if basis is not None
            else "unknown"
        )

        return OpportunityAssessment(
            opportunity="media_optimisation",
            opportunity_level=level,
            priority_label=OPPORTUNITY_LEVEL_LABELS.get(
                level,
                OPPORTUNITY_LEVEL_LABELS["none"],
            ),
            confidence=confidence,
            opportunity_score=score,
            estimated_saving_percent=estimated_saving_percent,
            expected_saved_bytes=expected_saved_bytes,
            evidence=evidence,
            reasoning=reasons,
            provenance=provenance,
            contributing_rules=contributing_rules,
            risk=risk,
            signals=signals,
            constraints=constraints,
            preservation_reasons=preservation_reasons,
            suppressed_signals=suppressed,
            benefit=benefit,
            cost=cost,
            active_signals=remaining,
        )

    def _classify_level(
        self,
        score: float,
        estimated_saving_percent: float,
        policy: UserPolicy,
        has_storage_saving: bool = False,
    ) -> str:
        """
        Classify the opportunity level from the fused value score and
        the user-policy worthwhile threshold.

        The user-policy worthwhile-saving gate applies ONLY to
        storage-bearing assessments (a surviving storage proposition
        exists). The decision rules already enforce
        `policy.worthwhile()` before a storage proposition is emitted,
        so this is a defensive fusion-level gate. Compatibility-only
        assessments (for example a container remux) are classified by
        their value score; they carry no storage saving and are not
        suppressed by a storage threshold that does not apply to them.
        """

        if has_storage_saving:

            min_saving = policy.effective_min_saving_percent()

            if estimated_saving_percent < min_saving:
                return "none"

        if score >= self.LEVEL_STRONG:
            return "strong"
        if score >= self.LEVEL_MEANINGFUL:
            return "meaningful"
        if score >= self.LEVEL_WEAK:
            return "weak"
        return "none"

    @staticmethod
    def _dominant_storage_signal(signals):
        """
        The surviving STORAGE proposition with the highest opportunity
        score, or None when no surviving proposition carries a storage
        saving.

        A storage proposition is recognised by the transformation-aware
        `expected_saved_bytes` evidence its rule produced. This is the
        primary proposed storage transformation; its expected saving
        percent and absolute bytes become the assessment's savings.
        Compatibility-only propositions (for example a container remux)
        carry no such evidence and therefore contribute no storage
        saving.
        """

        storage = [
            signal
            for signal in signals
            if (
                int(
                    (signal.evidence or {}).get(
                        "expected_saved_bytes", 0
                    )
                    or 0
                )
                > 0
            )
        ]

        if not storage:
            return None

        return max(
            storage,
            key=lambda signal: signal.opportunity_score,
        )

    @staticmethod
    def _merge_evidence(signals) -> dict:
        merged = {}
        for signal in signals:
            if signal.evidence:
                merged.update(signal.evidence)
        return merged

    @staticmethod
    def _merge_provenance(signals) -> list:
        provenance = []
        for signal in signals:
            if signal.provenance:
                provenance.append(signal.provenance)
        return provenance