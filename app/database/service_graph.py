"""
Shared construction of the repository / shared-domain-service graph.

Single source of truth for wiring the persistence and shared domain
services from a connection. Consumed by:

- app/database/pipeline.py   (canonical scan/analysis pipeline)
- app/web/composition.py     (GUI composition root)

Pipeline-specific authorities (ExpertManager, DecisionEngine, expert
rules) remain constructed by the pipeline. Read-model authorities
(OpportunityQueueService, ProvenanceQueryService,
ProvenanceExplanationService) remain constructed by their consumers.

Construction order is deterministic; behaviour is identical to the
previous inline wiring.
"""

from dataclasses import dataclass

from app.database.repositories.standing_decision_repository import (
    StandingDecisionRepository,
)

from app.database.repositories.user_policy_repository import (
    UserPolicyRepository,
)

from app.database.repositories.analysis_repository import (
    AnalysisRepository,
)

from app.database.repositories.decision_signal_repository import (
    DecisionSignalRepository,
)

from app.database.repositories.evidence_repository import (
    EvidenceRepository,
)

from app.database.repositories.expert_result_repository import (
    ExpertResultRepository,
)

from app.database.repositories.knowledge_repository import (
    KnowledgeRepository,
)

from app.database.repositories.media_repository import (
    MediaRepository,
)

from app.database.repositories.opportunity_repository import (
    OpportunityRepository,
)

from app.database.repositories.organisation_repository import (
    OrganisationRepository,
)

from app.database.repositories.provenance_repository import (
    ProvenanceRepository,
)

from app.database.repositories.recommendation_repository import (
    RecommendationRepository,
)

from app.database.repositories.scan_repository import (
    ScanRepository,
)

from app.knowledge.database_knowledge_service import (
    DatabaseKnowledgeService,
)

from app.services.analysis_validity_service import (
    AnalysisValidityService,
)


@dataclass
class ServiceGraph:
    """
    Repositories and shared domain services wired over one connection.

    Persistence-oriented; contains no application or presentation
    logic. The connection lifecycle remains owned by the caller.
    """

    standing_decision_repository: StandingDecisionRepository
    user_policy_repository: UserPolicyRepository
    media_repository: MediaRepository
    analysis_repository: AnalysisRepository
    evidence_repository: EvidenceRepository
    expert_result_repository: ExpertResultRepository
    provenance_repository: ProvenanceRepository
    knowledge_repository: KnowledgeRepository
    decision_signal_repository: DecisionSignalRepository
    opportunity_repository: OpportunityRepository
    recommendation_repository: RecommendationRepository
    organisation_repository: OrganisationRepository
    scan_repository: ScanRepository
    knowledge_service: DatabaseKnowledgeService
    validity_service: AnalysisValidityService


def build_service_graph(connection) -> ServiceGraph:
    """
    Construct the repository / shared-domain-service graph over the
    provided connection.
    """

    user_policy_repository = UserPolicyRepository(connection)

    standing_decision_repository = StandingDecisionRepository(connection)

    media_repository = MediaRepository(connection)

    decision_signal_repository = DecisionSignalRepository(
        connection
    )

    analysis_repository = AnalysisRepository(
        connection,
        decision_signal_repository=(
            decision_signal_repository
        ),
    )

    evidence_repository = EvidenceRepository(connection)

    expert_result_repository = ExpertResultRepository(connection)

    provenance_repository = ProvenanceRepository(connection)

    knowledge_repository = KnowledgeRepository(connection)

    opportunity_repository = OpportunityRepository(connection)

    recommendation_repository = RecommendationRepository(
        connection
    )

    organisation_repository = OrganisationRepository(
        connection
    )

    scan_repository = ScanRepository(connection)

    knowledge_service = DatabaseKnowledgeService(
        knowledge_repository
    )

    validity_service = AnalysisValidityService(
        media_repository=media_repository,
        provenance_repository=provenance_repository,
        analysis_repository=analysis_repository,
    )

    return ServiceGraph(
        standing_decision_repository=standing_decision_repository,
        user_policy_repository=user_policy_repository,
        media_repository=media_repository,
        analysis_repository=analysis_repository,
        evidence_repository=evidence_repository,
        expert_result_repository=expert_result_repository,
        provenance_repository=provenance_repository,
        knowledge_repository=knowledge_repository,
        decision_signal_repository=decision_signal_repository,
        opportunity_repository=opportunity_repository,
        recommendation_repository=recommendation_repository,
        organisation_repository=organisation_repository,
        scan_repository=scan_repository,
        knowledge_service=knowledge_service,
        validity_service=validity_service,
    )
