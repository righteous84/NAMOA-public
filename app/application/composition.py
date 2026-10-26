"""
Composition root for NAMOA application services.

Wires the application services over a fresh database connection.
A fresh service graph is built per unit of work (repositories hold a
sqlite3 connection, and connections are thread-bound), so each
external interface (GUI server, CLI invocation) hands this factory its
own fully wired service graph.

This is the single wiring source for application services. The GUI's
seam remains app/web/composition.py, which re-exports this module so
the web layer keeps its single sanctioned import point.
"""

from dataclasses import dataclass

from app.application.standing_decision_service import (
    StandingDecisionService,
)

from app.application.user_policy_service import (
    UserPolicyService,
)

from app.database.db import get_connection

from app.database.repositories.preference_review_repository import (
    PreferenceReviewRepository,
)

from app.database.service_graph import (
    build_service_graph,
)

from app.database.repositories.execution_repository import (
    ExecutionRepository,
)

from app.database.repositories.notification_repository import (
    NotificationRepository,
)

from app.database.repositories.organisation_execution_repository import (
    OrganisationExecutionRepository,
)

from app.services.opportunity_queue_service import (
    OpportunityQueueService,
)

from app.services.savings_prediction_service import (
    SavingsPredictionService,
)

from app.services.library_intelligence_service import (
    LibraryIntelligenceService,
)

from app.services.recommendation_prioritisation_service import (
    RecommendationPrioritisationService,
)

from app.services.provenance_query_service import (
    ProvenanceQueryService,
)

from app.services.provenance_explanation_service import (
    ProvenanceExplanationService,
)

from app.organisation.intelligence import (
    OrganisationIntelligenceService,
)

from app.organisation.policy import (
    DEFAULT_ORGANISATION_POLICY,
)

from app.scanner.scanner import scan_directory
from app.database.pipeline import save_to_db

from app.application.analysis_service import (
    AnalysisService,
)

from app.application.execution_service import (
    ExecutionService,
)

from app.application.filesystem_service import (
    FilesystemService,
)

from app.application.operation_service import (
    OperationService,
)

from app.application.quick_find_service import (
    QuickFindService,
)
from app.application.preference_service import (
    PreferenceService,
)
from app.application.preview_service import (
    PreviewService,
)

from app.application.transformation_service import (
    TransformationService,
)

from app.application.bulk_optimisation_service import (
    BulkOptimisationService,
)

from app.application.bulk_organisation_service import (
    BulkOrganisationService,
)

from app.application.integration_service import (
    IntegrationService,
)

from app.application.library_service import (
    LibraryService,
)

from app.application.library_status_service import (
    LibraryStatusService,
)

from app.application.media_service import (
    MediaService,
)

from app.application.notification_service import (
    NotificationService,
)

from app.application.organisation_service import (
    OrganisationService,
)

from app.application.organisation_execution_service import (
    OrganisationExecutionService,
)

from app.application.provenance_service import (
    ProvenanceService,
)

from app.application.recommendation_service import (
    RecommendationService,
)

from app.application.scan_service import (
    ScanService,
)


@dataclass
class Services:
    """
    Fully wired application services exposed to external interfaces.
    """

    user_policy_service: UserPolicyService
    standing_decision_service: StandingDecisionService
    scan_service: ScanService
    media_service: MediaService
    analysis_service: AnalysisService
    recommendation_service: RecommendationService
    provenance_service: ProvenanceService
    library_service: LibraryService
    library_status_service: LibraryStatusService
    execution_service: ExecutionService
    organisation_service: OrganisationService
    organisation_execution_service: OrganisationExecutionService
    integration_service: IntegrationService
    bulk_organisation_service: BulkOrganisationService
    notification_service: NotificationService
    filesystem_service: FilesystemService
    operation_service: OperationService
    transformation_service: TransformationService
    bulk_optimisation_service: BulkOptimisationService
    quick_find_service: QuickFindService
    preference_service: PreferenceService
    preview_service: PreviewService


