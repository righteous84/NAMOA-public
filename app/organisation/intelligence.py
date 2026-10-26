"""
Organisation intelligence authority (Sprint 13).

One decision run deterministically converts organisation
EVIDENCE (derived from persisted observations) plus versioned
rule INTELLIGENCE plus operator POLICY into durable organisation
PROPOSALS.

Domain separation enforced here:

- evidence      facts from persisted observations only
- intelligence  versioned rule components (semantic versions)
- policy        operator-owned selection/roots, snapshotted per
                run but never versioned as intelligence
- proposal      the durable recommendation output (typed intent)
- user preference / execution intent / filesystem operation /
                observation are NOT modelled here; execution is
                Sprint 14 and resulting state arrives through
                the canonical filesystem-observation mechanism

The decision-run anchor mirrors configuration-snapshot
conventions: rule versions, policy values, git revision and a
deterministic organisation identity digest are persisted so any
historical proposal remains attributable to the exact inputs
that produced it. The digest is a SEPARATE domain digest: it
never participates in analysis applicability, and changing
organisation rules never invalidates analyses.

ZERO filesystem mutation: generation reads observations,
computes payloads in memory, persists them, and nothing else.
"""

from app.organisation.policy import (
    OrganisationPolicy,
    organisation_identity_digest,
    rule_manifest,
)
from app.organisation.rules import (
    CATEGORY_UNCLASSIFIED,
    DestinationTemplateRules,
    DuplicateDetectionRules,
    GroupingRules,
    LibraryClassificationRules,
    NamingConsistencyRules,
    OrderingRules,
    select_library_root,
)
from app.organisation.evidence import (
    OrganisationEvidenceBuilder,
    compute_content_hash,
    normalise_path,
)
from app.versioning import get_git_revision

RULE_CITATION_PREFIX = "rule:"


