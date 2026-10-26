"""
Base interface for all Decision Engine rules.

Rules analyse an AnalysisContext and produce DecisionSignal objects.

Rules must:
- Never perform I/O
- Never modify MediaContext
- Never execute FFmpeg
- Never access the database directly

Rules consume maintained semantic meaning through the same
KnowledgeService boundary used by Experts. When a rule consults
knowledge, the consultation is recorded on the AnalysisContext and
therefore participates in the run's knowledge provenance and
intelligence identity.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from app.models.analysis_context import AnalysisContext
from app.decision_engine.signals.decision_signal import DecisionSignal


class BaseDecisionRule(ABC):
    """
    Base class for every Decision Rule.
    """

    name: str = "base_rule"

    # Semantic version of this Rule's decision behaviour.
    # A semantic change (threshold, classification, calculation or
    # interpretation semantics) MUST bump this version.
    semantic_version: str = "0.0.0"

    def __init__(self, knowledge_service=None):
        """
        A KnowledgeService may be injected so the rule can consult
        maintained, versioned semantic relationships.

        Knowledge/decision-logic separation:
        - Domain assumptions and maintained relationships live in
          versioned Knowledge.
        - Deterministic decision logic (thresholds, combination,
          scoring, policy gates) lives in the Rule (Python).

        When a knowledge service IS present (production), a missing
        required knowledge value must fail closed: the rule must not
        silently substitute an untracked second copy of production
        intelligence. When NO service is present, documented fallback
        constants may be used for isolated unit testing only; they
        never masquerade as production Knowledge.
        """
        self.knowledge_service = knowledge_service

    @property
    def has_knowledge_service(self) -> bool:
        """
        Whether this rule was constructed with a KnowledgeService.

        True means production knowledge is authoritative: a missing
        required value is a fail-closed condition, never a silent
        fallback to test constants.
        """
        return self.knowledge_service is not None

    @abstractmethod
    def evaluate(
        self,
        context: AnalysisContext
    ) -> List[DecisionSignal]:
        """
        Analyse the AnalysisContext and return
        zero or more decision signals.
        """
        pass

    def supports(
        self,
        context: AnalysisContext
    ) -> bool:
        """
        Optional filter for deciding whether this rule should run.
        """
        return True

    def _knowledge(
        self,
        context: AnalysisContext,
        *,
        domain: str,
        key: str,
    ):
        """
        Consult a knowledge entry through the injected service.

        Returns None when no service is available OR when the service
        returns no entry. Rules MUST distinguish these cases using
        `has_knowledge_service`: with a service present, None means
        required production knowledge is missing (fail-closed); with
        no service, the rule may use documented test fallbacks.
        Consultations are recorded on the context when a service is
        present.
        """

        if self.knowledge_service is None:
            return None

        return self.knowledge_service.get(
            context=context,
            domain=domain,
            key=key,
        )

    def _get_domain(
        self,
        context: AnalysisContext,
        domain: str,
    ):
        """
        Return (result, analysis) for the authoritative expert result
        of a domain, or (None, None) when unavailable.
        """

        result = context.get_domain_result(domain)

        if result is None or result.expert_data is None:
            return None, None

        analysis = result.expert_data.domains.get(domain)

        if analysis is None:
            return None, None

        return result, analysis

    def _domain_value(
        self,
        context: AnalysisContext,
        domain: str,
        default: str | None = None,
    ):
        """
        The authoritative selected value for a domain, or `default`
        when unavailable.
        """

        _, analysis = self._get_domain(context, domain)

        if analysis is None:
            return default

        return analysis.selected_value

    def _build_provenance(
        self,
        result,
        analysis,
        domain: str,
    ) -> dict:
        """
        Structured provenance from an authoritative expert result and
        its domain analysis.
        """

        return {
            "expert": result.expert_name,
            "domain": domain,
            "expert_confidence": analysis.confidence,
            "agreement": (
                analysis.agreement.value
                if analysis.agreement is not None
                else None
            ),
            "uncertainty": analysis.uncertainty,
            "knowledge_sets": sorted(
                result.knowledge_set_ids
            ),
        }

    # Documented benefit-category thresholds for absolute expected
    # saving. These are versioned with the rule semantics that use
    # them.
    SUBSTANTIAL_SAVING_BYTES = 2 * 1024**3  # >= 2 GiB
    MODERATE_SAVING_BYTES = 500 * 1024**2   # >= 500 MiB
    SMALL_SAVING_BYTES = 50 * 1024**2       # >= 50 MiB

    @classmethod
    def benefit_category(cls, saved_bytes) -> str:
        """
        Benefit category from an expected absolute saving (bytes):
        substantial / moderate / small / none.
        """

        try:
            value = int(saved_bytes or 0)
        except (TypeError, ValueError):
            value = 0

        if value >= cls.SUBSTANTIAL_SAVING_BYTES:
            return "substantial"
        if value >= cls.MODERATE_SAVING_BYTES:
            return "moderate"
        if value >= cls.SMALL_SAVING_BYTES:
            return "small"
        return "none"

    def _preserve_signal(
        self,
        *,
        context: AnalysisContext,
        proposition: str,
        reason: str,
        notes: str,
        confidence: float = 1.0,
        result=None,
        analysis=None,
        domain: str = "",
        benefit: str = "none",
        cost: str = "none",
        risk: str = "unknown",
        evidence: Optional[dict] = None,
    ) -> DecisionSignal:
        """
        Build a preservation signal that states a reason NOT to
        optimise. Preservation signals carry the proposition they
        negate so fusion can suppress contradicting opportunities and
        explain the suppression.
        """

        provenance: dict = {}

        if result is not None and analysis is not None:
            provenance = self._build_provenance(
                result,
                analysis,
                domain,
            )

        return DecisionSignal(
            rule=self.name,
            opportunity_score=0.0,
            confidence=confidence,
            direction="preserve",
            proposition=proposition,
            current_state=None,
            target_state=None,
            benefit=benefit,
            cost=cost,
            risk=risk,
            reason=reason,
            notes=notes,
            evidence=dict(evidence or {}),
            provenance=provenance,
        )