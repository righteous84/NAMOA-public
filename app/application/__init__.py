"""
NAMOA Application Service layer.

This package is the upper application-facing orchestration boundary:

    GUI / API / CLI
           |
           v
    Application Services   <- this package (app/application)
           |
           v
    Domain / intelligence / read-model services (app/services)
           |
           v
    Persistence (app/database)

The six established application-facing services are:

    ScanService
    MediaService
    AnalysisService
    RecommendationService
    ProvenanceService
    LibraryService

Sprint 6.12 adds a seventh GUI-facing aggregate read boundary:

    LibraryStatusService

which composes the existing authorities into honest library-level
reads (overview, per-lineage status, storage summary, run history)
without duplicating any authority.

Sprint 7 introduces the authoritative library-intelligence and
recommendation-prioritisation authorities:

    LibraryIntelligenceService       (app/services)
    RecommendationPrioritisationService (app/services)

and evolves the existing boundaries to delegate to them:

    LibraryService        now orchestrates LibraryIntelligenceService
    RecommendationService now also orchestrates
                          RecommendationPrioritisationService

LibraryService no longer remains the intentionally empty boundary from
Sprint 6.11; a genuine authoritative library capability now exists.

Sprint 6.11 Phase 1 establishes the boundary and conventions only.
Full workflows are implemented in later Sprint 6.11 phases.

Conventions
-----------

1. Dependency injection
   Application services receive their collaborators in the constructor
   using keyword-only arguments. No module-level service singletons,
   service locators, or DI frameworks.

2. Construction
   Application services are plain Python classes. A composition root /
   factory is intentionally NOT part of Phase 1; later phases formalise
   wiring. Services remain constructible with explicit dependencies so
   tests can inject real or substitute collaborators.

3. Method boundaries
   Application-facing methods orchestrate existing capabilities. Phase 1
   defines only thin delegations over established authorities; full
   multi-step workflows are deferred.

4. Result objects
   Application services return existing domain / read models
   (e.g. AnalysisProvenance, ProvenanceExplanation, OptimisationCandidate,
   MediaLineage). No new result-object types are introduced purely for
   orchestration.

5. Error handling
   Application services propagate domain errors. "Not found" raises
   ValueError, matching the existing ProvenanceQueryService convention.
   They never swallow or invent errors.

6. Orchestration vs domain logic
   Application services coordinate existing capabilities; they never
   reimplement domain logic. Established authorities remain authoritative:

   - currentness                -> AnalysisValidityService
   - opportunity-queue building -> OpportunityQueueService
   - provenance reconstruction  -> ProvenanceQueryService
   - provenance explanation     -> ProvenanceExplanationService

Dependency direction is strictly downward:

    Application -> Domain / Intelligence / Persistence

The reverse direction does not exist. No module under app/services,
app/database, app/scanner, app/experts, app/knowledge, or the engines
may import from this package.
"""

from app.application.scan_service import ScanService
from app.application.media_service import MediaService
from app.application.analysis_service import AnalysisService
from app.application.recommendation_service import RecommendationService
from app.application.provenance_service import ProvenanceService
from app.application.library_service import LibraryService
from app.application.library_status_service import LibraryStatusService
from app.application.execution_service import ExecutionService
from app.application.operation_service import OperationService
from app.application.transformation_service import TransformationService
from app.application.quick_find_service import QuickFindService
from app.application.preference_service import PreferenceService


__all__ = [
    "ScanService",
    "MediaService",
    "AnalysisService",
    "RecommendationService",
    "ProvenanceService",
    "LibraryService",
    "LibraryStatusService",
    "ExecutionService",
    "OperationService",
    "TransformationService",
    "QuickFindService",
    "PreferenceService",
]