class OrganisationIntelligenceService:
    """
    Deterministic organisation decision authority.
    """

    semantic_version = "1.0.0"

    def __init__(
        self,
        *,
        media_repository,
        organisation_repository,
        git_revision_provider=None,
    ):

        self.media_repository = media_repository
        self.organisation_repository = (
            organisation_repository
        )
        self._git_revision_provider = (
            git_revision_provider or get_git_revision
        )

        self._evidence_builder = (
            OrganisationEvidenceBuilder()
        )

    # ---------------------------------------------------------
    # explicit hash acquisition (optional evidence)
    # ---------------------------------------------------------

    def acquire_content_hashes(
        self,
        media_ids=None,
    ) -> dict:
        """
        Explicitly acquire sha256 content hashes as OPTIONAL
        evidence for chosen lineages (default: all active
        lineages).

        This is deliberately NOT part of normal scanning: a
        normal scan reads only filesystem metadata and never the
        complete contents of media files. Acquisition happens
        only when a caller asks for it.

        Per lineage, acquisition is refused honestly when the
        lineage is missing, has no current observation, the file
        no longer exists, or its current size + mtime fingerprint
        no longer matches the current observation - a hash is
        only ever computed for the exact observed state it
        describes.

        EVIDENCE SEMANTICS (architectural correction): a
        successful acquisition returns the digest to the caller
        as FORWARD-ONLY, IN-MEMORY evidence. It performs NO
        persistence:

        - no file_observations row is created or altered
          (observations are immutable records of scanner-driven
          filesystem state; hash acquisition is evidence
          acquisition, not a new observation);
        - Media Identity, current observation/currentness
          semantics and identity continuity are untouched;
        - no execution behaviour is invoked.

        Persisting acquired hashes into a durable evidence store
        would require an Architect-approved mechanism and is
        intentionally NOT part of Sprint 13.
        """

        if media_ids is None:

            lineages = sorted(
                self.media_repository.get_active_lineages(),
                key=lambda lineage: lineage.id,
            )

            targets = [lineage.id for lineage in lineages]

        else:

            targets = list(media_ids)

        acquired = []

        refused = []

        for media_id in targets:

            try:

                result = self.acquire_content_hash(
                    media_id=media_id,
                )

            except ValueError as error:

                refused.append(
                    {
                        "media_id": media_id,
                        "reason": str(error),
                    }
                )

                continue

            if result["acquired"]:

                acquired.append(result)

            else:

                refused.append(
                    {
                        "media_id": media_id,
                        "reason": result["reason"],
                    }
                )

        return {
            "acquired": acquired,
            "refused": refused,
        }

    def acquire_content_hash(
        self,
        *,
        media_id: int,
    ) -> dict:
        """
        Acquire one lineage's content hash explicitly. See
        acquire_content_hashes for the semantics and refusals.
        Performs NO database writes of any kind.
        """

        from pathlib import Path

        lineage = self.media_repository.get_media_item(
            media_id
        )

        if lineage is None:

            raise ValueError(
                f"Media lineage {media_id} not found"
            )

        refusal = (
            lambda reason: {
                "acquired": False,
                "media_id": media_id,
                "reason": reason,
            }
        )

        if lineage.status == "missing":

            return refusal(
                "lineage is marked missing; nothing to hash"
            )

        observations = (
            self.media_repository.get_file_observations(
                media_id
            )
        )

        current = None

        for observation in observations:

            if (
                current is None
                or observation.id > current.id
            ):

                current = observation

        if current is None:

            return refusal(
                "no current observation to hash against"
            )

        try:

            stat = Path(lineage.file_path).stat()

        except OSError:

            return refusal(
                "file not found at the lineage path"
            )

        if (
            stat.st_size != current.size_bytes
            or stat.st_mtime_ns != current.file_mtime_ns
        ):

            return refusal(
                "filesystem state changed since the current "
                "observation; scan first"
            )

        digest = compute_content_hash(lineage.file_path)

        if not digest:

            return refusal(
                "file could not be read for hashing"
            )

        # Forward-only, in-memory evidence: the digest is
        # returned to the caller and deliberately NOT persisted.
        # No observation row, no lineage change, no currentness
        # effect, no commit.
        return {
            "acquired": True,
            "media_id": media_id,
            "sha256": digest,
            "verified_observation_id": current.id,
        }

    # ---------------------------------------------------------
    # decision runs
    # ---------------------------------------------------------

    def generate_proposals(
        self,
        *,
        policy: OrganisationPolicy | None = None,
        preferences=None,
    ) -> dict:
        """
        Run one deterministic decision pass over the current
        active library and persist its proposals atomically.

        A decision run becomes visible only when complete: all
        writes happen in one transaction committed at the end;
        any failure rolls everything back.

        `preferences` (Phase 13) are operator-owned
        metadata/tag/naming/classification preferences. They
        resolve into the effective policy through
        `resolve_effective_policy` and their payload is
        snapshotted verbatim alongside the policy values, so
        each proposal stays attributable to the exact
        preferences that produced it. None (default) preserves
        existing behaviour exactly.

        Returns an honest summary of what was considered,
        produced, superseded, and how far hash coverage reaches.
        """

        from app.organisation.preferences import (
            resolve_effective_policy,
        )

        base_policy = policy or OrganisationPolicy()

        effective_policy = resolve_effective_policy(
            base_policy,
            preferences,
        )

        connection = (
            self.organisation_repository.connection
        )

        lineages = sorted(
            self.media_repository.get_active_lineages(),
            key=lambda lineage: lineage.id,
        )

        evidences = []

        metadata_domains = (
            tuple(preferences.metadata_domains)
            if preferences is not None
            else None
        )

        for lineage in lineages:

            observations = (
                self.media_repository.get_file_observations(
                    lineage.id
                )
            )

            if not observations:
                # An active lineage without observations cannot
                # be reasoned about honestly; skip without
                # inventing evidence.
                continue

            evidences.append(
                self._evidence_builder.build(
                    lineage,
                    observations,
                    metadata_domains=metadata_domains,
                )
            )

        enabled = effective_policy.enabled_rules

        rule_versions = rule_manifest(enabled)

        policy_values = effective_policy.policy_values()

        if preferences is not None:

            # Preference attribution: the exact preference
            # payload participates in the snapshot (and
            # therefore the identity digest) of every run it
            # influences. Runs without preferences snapshot
            # exactly as before.
            policy_values = {
                **policy_values,
                "preferences": (
                    preferences.to_preference_payload()
                ),
            }

        identity_digest = organisation_identity_digest(
            rule_versions,
            policy_values,
        )

        hashed_total = len(evidences)

        hashed_count = sum(
            1
            for item in evidences
            if item.sha256_hash
        )

        try:

            payloads, category_counts, unclassified_ids = (
                self._evaluate_rules(
                    evidences=evidences,
                    policy=effective_policy,
                    enabled=enabled,
                )
            )

            decision_run_id = (
                self.organisation_repository
                .create_decision_run(
                    library_roots=list(
                        effective_policy.library_roots
                    ),
                    rule_versions=rule_versions,
                    policy_values=policy_values,
                    git_revision=(
                        self._git_revision_provider()
                    ),
                    identity_digest=identity_digest,
                    lineages_considered=len(evidences),
                    proposals_created=len(payloads),
                    hash_coverage_total=hashed_total,
                    hash_coverage_hashed=hashed_count,
                )
            )

            proposal_ids = []

            for payload in payloads:

                proposal_ids.append(
                    self.organisation_repository
                    .create_proposed(
                        decision_run_id=decision_run_id,
                        intelligence_identity=(
                            identity_digest
                        ),
                        **payload,
                    )
                )

            # Supersession: proposals still 'proposed' from
            # OLDER decision runs for the considered lineages
            # are superseded by this newer run. Accepted and
            # rejected proposals are durable human decisions
            # and remain untouched.
            stale_ids = [
                record.id
                for record in (
                    self.organisation_repository
                    .list_by_states(("proposed",))
                )
                if record.decision_run_id < decision_run_id
            ]

            superseded_count = (
                self.organisation_repository
                .supersede_proposals(
                    stale_ids,
                    new_decision_run_id=decision_run_id,
                )
            )

            connection.commit()

        except Exception:

            connection.rollback()

            raise

        return {
            "decision_run_id": decision_run_id,
            "identity_digest": identity_digest,
            "rule_versions": rule_versions,
            "policy_values": policy_values,
            "lineages_considered": len(evidences),
            "proposals_created": len(proposal_ids),
            "proposal_ids": proposal_ids,
            "superseded_count": superseded_count,
            "hash_coverage": {
                "total": hashed_total,
                "hashed": hashed_count,
                "unhashed": hashed_total - hashed_count,
            },
            "category_counts": category_counts,
            "unclassified_media_ids": unclassified_ids,
        }

    def latest_decision_run(self):

        return (
            self.organisation_repository
            .latest_decision_run()
        )

    # ---------------------------------------------------------
    # rule evaluation (pure, deterministic)
    # ---------------------------------------------------------

    def _evaluate_rules(
        self,
        *,
        evidences,
        policy,
        enabled,
    ):
        """
        Evaluate the enabled rule components over the evidence
        and return in-memory proposal payloads.

        Returns (payloads, category_counts, unclassified_ids).
        """

        payloads = []

        category_counts: dict[str, int] = {}

        unclassified_ids: list[int] = []

        def is_enabled(component_name: str) -> bool:

            return (
                enabled is None
                or component_name in enabled
            )

        duplicates_enabled = is_enabled(
            DuplicateDetectionRules.name
        )

        classification_enabled = is_enabled(
            LibraryClassificationRules.name
        )

        naming_enabled = is_enabled(
            NamingConsistencyRules.name
        )

        destination_enabled = is_enabled(
            DestinationTemplateRules.name
        )

        grouping_enabled = is_enabled(GroupingRules.name)

        ordering_enabled = is_enabled(OrderingRules.name)

        roots = tuple(policy.library_roots)

        destinations_possible = bool(
            roots and destination_enabled
        )

        # -----------------------------------------------------
        # Pass 1: duplicates + classification/naming/destination
        # -----------------------------------------------------

        placement = {}

        for evidence in evidences:

            if not destinations_possible:

                continue

            classification = (
                LibraryClassificationRules.classify(
                    file_name=evidence.name,
                    path_segments=(
                        evidence.path_segments
                    ),
                )
                if classification_enabled
                else None
            )

            if classification is None:

                category_counts["*classification_disabled*"] = (
                    category_counts.get(
                        "*classification_disabled*", 0
                    )
                    + 1
                )

                continue

            category = classification.category

            category_counts[category] = (
                category_counts.get(category, 0) + 1
            )

            if category == CATEGORY_UNCLASSIFIED:

                unclassified_ids.append(evidence.media_id)

                continue

            root = select_library_root(roots, evidence.path)

            destination_directory = (
                DestinationTemplateRules.destination_directory(
                    root,
                    category,
                )
            )

            naming = (
                NamingConsistencyRules.proposed_name(
                    evidence.name
                )
                if naming_enabled
                else None
            )

            proposed_name = (
                naming.proposed_name
                if naming is not None and naming.changed
                else None
            )

            final_name = proposed_name or (
                evidence.name or ""
            )

            full_destination = (
                DestinationTemplateRules.full_destination(
                    destination_directory,
                    final_name,
                )
            )

            correctly_placed = normalise_path(
                evidence.path
            ).startswith(
                normalise_path(destination_directory)
                + "/"
            )

            placement[evidence.media_id] = {
                "category": category,
                "destination_directory": (
                    destination_directory
                ),
                "final_name": final_name,
                "correctly_placed": correctly_placed,
            }

            reasoning = list(classification.reasoning)

            rationale = [
                f"{RULE_CITATION_PREFIX}{LibraryClassificationRules.name}"
                f"@{LibraryClassificationRules.semantic_version}: "
                + line
                for line in reasoning
            ]

            evidence_citation = {
                "observation_id": evidence.observation_id,
                "current_path": evidence.path,
                "file_name": evidence.name,
                "path_segments": list(
                    evidence.path_segments
                ),
                "filename_attributes": (
                    evidence.filename_attributes
                ),
            }

            if naming is not None and naming.changed:

                rationale.append(
                    f"{RULE_CITATION_PREFIX}"
                    f"{NamingConsistencyRules.name}"
                    f"@{NamingConsistencyRules.semantic_version}: "
                    + " ".join(naming.reasoning)
                )

            if not correctly_placed:

                rationale.append(
                    "current location does not match the "
                    f"proposed {category} destination "
                    "directory"
                )

                payloads.append(
                    {
                        "media_id": evidence.media_id,
                        "intent": "move_destination",
                        "related_media_id": None,
                        "proposed_destination": (
                            full_destination
                        ),
                        "proposed_name": proposed_name,
                        "confidence": (
                            classification.confidence
                        ),
                        "risk": "low",
                        "rationale": rationale,
                        "evidence": {
                            **evidence_citation,
                            "library_root": root,
                            "category": category,
                            "destination_directory": (
                                destination_directory
                            ),
                        },
                    }
                )

            elif proposed_name:

                payloads.append(
                    {
                        "media_id": evidence.media_id,
                        "intent": "rename",
                        "related_media_id": None,
                        "proposed_destination": None,
                        "proposed_name": proposed_name,
                        "confidence": (
                            classification.confidence
                        ),
                        "risk": "low",
                        "rationale": rationale
                        + [
                            "already placed in the "
                            "correct destination "
                            "directory",
                        ],
                        "evidence": {
                            **evidence_citation,
                            "library_root": root,
                            "category": category,
                        },
                    }
                )

        # -----------------------------------------------------
        # Pass 2: duplicate candidates (hash-confirmed only)
        # -----------------------------------------------------

        if duplicates_enabled:

            duplicate_groups = (
                DuplicateDetectionRules.find_duplicate_groups(
                    evidences
                )
            )

            for group in duplicate_groups:

                primary = group["primary"]

                for member in group["duplicates"]:

                    payloads.append(
                        {
                            "media_id": member.media_id,
                            "intent": "flag_duplicate",
                            "related_media_id": (
                                primary.media_id
                            ),
                            "proposed_destination": None,
                            "proposed_name": None,
                            "confidence": (
                                DuplicateDetectionRules.confidence
                            ),
                            "risk": (
                                DuplicateDetectionRules.risk
                            ),
                            "rationale": [
                                f"{RULE_CITATION_PREFIX}"
                                f"{DuplicateDetectionRules.name}"
                                f"@{DuplicateDetectionRules.semantic_version}:",
                                "exact sha256 content-hash "
                                "equality between the two "
                                "current observations",
                                "duplicate EVIDENCE only; "
                                "this candidate is NOT "
                                "identity equivalence and "
                                "no merge has occurred",
                            ],
                            "evidence": {
                                "method": (
                                    DuplicateDetectionRules.method
                                ),
                                "sha256": group["sha256"],
                                "primary_media_id": (
                                    primary.media_id
                                ),
                                "primary_path": primary.path,
                                "member_observation_id": (
                                    member.observation_id
                                ),
                                "member_path": member.path,
                            },
                        }
                    )

        # -----------------------------------------------------
        # Pass 3: grouping + ordering per shared destination
        # -----------------------------------------------------

        if destinations_possible and grouping_enabled:

            groups: dict[str, list[dict]] = {}

            for evidence in evidences:

                info = placement.get(evidence.media_id)

                if info is None:
                    continue

                groups.setdefault(
                    info["destination_directory"],
                    [],
                ).append(
                    {
                        "media_id": evidence.media_id,
                        "final_name": info["final_name"],
                    }
                )

            for destination_directory in sorted(groups):

                members = groups[destination_directory]

                if (
                    len(members)
                    < GroupingRules.minimum_group_size
                ):
                    continue

                members_sorted = sorted(
                    members,
                    key=lambda member: (
                        OrderingRules.sort_key(
                            member["final_name"]
                        ),
                        member["media_id"],
                    ),
                )

                ordered_ids = [
                    member["media_id"]
                    for member in members_sorted
                ]

                anchor_id = min(ordered_ids)

                grouping_rationale = [
                    f"{RULE_CITATION_PREFIX}"
                    f"{GroupingRules.name}"
                    f"@{GroupingRules.semantic_version}: "
                    f"{len(members)} items resolve to the "
                    "same destination directory",
                ]

                payloads.append(
                    {
                        "media_id": anchor_id,
                        "intent": "group_with",
                        "related_media_id": None,
                        "proposed_destination": (
                            destination_directory
                        ),
                        "proposed_name": None,
                        "confidence": 1.0,
                        "risk": "low",
                        "rationale": grouping_rationale,
                        "evidence": {
                            "member_media_ids": ordered_ids,
                            "sort_key": (
                                OrderingRules.sort_key_name
                            )
                            if ordering_enabled
                            else None,
                        },
                    }
                )

                if ordering_enabled:

                    payloads.append(
                        {
                            "media_id": anchor_id,
                            "intent":
                                "order_within_group",
                            "related_media_id": None,
                            "proposed_destination": (
                                destination_directory
                            ),
                            "proposed_name": None,
                            "confidence": 1.0,
                            "risk": "low",
                            "rationale": [
                                f"{RULE_CITATION_PREFIX}"
                                f"{OrderingRules.name}"
                                f"@{OrderingRules.semantic_version}:"
                                " deterministic casefolded "
                                "name order within the "
                                "group",
                            ],
                            "evidence": {
                                "ordered_media_ids": (
                                    ordered_ids
                                ),
                                "sort_key": (
                                    OrderingRules.sort_key_name
                                ),
                            },
                        }
                    )

        return payloads, category_counts, unclassified_ids
