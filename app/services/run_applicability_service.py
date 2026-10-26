"""
Run applicability evaluation (Sprint 10 correction).

Answers a question that is deliberately DISTINCT from filesystem
currentness:

    "Was this existing analysis run produced under the intelligence
     context that is currently applicable?"

Filesystem currentness remains the sole responsibility of
AnalysisValidityService. This service NEVER inspects the filesystem,
never modifies runs, and never reinterprets results. It only compares
persisted provenance against the currently declared intelligence:

    candidate run's recorded intelligence identity digest
        vs
    digest recomputed from the CURRENT manifest/policy values over the
    knowledge-set versions the candidate run consulted

Evaluation rules:

- A run recorded before identity capture (digest NULL, development-era
  history) is NOT applicable: its producing intelligence cannot be
  established. History is preserved; the next scan legitimately
  creates a new, correctly attributed run.
- A digest mismatch means relevant intelligence changed.
- A consulted knowledge set whose currently resolvable newest version
  differs from the version the run used means relevant knowledge
  changed. Unrelated knowledge sets can never invalidate a run.

Irrelevant software/runtime changes (git revision, refactors) are
excluded from the identity by construction and can never trigger
re-analysis.
"""

from dataclasses import dataclass

from app.versioning import (
    intelligence_identity_digest,
)


REASON_APPLICABLE = "applicable"
REASON_IDENTITY_UNRECORDED = "intelligence_identity_unrecorded"
REASON_IDENTITY_CHANGED = "intelligence_identity_changed"
REASON_KNOWLEDGE_CHANGED = "knowledge_version_changed"


@dataclass(frozen=True)
class ApplicabilityVerdict:
    """
    Read-model result of one applicability evaluation.
    """

    applicable: bool

    reason: str

    analysis_run_id: int | None = None

    detail: dict | None = None


class RunApplicabilityService:
    """
    Read-only domain service for intelligence/provenance
    applicability of an existing analysis run.

    This service:

    - consumes persisted provenance plus the caller-supplied CURRENT
      component-version manifest and policy values
    - never scans the filesystem
    - never modifies analysis_runs or any other table
    - never invokes experts / rules / fusion
    """

    def __init__(
        self,
        *,
        provenance_repository,
        knowledge_repository,
        current_component_versions: dict,
        current_policy_values: dict,
    ):

        self.provenance_repository = provenance_repository
        self.knowledge_repository = knowledge_repository
        self.current_component_versions = (
            current_component_versions
        )
        self.current_policy_values = current_policy_values

    # ---------------------------------------------------------
    # Knowledge scoping helpers
    # ---------------------------------------------------------

    def _consulted_names(
        self,
        analysis_run_id: int,
    ) -> list[str]:
        """
        Names of the knowledge sets a run consulted, from persisted
        usage provenance.
        """

        names = []

        for usage in (
            self.provenance_repository.get_knowledge_usage(
                analysis_run_id
            )
        ):

            resolved = (
                self.knowledge_repository
                .get_set_name_and_version(
                    usage.knowledge_set_id
                )
            )

            if resolved is not None:
                names.append(resolved[0])

        return names

    def _current_knowledge_versions(
        self,
        names,
    ) -> dict[str, str] | None:
        """
        Current newest version per consulted set name, or None when a
        consulted set no longer exists at all.
        """

        resolved_map: dict[str, str] = {}

        for name in names:

            newest = (
                self.knowledge_repository
                .get_newest_set_version(name)
            )

            if newest is None:
                return None

            resolved_map[name] = newest[1]

        return resolved_map

    # ---------------------------------------------------------
    # Evaluation
    # ---------------------------------------------------------

    def evaluate_run(
        self,
        analysis_run,
    ) -> ApplicabilityVerdict:
        """
        Evaluate whether `analysis_run` remains applicable to the
        current intelligence context.
        """

        if analysis_run is None:
            return ApplicabilityVerdict(
                applicable=False,
                reason=REASON_IDENTITY_UNRECORDED,
                detail={"reason": "no completed run"},
            )

        recorded = (
            analysis_run.intelligence_identity
        )

        if not recorded:
            return ApplicabilityVerdict(
                applicable=False,
                reason=REASON_IDENTITY_UNRECORDED,
                analysis_run_id=analysis_run.id,
                detail={
                    "note": (
                        "run predates intelligence identity "
                        "capture; history preserved"
                    )
                },
            )

        consulted_names = self._consulted_names(
            analysis_run.id
        )

        current_knowledge = (
            self._current_knowledge_versions(
                consulted_names
            )
        )

        if current_knowledge is None:
            return ApplicabilityVerdict(
                applicable=False,
                reason=REASON_KNOWLEDGE_CHANGED,
                analysis_run_id=analysis_run.id,
                detail={
                    "note": (
                        "a consulted knowledge set no longer "
                        "resolves"
                    ),
                    "consulted": sorted(consulted_names),
                },
            )

        current_digest = (
            intelligence_identity_digest(
                self.current_component_versions,
                self.current_policy_values,
                current_knowledge,
            )
        )

        if recorded != current_digest:
            return ApplicabilityVerdict(
                applicable=False,
                reason=REASON_IDENTITY_CHANGED,
                analysis_run_id=analysis_run.id,
                detail={
                    "recorded": recorded,
                    "current": current_digest,
                    "consulted_knowledge": (
                        current_knowledge
                    ),
                },
            )

        return ApplicabilityVerdict(
            applicable=True,
            reason=REASON_APPLICABLE,
            analysis_run_id=analysis_run.id,
            detail={
                "consulted_knowledge": current_knowledge
            },
        )