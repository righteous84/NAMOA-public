"""
AnalysisContext.

Runtime intelligence layer used throughout NAMOA.

Contains:

    MediaContext
        +
    Evidence
        +
    Expert Results
        +
    Opportunity Assessment
"""

from dataclasses import dataclass, field
from typing import List, Optional

from app.models.media_context import MediaContext
from app.models.evidence_collection import EvidenceCollection
from app.models.expert_result import ExpertResult
from app.models.knowledge_usage import KnowledgeUsage
from app.models.opportunity_assessment import OpportunityAssessment
from app.models.user_policy import UserPolicy


AUTHORITATIVE_DOMAIN_EXPERTS = {
    "video_codec": "codec_expert",
    "resolution": "resolution_expert",
    "hdr": "hdr_expert",
    "source": "source_expert",
    "quality": "quality_expert",
    "container": "container_expert",
    "audio": "audio_expert",
}


@dataclass
class AnalysisContext:

    media: MediaContext

    knowledge_usage: set[KnowledgeUsage] = field(
        default_factory=set
    )

    # Knowledge sets consulted by the Expert currently executing.
    # This is intentionally separate from knowledge_usage, which
    # represents cumulative run-level provenance.
    _expert_knowledge_usage: set[int] = field(
        default_factory=set
    )

    evidence: EvidenceCollection = field(
        default_factory=EvidenceCollection
    )

    expert_results: List[ExpertResult] = field(
        default_factory=list
    )

    assessment: Optional[OpportunityAssessment] = None

    # User policy active for this analysis. Policy influences
    # acceptable trade-offs and worthwhile-benefit thresholds in the
    # Decision layer; it NEVER alters factual observations or expert
    # conclusions. When None, the standard default policy applies.
    policy: Optional[UserPolicy] = None

    def policy_or_default(self) -> UserPolicy:
        return self.policy if self.policy is not None else UserPolicy.default()

    def get_expert_result(
        self,
        expert_name: str
    ) -> Optional[ExpertResult]:

        for result in self.expert_results:

            if result.expert_name == expert_name:
                return result

        return None

    def get_expert_data(
        self,
        expert_name: str
    ):

        result = self.get_expert_result(
            expert_name
        )

        if not result:
            return None

        return result.expert_data

    def get_domain_analysis(
        self,
        domain: str
    ):

        result = self.get_domain_result(
            domain
        )

        if result:
            return result.expert_data.domains.get(
                domain
            )

        return None

    def get_domain_result(
        self,
        domain: str
    ) -> Optional[ExpertResult]:

        authoritative_expert = (
            AUTHORITATIVE_DOMAIN_EXPERTS.get(
                domain
            )
        )

        if authoritative_expert:

            result = self.get_expert_result(
                authoritative_expert
            )

            if (
                result
                and result.expert_data
                and domain in result.expert_data.domains
            ):
                return result

            return None

        for result in self.expert_results:

            if not result.expert_data:
                continue

            if domain in result.expert_data.domains:
                return result

        return None

    def get_domain_confidence(
        self,
        domain: str
    ) -> float:

        analysis = self.get_domain_analysis(
            domain
        )

        if not analysis:
            return 0.0

        return analysis.confidence

    def record_knowledge_usage(
        self,
        knowledge_set_id: int,
    ) -> None:
        """
        Record a knowledge set as consulted during this analysis.

        The knowledge set is always recorded at run level.

        When an Expert attribution scope is active, the same
        knowledge set is also attributed to that Expert.
        """

        self.knowledge_usage.add(
            KnowledgeUsage(
                knowledge_set_id=knowledge_set_id
            )
        )

        self._expert_knowledge_usage.add(
            knowledge_set_id
        )

    def begin_expert_knowledge_scope(self) -> None:
        """
        Begin knowledge attribution for one Expert execution.
        """

        self._expert_knowledge_usage.clear()

    def end_expert_knowledge_scope(self) -> set[int]:
        """
        Return the knowledge sets consulted by the current Expert
        and close its attribution scope.
        """

        knowledge_set_ids = set(
            self._expert_knowledge_usage
        )

        self._expert_knowledge_usage.clear()

        return knowledge_set_ids

    def get_knowledge_set_ids(self) -> set[int]:
        """
        Return every knowledge set consulted during this analysis.
        """

        return {
            usage.knowledge_set_id
            for usage in self.knowledge_usage
        }