def build_services(database_path=None) -> Services:
    """
    Compose the application service graph over `database_path`
    (defaults to the project database).
    """

    connection = get_connection(database_path)

    # Repositories and the shared validity authority come from the
    # shared construction helper (single wiring source of truth,
    # also used by the canonical pipeline).
    graph = build_service_graph(connection)

    user_policy_service = UserPolicyService(
        user_policy_repository=graph.user_policy_repository,
    )

    standing_decision_service = StandingDecisionService(
        standing_decision_repository=(
            graph.standing_decision_repository
        ),
    )

    opportunity_queue_service = OpportunityQueueService(
        opportunity_repository=graph.opportunity_repository,
        media_repository=graph.media_repository,
        analysis_validity_service=graph.validity_service,
        standing_decision_repository=(
            graph.standing_decision_repository
        ),
    )

    library_intelligence_service = LibraryIntelligenceService(
        media_repository=graph.media_repository,
        analysis_validity_service=graph.validity_service,
        opportunity_queue_service=opportunity_queue_service,
    )

    recommendation_prioritisation_service = (
        RecommendationPrioritisationService(
            opportunity_queue_service=opportunity_queue_service,
        )
    )

    provenance_query_service = ProvenanceQueryService(
        provenance_repository=graph.provenance_repository,
        evidence_repository=graph.evidence_repository,
        expert_result_repository=graph.expert_result_repository,
        decision_signal_repository=(
            graph.decision_signal_repository
        ),
        analysis_repository=graph.analysis_repository,
        media_repository=graph.media_repository,
        recommendation_repository=(
            graph.recommendation_repository
        ),
    )

    provenance_explanation_service = (
        ProvenanceExplanationService()
    )

    # The notification system is a separate presentation capability:
    # it uses its own connection so its best-effort writes never
    # interfere with an in-flight scan/execution transaction on the
    # shared graph connection.
    notification_service = NotificationService(
        notification_repository=NotificationRepository(
            get_connection(database_path)
        ),
    )

    filesystem_service = FilesystemService()

    def _scan_preference_state(scan_database_path):
        """
        Supply accepted preference inputs for one scan from the
        durable review ledger, or None when there is nothing to
        apply. Read-only: never writes, transitions, or accepts.
        Missing preference tables (databases migrated before Phase
        15E) also yield None, preserving previous behaviour.
        """

        from app.preferences.review import load_accepted_scan_state

        connection = get_connection(scan_database_path)

        try:
            return load_accepted_scan_state(
                PreferenceReviewRepository(connection)
            )
        finally:
            connection.close()

    scan_service = ScanService(
        scanner=scan_directory,
        pipeline=save_to_db,
        scan_repository=graph.scan_repository,
        notification_service=notification_service,
        user_policy_service=user_policy_service,
        preference_state_provider=_scan_preference_state,
    )

    media_service = MediaService(
        media_repository=graph.media_repository,
        provenance_query_service=provenance_query_service,
    )

    analysis_service = AnalysisService(
        analysis_pipeline=save_to_db,
        media_service=media_service,
        user_policy_service=user_policy_service,
    )

    recommendation_service = RecommendationService(
        opportunity_queue_service=opportunity_queue_service,
        recommendation_prioritisation_service=(
            recommendation_prioritisation_service
        ),
        recommendation_repository=(
            graph.recommendation_repository
        ),
    )

    provenance_service = ProvenanceService(
        provenance_query_service=provenance_query_service,
        provenance_explanation_service=(
            provenance_explanation_service
        ),
    )

    library_status_service = LibraryStatusService(
        media_service=media_service,
        recommendation_service=recommendation_service,
        validity_service=graph.validity_service,
        provenance_repository=graph.provenance_repository,
        analysis_repository=graph.analysis_repository,
    )

    library_service = LibraryService(
        library_intelligence_service=library_intelligence_service,
    )

    operation_service = OperationService()

    transformation_service = TransformationService(
        operation_service=operation_service,
    )

    prediction_service = SavingsPredictionService(
        knowledge_service=graph.knowledge_service,
    )

    execution_service = ExecutionService(
        execution_repository=ExecutionRepository(connection),
        recommendation_service=recommendation_service,
        media_repository=graph.media_repository,
        recommendation_repository=(
            graph.recommendation_repository
        ),
        transformation_service=transformation_service,
        prediction_service=prediction_service,
        notification_service=notification_service,
        user_policy_service=user_policy_service,
    )

    organisation_intelligence_service = (
        OrganisationIntelligenceService(
            media_repository=graph.media_repository,
            organisation_repository=(
                graph.organisation_repository
            ),
        )
    )

    integration_service = IntegrationService(
        organisation_repository=graph.organisation_repository,
        media_repository=graph.media_repository,
        notification_service=notification_service,
    )

    organisation_service = OrganisationService(
        organisation_intelligence_service=(
            organisation_intelligence_service
        ),
        organisation_repository=(
            graph.organisation_repository
        ),
        default_policy=DEFAULT_ORGANISATION_POLICY,
        notification_service=notification_service,
        media_repository=graph.media_repository,
        integration_service=integration_service,
    )

    organisation_execution_service = OrganisationExecutionService(
        execution_repository=OrganisationExecutionRepository(
            connection
        ),
        organisation_repository=graph.organisation_repository,
        media_repository=graph.media_repository,
        notification_service=notification_service,
    )

    bulk_organisation_service = BulkOrganisationService(
        organisation_service=organisation_service,
        organisation_execution_service=(
            organisation_execution_service
        ),
    )

    quick_find_service = QuickFindService(
        analysis_service=analysis_service,
        media_service=media_service,
        recommendation_service=recommendation_service,
    )

    bulk_optimisation_service = BulkOptimisationService(
        execution_service=execution_service,
    )

    preference_service = PreferenceService(
        connection=connection,
        media_repository=graph.media_repository,
        analysis_repository=graph.analysis_repository,
        validity_service=graph.validity_service,
        user_policy_service=user_policy_service,
    )

    preview_service = PreviewService(
        media_repository=graph.media_repository,
        validity_service=graph.validity_service,
        recommendation_service=recommendation_service,
        execution_service=execution_service,
        preference_service=preference_service,
        transformation_service=transformation_service,
        operation_service=operation_service,
        notification_service=notification_service,
        user_policy_service=user_policy_service,
    )

    return Services(
        user_policy_service=user_policy_service,
        standing_decision_service=standing_decision_service,
        scan_service=scan_service,
        media_service=media_service,
        analysis_service=analysis_service,
        recommendation_service=recommendation_service,
        provenance_service=provenance_service,
        library_service=library_service,
        library_status_service=library_status_service,
        execution_service=execution_service,
        organisation_service=organisation_service,
        organisation_execution_service=(
            organisation_execution_service
        ),
        integration_service=integration_service,
        bulk_organisation_service=bulk_organisation_service,
        notification_service=notification_service,
        filesystem_service=filesystem_service,
        operation_service=operation_service,
        transformation_service=transformation_service,
        bulk_optimisation_service=bulk_optimisation_service,
        quick_find_service=quick_find_service,
        preference_service=preference_service,
        preview_service=preview_service,
    )
