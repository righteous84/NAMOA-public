"""
Organisation PLANNING (Sprint 15).

Shared deterministic planning semantics for What-If,
sampling, reconciliation preview, bulk reconciliation,
and approved execution planning.

Two boundaries, one semantics:

- `plan_file(media_id, ...)` plans one media item/file
- `plan_scope(scope, ...)` plans a directory, subtree,
  or lineage set, preferring minimum safe structural
  operations before per-file actions

Planning is pure with respect to persistence and the
filesystem: it reads observations, metadata snapshots,
and directory listings, and writes nothing. What-If is
presentation over these functions. Real reconciliation
persists the same results through the existing
decision-run/proposal/scope-action transaction.

Determinism: given the same observations, metadata
snapshots, associations, profile, policy/preferences,
and rule versions, planning produces the same result.
Randomness exists only in the sampler (seeded,
seed shown).
"""

import os
import random

from app.metadata_providers.association import (
    detect_conflicts,
    rank_associations,
)
from app.organisation import evidence as evidence_module
from app.organisation.paths import (
    destination_occupied,
    is_within_roots,
    normcase_compare,
    target_is_windows,
)
from app.organisation.preferences import (
    resolve_effective_policy,
)
from app.organisation.profiles import (
    DEFAULT_PROVIDER_PRIORITY,
    PROFILE_TEMPLATE_VERSION as PROFILE_POLICY_VERSION,
    evaluate_tag_mappings,
    normalise_certification,
    profile_digest,
    render_template,
    root_token_fields,
    tag_mapping_rank,
    validate_profile,
)
from app.organisation.rules import (
    CATEGORY_UNCLASSIFIED,
    CategorySuitabilityRules,
    DestinationTemplateRules,
    LibraryClassificationRules,
    MetadataCategoryRules,
    select_library_root,
)


#: Review states (closed set).
REVIEW_READY = "ready"

REVIEW_ALREADY_CORRECT = "already_correct"

REVIEW_NEEDS_REVIEW = "needs-review"

REVIEW_COLLISION = "collision"

REVIEW_CONFLICT = "conflict"

REVIEW_STALE = "stale"

REVIEW_STATES = frozenset(
    {
        REVIEW_READY,
        REVIEW_ALREADY_CORRECT,
        REVIEW_NEEDS_REVIEW,
        REVIEW_COLLISION,
        REVIEW_CONFLICT,
        REVIEW_STALE,
    }
)

#: Mutation strategies (closed set).
STRATEGY_NO_MUTATION = "already correct"

STRATEGY_MOVE_FILE = "move file"

STRATEGY_RENAME_FILE = "rename file"

STRATEGY_COPY_VERIFY_DELETE = "copy, verify, then remove original"

STRATEGY_RENAME_DIRECTORY = "rename directory"

STRATEGY_MOVE_DIRECTORY = "move directory"

STRATEGY_SUBTREE_RELOCATION = "subtree relocation"

STRATEGY_CREATE_DIRECTORY = "create directory"

STRATEGY_REVIEW = "requires review"
STRATEGY_COLLISION = "collision"

STRATEGY_NO_STRUCTURAL = "no safe structural transformation"

#: Scope action types persisted for structural actions.
ACTION_TYPES = (
    "directory_rename",
    "directory_move",
    "subtree_relocation",
    "directory_creation",
    "file_rename",
    "file_move",
    "combination",
    "no_mutation",
)


class FilePlan:
    """
    Deterministic plan for one media item. Plain data;
    JSON-serialisable via `to_dict()`.
    """

    __slots__ = (
        "media_id",
        "current_path",
        "source_observation_id",
        "expected_destination",
        "destination_root",
        "destination_token",
        "template",
        "provider_priority",
        "classification",
        "category",
        "rules_applied",
        "mappings_applied",
        "reasoning",
        "confidence",
        "review_state",
        "provider_review",
        "mutation",
        "metadata_cited",
        "metadata_summary",
        "association",
        "matched_rule",
    )

    def __init__(
        self,
        *,
        media_id,
        current_path=None,
        source_observation_id=None,
        expected_destination=None,
        destination_root=None,
        destination_token=None,
        template=None,
        provider_priority=None,
        classification=None,
        category=None,
        rules_applied=None,
        mappings_applied=None,
        reasoning=None,
        confidence=0.0,
        review_state=REVIEW_NEEDS_REVIEW,
        provider_review=False,
        mutation=None,
        metadata_cited=None,
        metadata_summary=None,
        association=None,
        matched_rule=None,
    ):
        self.media_id = media_id
        self.current_path = current_path
        self.source_observation_id = source_observation_id
        self.expected_destination = expected_destination
        self.destination_root = destination_root
        self.destination_token = destination_token
        self.template = template
        self.provider_priority = provider_priority
        self.classification = classification
        self.category = category
        self.rules_applied = list(rules_applied or [])
        self.mappings_applied = list(mappings_applied or [])
        self.reasoning = list(reasoning or [])
        self.confidence = confidence
        self.review_state = review_state
        self.provider_review = bool(provider_review)
        self.mutation = dict(
            mutation
            or {"strategy": STRATEGY_REVIEW,
                "operation_count": 0}
        )
        self.metadata_cited = dict(
            metadata_cited
            or {"observation_ids": [],
                "fingerprint": None}
        )
        self.metadata_summary = dict(metadata_summary or {})
        self.association = dict(association or {})
        self.matched_rule = (
            dict(matched_rule) if matched_rule else None
        )

    def to_dict(self) -> dict:
        return {
            "media_id": self.media_id,
            "current_path": self.current_path,
            "source_observation_id": self.source_observation_id,
            "expected_destination": self.expected_destination,
            "destination_root": self.destination_root,
            "destination_token": self.destination_token,
            "template": self.template,
            "provider_priority": self.provider_priority,
            "classification": self.classification,
            "category": self.category,
            "rules_applied": list(self.rules_applied),
            "mappings_applied": list(self.mappings_applied),
            "reasoning": list(self.reasoning),
            "confidence": self.confidence,
            "review_state": self.review_state,
            "provider_review": self.provider_review,
            "mutation": dict(self.mutation),
            "metadata_cited": {
                "observation_ids": list(
                    self.metadata_cited.get(
                        "observation_ids", []
                    )
                ),
                "fingerprint": self.metadata_cited.get(
                    "fingerprint"
                ),
            },
            "metadata_summary": dict(
                self.metadata_summary
            ),
            "association": dict(self.association),
            "matched_rule": (
                dict(self.matched_rule)
                if self.matched_rule
                else None
            ),
        }


class StructuralAction:
    """
    One structural (scope-level) action. Plain data;
    JSON-serialisable via `to_dict()`.
    """

    __slots__ = (
        "action_type",
        "source_path",
        "destination_path",
        "descendant_media_ids",
        "descendants",
        "strategy",
        "operation_count",
        "reasoning",
        "review_conditions",
    )

    def __init__(
        self,
        *,
        action_type,
        source_path,
        destination_path,
        descendant_media_ids=None,
        descendants=None,
        strategy="",
        operation_count=1,
        reasoning=None,
        review_conditions=None,
    ):
        self.action_type = action_type
        self.source_path = source_path
        self.destination_path = destination_path
        self.descendant_media_ids = list(
            descendant_media_ids or []
        )
        self.descendants = list(descendants or [])
        self.strategy = strategy
        self.operation_count = operation_count
        self.reasoning = list(reasoning or [])
        self.review_conditions = list(review_conditions or [])

    def to_dict(self) -> dict:
        return {
            "action_type": self.action_type,
            "source_path": self.source_path,
            "destination_path": self.destination_path,
            "descendant_media_ids": list(
                self.descendant_media_ids
            ),
            "descendants": [dict(item) for item in self.descendants],
            "strategy": self.strategy,
            "operation_count": self.operation_count,
            "reasoning": list(self.reasoning),
            "review_conditions": list(
                self.review_conditions
            ),
        }


class ScopePlan:
    """
    Deterministic plan for a scope. Plain data;
    JSON-serialisable via `to_dict()`.
    """

    __slots__ = (
        "scope_path",
        "strategy",
        "operation_count",
        "reasoning",
        "file_plans",
        "structural_actions",
        "review_conditions",
    )

    def __init__(
        self,
        *,
        scope_path,
        strategy=STRATEGY_NO_MUTATION,
        operation_count=0,
        reasoning=None,
        file_plans=None,
        structural_actions=None,
        review_conditions=None,
    ):
        self.scope_path = scope_path
        self.strategy = strategy
        self.operation_count = operation_count
        self.reasoning = list(reasoning or [])
        self.file_plans = list(file_plans or [])
        self.structural_actions = list(
            structural_actions or []
        )
        self.review_conditions = list(
            review_conditions or []
        )

    def to_dict(self) -> dict:
        return {
            "scope_path": self.scope_path,
            "strategy": self.strategy,
            "operation_count": self.operation_count,
            "reasoning": list(self.reasoning),
            "file_plans": [
                plan.to_dict() for plan in self.file_plans
            ],
            "structural_actions": [
                action.to_dict()
                for action in self.structural_actions
            ],
            "review_conditions": list(
                self.review_conditions
            ),
        }


class OrganisationPlanner:
    """
    Shared planning authority for Sprint 15 organisation.

    Constructed with repository reads and an optional
    metadata fetcher. `metadata_fetcher(media_id)` returns
    a list of metadata snapshot payload dicts
    (each with provider, provider_item_id,
    provider_item_kind, association data, and relevant
    metadata fields); it performs no persistence itself.
    Persistence of fetched snapshots is owned by the
    calling service layer, so What-If stays fully
    non-persisting while reconciliation records history.
    """

    def __init__(
        self,
        *,
        media_repository,
        organisation_repository,
        metadata_fetcher=None,
    ):
        self.media_repository = media_repository
        self.organisation_repository = organisation_repository
        self.metadata_fetcher = metadata_fetcher
        self._evidence_builder = (
            evidence_module.OrganisationEvidenceBuilder()
        )

    # ---------------------------------------------------------
    # file-level planning
    # ---------------------------------------------------------

    def plan_ephemeral(
        self,
        scan: dict,
        *,
        profile: dict | None = None,
        preferences=None,
        snapshots: list | None = None,
    ) -> FilePlan:
        """
        Deterministic plan for a previously unknown file
        from a read-only scan record (path, name,
        extension, size_bytes, file_mtime_ns,
        filesystem_device, filesystem_inode). Builds
        in-memory lineage/observation models and reuses
        the shared _plan_from_evidence, so ephemeral
        plans can never disagree with lineage plans.
        Persists nothing; media_id 0 marks "no stored
        lineage" (no DB row is read or written).
        """

        from app.models.file_observation import (
            FileObservation,
        )
        from app.models.observation_history import (
            MediaLineage,
        )

        profile = dict(profile or {})
        scan = dict(scan or {})

        path = str(scan.get("path") or "")

        if not path:
            raise ValueError(
                "ephemeral planning needs a file path"
            )

        name = scan.get("name") or os.path.basename(path)

        lineage = MediaLineage(
            id=0,
            file_path=path,
            file_name=name,
            status="active",
            file_size_bytes=scan.get("size_bytes"),
            file_mtime_ns=scan.get("file_mtime_ns"),
        )

        observation = FileObservation(
            id=0,
            media_id=0,
            file_path=path,
            file_name=name,
            file_extension=scan.get("extension"),
            size_bytes=scan.get("size_bytes"),
            file_mtime_ns=scan.get("file_mtime_ns"),
            filesystem_device=scan.get("filesystem_device"),
            filesystem_inode=scan.get("filesystem_inode"),
            identity_match_method="ephemeral-scan",
            identity_evidence={},
        )

        try:
            evidence = self._evidence_builder.build(
                lineage,
                [observation],
                metadata_domains=(
                    tuple(preferences.metadata_domains)
                    if preferences is not None
                    else None
                ),
            )
        except ValueError as error:
            return FilePlan(
                media_id=0,
                current_path=path,
                reasoning=[f"{error}; review required"],
            )

        return self._plan_from_evidence(
            0,
            evidence,
            list(snapshots or []),
            profile,
            preferences,
        )

    def plan_file(
        self,
        media_id: int,
        *,
        profile: dict | None = None,
        preferences=None,
        metadata_scope: str | dict = "cached",
    ) -> FilePlan:
        """
        Deterministic plan for one media item. Reads
        observations and metadata snapshots; writes
        nothing; mutates nothing.
        """

        profile = dict(profile or {})

        lineage = self.media_repository.get_media_item(
            media_id
        )

        if lineage is None:
            raise ValueError(
                f"media lineage {media_id} not found"
            )

        observations = (
            self.media_repository.get_file_observations(
                media_id
            )
        )

        if not observations:
            return FilePlan(
                media_id=media_id,
            provider_priority=None,
                reasoning=[
                    "lineage has no filesystem "
                    "observation; review required",
                ],
            )

        try:
            evidence = self._evidence_builder.build(
                lineage,
                observations,
                metadata_domains=(
                    tuple(preferences.metadata_domains)
                    if preferences is not None
                    else None
                ),
            )
        except ValueError as error:
            return FilePlan(
                media_id=media_id,
            provider_priority=None,
                reasoning=[f"{error}; review required"],
            )

        snapshots = self._metadata_snapshots(
            media_id, metadata_scope
        )

        if snapshots is None:
            return FilePlan(
                media_id=media_id,
            provider_priority=None,
                current_path=evidence.path,
                source_observation_id=evidence.observation_id,
                reasoning=[
                    "live provider metadata requested but "
                    "no metadata fetcher is configured; "
                    "review required",
                ],
            )

        return self._plan_from_evidence(
            media_id,
            evidence,
            snapshots,
            profile,
            preferences,
        )

    def _plan_from_evidence(
        self,
        media_id,
        evidence,
        snapshots,
        profile,
        preferences,
    ):
        """
        Shared deterministic file-plan computation over
        ready evidence and metadata snapshots. Used by
        both lineage planning (plan_file) and ephemeral
        unseen-file planning (plan_ephemeral) so the
        two can never disagree. Pure; writes nothing.
        """

        candidates = _association_candidates(snapshots)

        ranked = rank_associations(evidence.path, candidates)

        conflicts = detect_conflicts(ranked)

        association = (
            {
                "strength": ranked[0]["strength"],
                "basis": ranked[0]["basis"],
                "provider": ranked[0]["provider"],
                "provider_item_id": ranked[0][
                    "provider_item_id"
                ],
            }
            if ranked
            else {}
        )

        observation_ids = sorted(
            {
                snapshot.get("observation_id")
                for snapshot in snapshots
                if snapshot.get("observation_id") is not None
            }
        )

        fingerprint = (
            self.organisation_repository
            .metadata_fingerprint(
                {
                    str(snapshot.get("provider")): (
                        snapshot.get("relevant") or {}
                    )
                    for snapshot in snapshots
                }
            )
            if snapshots
            else None
        )

        reasoning = []
        rules_applied = []
        mappings_applied = []
        confidence = 0.0
        review_state = REVIEW_READY
        category = None
        category_source = None
        classification = None
        matched_rule = None

        # Merged human-readable metadata summary, computed
        # once here so every FilePlan below can cite it.
        # First source wins per field (deterministic
        # provider order); tags union by provider.
        provider_priority = list(
            profile.get("provider_priority")
            or DEFAULT_PROVIDER_PRIORITY
        )

        merged_metadata = _merge_metadata(
            snapshots,
            priority=provider_priority,
        )

        if conflicts:
            return FilePlan(
                media_id=media_id,
            provider_priority=provider_priority,
                current_path=evidence.path,
                source_observation_id=evidence.observation_id,
                reasoning=[
                    f"conflicting association: {conflicts[0]}; "
                    f"review required",
                ],
                review_state=REVIEW_CONFLICT,
                metadata_cited={
                    "observation_ids": observation_ids,
                    "fingerprint": fingerprint,
                },
                association=association,
                metadata_summary=merged_metadata,
                matched_rule=matched_rule,
                )

        if ranked and ranked[0]["strength"] in (
            "fuzzy_ambiguous",
        ):
            return FilePlan(
                media_id=media_id,
            provider_priority=provider_priority,
                current_path=evidence.path,
                source_observation_id=evidence.observation_id,
                reasoning=[
                    "association is ambiguous (weak match "
                    "only); review required",
                ],
                review_state=REVIEW_CONFLICT,
                metadata_cited={
                    "observation_ids": observation_ids,
                    "fingerprint": fingerprint,
                },
                association=association,
                metadata_summary=merged_metadata,
                matched_rule=matched_rule,
                )

        # Base classification from local evidence (existing
        # semantics, always available).
        base = (
            evidence_module.LibraryClassificationRules
            if hasattr(evidence_module,
                       "LibraryClassificationRules")
            else None
        )

        if base is None:
            from app.organisation.rules import (
                LibraryClassificationRules as _Base,
            )
            base = _Base

        local = base.classify(
            file_name=evidence.name,
            path_segments=evidence.path_segments,
        )

        classification = local.category
        confidence = local.confidence
        reasoning.extend(local.reasoning)
        rules_applied.append(
            f"{base.name}@{base.semantic_version}"
        )

        # Local category stands unless metadata-aware
        # intelligence supersedes it. Metadata yielding
        # no decision never erases filename evidence.
        if local.category not in (None, "", CATEGORY_UNCLASSIFIED):
            category = local.category
            category_source = "local"

        # Metadata-aware classification when provider
        # metadata is present (merged summary is computed
        # once above and cited by every FilePlan below).
        #
        # Deterministic classification precedence
        # (documented product rule):
        #
        #   0. unified organisation rules (explicit,
        #      non-fallback entries, top to bottom)
        #   1. explicit certification/rating policy
        #   2. explicit collection policy
        #   3. intelligent metadata signals (only when no
        #      explicit policy matched)
        #   4. explicit provider tag rules, where a
        #      generic single-label tag never silently
        #      outranks a certification/collection
        #      decision but a more specific multi-label
        #      rule (e.g. Kids + Anime) explicitly
        #      refines it
        #   5. unified fallback rules (top to bottom)
        #   6. baseline local Movie/TV classification
        #
        # Original provider certification values stay as
        # provenance in the merged summary; matching
        # uses the normalised form.

        categories = dict(profile.get("categories") or {})

        local_kind = (
            "movie"
            if local.category == "movies"
            else (
                "tv"
                if local.category == "tv"
                else None
            )
        )

        combined_tags, tags_by_provider = _combined_tag_sets(
            snapshots
        )

        unified_rules = list(
            profile.get("organisation_rules") or []
        )

        unified_hit = _match_unified_rule(
            [
                rule for rule in unified_rules
                if not (
                    isinstance(rule, dict)
                    and rule.get("fallback")
                )
            ],
            local_kind,
            merged_metadata,
            combined_tags,
            tags_by_provider,
        )

        if unified_hit is not None:
            from app.organisation.profiles import (
                describe_rule,
            )

            classification = (
                f"rule:{unified_hit['category']}"
            )
            category = unified_hit["category"]
            category_source = "rule"
            confidence = max(confidence, 0.85)
            matched_rule = {
                "id": unified_hit.get("id"),
                "description": describe_rule(unified_hit),
                "category": unified_hit.get("category"),
                "fallback": False,
            }
            reasoning.append(
                f"organisation rule "
                f"'{unified_hit.get('id')}' matched "
                f"({matched_rule['description']})"
            )
            rules_applied.append(
                "organisation_rules@"
                f"{PROFILE_POLICY_VERSION}"
            )

            # An operator-explicit legacy override
            # outranks even a matching preset rule:
            # the override flag is the deliberate
            # "this Advanced rule must win" signal.
            # Ordinary (non-override) legacy mappings
            # never contend with a unified match.
            override_check = self._evaluate_mappings(
                profile, snapshots
            )

            if override_check["outcome"] == "conflict":
                return FilePlan(
                    media_id=media_id,
                    provider_priority=provider_priority,
                    current_path=evidence.path,
                    source_observation_id=(
                        evidence.observation_id
                    ),
                    classification=classification,
                    category=category,
                    rules_applied=rules_applied,
                    reasoning=reasoning
                    + [override_check["reason"]],
                    confidence=confidence,
                    review_state=REVIEW_CONFLICT,
                    metadata_cited={
                        "observation_ids": observation_ids,
                        "fingerprint": fingerprint,
                    },
                    association=association,
                    metadata_summary=merged_metadata,
                )

            if override_check["outcome"] == "match":
                winner = override_check["mapping"]

                if (
                    winner.get("override_policy")
                    and winner.get("category") != category
                ):
                    category = winner.get("category")
                    category_source = "tagmap"
                    matched_rule = (
                        _legacy_rule_description(
                            "tagmap", winner, category,
                            merged_metadata,
                        )
                    )
                    mappings_applied.append(
                        f"tagmap:"
                        f"{winner.get('provider') or '*'}:"
                        f"{','.join(sorted(winner.get('labels') or []))}"
                        f"@{winner.get('id')}"
                    )
                    reasoning.append(
                        f"explicit tag mapping "
                        f"'{winner.get('id')}' matched for "
                        f"category '{category}'; explicit "
                        f"policy override outranks the "
                        f"preset rule by operator choice"
                    )

        # Legacy policy tiers run only when no unified
        # organisation rule matched: explicit ordered
        # rules outrank the separate legacy lists.
        if unified_hit is None:
            cert_hit = _evaluate_certification_policy(
                profile.get("certification_rules"),
                merged_metadata,
                local_kind,
            )

            if cert_hit["outcome"] == "conflict":
                return FilePlan(
                    media_id=media_id,
                provider_priority=provider_priority,
                    current_path=evidence.path,
                    source_observation_id=evidence.observation_id,
                    classification=classification,
                    category=category,
                    rules_applied=rules_applied,
                    reasoning=reasoning
                    + [cert_hit["reason"]],
                    confidence=confidence,
                    review_state=REVIEW_CONFLICT,
                    metadata_cited={
                        "observation_ids": observation_ids,
                        "fingerprint": fingerprint,
                    },
                    association=association,
                    metadata_summary=merged_metadata,
                )

            if cert_hit["outcome"] == "match":
                classification = (
                    f"certification:{cert_hit['category']}"
                )
                category = cert_hit["category"]
                category_source = "certification"
                matched_rule = _legacy_rule_description(
                    "certification",
                    cert_hit.get("rule"),
                    cert_hit["category"],
                    merged_metadata,
                )
                confidence = max(confidence, 0.85)
                reasoning.append(cert_hit["reason"])
                rules_applied.append(
                    "certification_policy@"
                    f"{PROFILE_POLICY_VERSION}"
                )

            coll_hit = _evaluate_collection_policy(
                profile.get("collection_rules"),
                merged_metadata,
            )

            if coll_hit["outcome"] == "conflict":
                return FilePlan(
                    media_id=media_id,
                provider_priority=provider_priority,
                    current_path=evidence.path,
                    source_observation_id=evidence.observation_id,
                    classification=classification,
                    category=category,
                    rules_applied=rules_applied,
                    reasoning=reasoning
                    + [coll_hit["reason"]],
                    confidence=confidence,
                    review_state=REVIEW_CONFLICT,
                    metadata_cited={
                        "observation_ids": observation_ids,
                        "fingerprint": fingerprint,
                    },
                    association=association,
                    metadata_summary=merged_metadata,
                )

            if (
                coll_hit["outcome"] == "match"
                and category_source != "certification"
            ):
                classification = (
                    f"collection:{coll_hit['category']}"
                )
                category = coll_hit["category"]
                category_source = "collection"
                matched_rule = _legacy_rule_description(
                    "collection",
                    coll_hit.get("rule"),
                    coll_hit["category"],
                    merged_metadata,
                )
                confidence = max(confidence, 0.8)
                reasoning.append(coll_hit["reason"])
                rules_applied.append(
                    "collection_policy@"
                    f"{PROFILE_POLICY_VERSION}"
                )
            elif coll_hit["outcome"] == "match":
                reasoning.append(
                    coll_hit["reason"]
                    + "; certification policy takes "
                    "precedence for the category decision"
                )

            if (
                merged_metadata
                and categories
                and category_source not in (
                    "certification",
                    "collection",
                )
            ):
                from app.organisation.rules import (
                    MetadataCategoryRules,
                )

                decision = MetadataCategoryRules.classify(
                    metadata=merged_metadata,
                    categories=categories,
                    category_signals=dict(
                        profile.get("intelligent_rules") or {}
                    ),
                )

                rules_applied.append(
                    f"{MetadataCategoryRules.name}@"
                    f"{MetadataCategoryRules.semantic_version}"
                )

                if decision.category is not None:
                    classification = (
                        f"metadata:{decision.category}"
                    )
                    category = decision.category
                    category_source = "metadata"
                    confidence = max(
                        confidence, decision.confidence
                    )
                    reasoning.extend(decision.reasoning)
                else:
                    reasoning.extend(decision.reasoning)

            # Explicit tag mappings (policy, not intelligence).
            tag_hits = self._evaluate_mappings(
                profile, snapshots
            )

            if tag_hits["outcome"] == "conflict":
                return FilePlan(
                    media_id=media_id,
                provider_priority=provider_priority,
                    current_path=evidence.path,
                    source_observation_id=evidence.observation_id,
                    classification=classification,
                    category=category,
                    rules_applied=rules_applied,
                    reasoning=reasoning
                    + [tag_hits["reason"]],
                    confidence=confidence,
                    review_state=REVIEW_CONFLICT,
                    metadata_cited={
                        "observation_ids": observation_ids,
                        "fingerprint": fingerprint,
                    },
                    association=association,
                    metadata_summary=merged_metadata,
                    )

            if tag_hits["outcome"] == "match":
                mapping = tag_hits["mapping"]
                labels = list(mapping.get("labels") or [])
                explicit_override = bool(
                    mapping.get("override_policy")
                )

                if category_source in (
                    "certification",
                    "collection",
                ) and mapping.get("category") != category:
                    # A generic single-label tag never
                    # silently outranks the explicit
                    # certification/collection routing; a
                    # deliberate multi-label rule refines it,
                    # and a rule the operator explicitly
                    # marked as a policy override wins
                    # deterministically (shown as such in
                    # the editor and the reason below).
                    prior_source = category_source

                    if explicit_override or len(labels) >= 2:
                        category = mapping.get("category")
                        category_source = "tagmap"
                        matched_rule = _legacy_rule_description(
                            "tagmap", mapping, category,
                            merged_metadata,
                        )
                        mappings_applied.append(
                            f"tagmap:{mapping.get('provider') or '*'}:"
                            f"{','.join(sorted(labels))}"
                            f"@{mapping.get('id')}"
                        )
                        if explicit_override:
                            reasoning.append(
                                tag_hits["reason"]
                                + f"; explicit policy override "
                                f"'{mapping.get('id')}' "
                                f"outranks the "
                                f"{prior_source} baseline "
                                f"decision by operator choice"
                            )
                        else:
                            reasoning.append(
                                tag_hits["reason"]
                                + f"; explicit multi-label rule "
                                f"'{mapping.get('id')}' refines "
                                f"the {prior_source} "
                                f"baseline decision"
                            )
                    else:
                        mappings_applied.append(
                            f"tagmap:{mapping.get('provider') or '*'}:"
                            f"{','.join(sorted(labels))}"
                            f"@{mapping.get('id')}"
                        )
                        reasoning.append(
                            tag_hits["reason"]
                            + f"; generic tag rule "
                            f"'{mapping.get('id')}' does not "
                            f"outrank the explicit "
                            f"{category_source} policy "
                            f"(category stays '{category}')"
                        )
                else:
                    category = mapping.get("category")
                    category_source = "tagmap"
                    matched_rule = _legacy_rule_description(
                        "tagmap", mapping, category,
                        merged_metadata,
                    )
                    mappings_applied.append(
                        f"tagmap:{mapping.get('provider') or '*'}:"
                        f"{','.join(sorted(labels))}"
                        f"@{mapping.get('id')}"
                    )
                    reasoning.append(tag_hits["reason"])
        # Baseline local Movie/TV classification renders
        # through the plain Movie or TV template below.
        # A baseline category never forces the generic
        # Category template: only an explicit policy
        # (certification, collection, signals, tags)
        # selecting a configured category routes there.
        # Local TV keeps the TV template in particular
        # because only it carries Season structure.

        # Unified fallback rules: the preset's
        # safety net below the legacy tiers. When one
        # matches, the standard-destination reason
        # applies (§29 What-If wording).
        if unified_hit is None and category_source in (
            None, "local",
        ):
            fallback_hit = _match_unified_rule(
                [
                    rule
                    for rule in unified_rules
                    if isinstance(rule, dict)
                    and rule.get("fallback")
                ],
                local_kind,
                merged_metadata,
                combined_tags,
                tags_by_provider,
            )

            if fallback_hit is not None:
                from app.organisation.profiles import (
                    describe_rule,
                )

                kind_word = (
                    "Movie"
                    if local_kind == "movie"
                    else (
                        "TV" if local_kind == "tv" else "media"
                    )
                )
                classification = (
                    f"rule:{fallback_hit['category']}"
                )
                category = fallback_hit["category"]
                category_source = "fallback"
                confidence = max(confidence, 0.7)
                matched_rule = {
                    "id": fallback_hit.get("id"),
                    "description": describe_rule(
                        fallback_hit
                    ),
                    "category": fallback_hit.get("category"),
                    "fallback": True,
                }
                reasoning.append(
                    f"organisation rule "
                    f"'{fallback_hit.get('id')}' matched "
                    f"({matched_rule['description']}); no "
                    f"specialised category evidence "
                    f"matched, so the profile's standard "
                    f"{kind_word} destination was used"
                )
                rules_applied.append(
                    "organisation_rules@"
                    f"{PROFILE_POLICY_VERSION}"
                )

        if category_source == "local" and local_kind in (
            "movie",
            "tv",
        ):
            kind_word = (
                "Movie" if local_kind == "movie" else "TV"
            )
            reasoning.append(
                f"no specialised category evidence "
                f"matched, so the profile's standard "
                f"{kind_word} destination was used"
            )

        # Suitability verdicts for safety-sensitive
        # categories configured on the profile.
        for check in self._suitability_checks(
            profile, merged_metadata, category
        ):
            reasoning.append(check["reason"])
            rules_applied.append(check["rule"])
            if check["verdict"] in (
                "incompatible", "conflicting-evidence"
            ):
                return FilePlan(
                    media_id=media_id,
            provider_priority=provider_priority,
                    current_path=evidence.path,
                    source_observation_id=evidence.observation_id,
                    classification=classification,
                    category=category,
                    rules_applied=rules_applied,
                    mappings_applied=mappings_applied,
                    reasoning=reasoning,
                    confidence=confidence,
                    review_state=REVIEW_CONFLICT,
                    metadata_cited={
                        "observation_ids": observation_ids,
                        "fingerprint": fingerprint,
                    },
                    association=association,
                    metadata_summary=merged_metadata,
                    )
            if check["verdict"] == "insufficient-evidence":
                review_state = REVIEW_NEEDS_REVIEW

        # Destination calculation (merged metadata
        # feeds template values and filenames so
        # reliable provider titles win over
        # release-filename text).
        destination, dest_reason, dest_template = self._destination(
            profile,
            evidence,
            category,
            classification,
            category_source,
            merged_metadata,
            local_kind=local_kind,
        )

        if destination is None:
            return FilePlan(
                media_id=media_id,
            provider_priority=provider_priority,
                current_path=evidence.path,
                source_observation_id=evidence.observation_id,
                classification=classification,
                category=category,
                rules_applied=rules_applied,
                mappings_applied=mappings_applied,
                reasoning=reasoning + [dest_reason],
                confidence=confidence,
                review_state=REVIEW_NEEDS_REVIEW,
                metadata_cited={
                    "observation_ids": observation_ids,
                    "fingerprint": fingerprint,
                },
                association=association,
                metadata_summary=merged_metadata,
                matched_rule=matched_rule,
                )

        reasoning.append(dest_reason)

        dest_token, dest_root = resolve_destination_root(
            profile.get("roots"), destination
        )

        # Placement comparison.
        if _same_path(evidence.path, destination):
            return FilePlan(
                media_id=media_id,
            provider_priority=provider_priority,
                current_path=evidence.path,
                source_observation_id=evidence.observation_id,
                expected_destination=destination,
                destination_root=dest_root,
                destination_token=dest_token,
                template=dest_template,
                classification=classification,
                category=category,
                rules_applied=rules_applied,
                mappings_applied=mappings_applied,
                reasoning=reasoning,
                confidence=confidence,
                review_state=REVIEW_ALREADY_CORRECT,
                mutation={
                    "strategy": STRATEGY_NO_MUTATION,
                    "operation_count": 0,
                },
                metadata_cited={
                    "observation_ids": observation_ids,
                    "fingerprint": fingerprint,
                },
                association=association,
                metadata_summary=merged_metadata,
                matched_rule=matched_rule,
                )

        # Collision probe (read-only).
        if destination_occupied(destination):
            owned = self._owned_by_other_lineage(
                media_id, destination
            )
            return FilePlan(
                media_id=media_id,
            provider_priority=provider_priority,
                current_path=evidence.path,
                source_observation_id=evidence.observation_id,
                expected_destination=destination,
                destination_root=dest_root,
                destination_token=dest_token,
                template=dest_template,
                classification=classification,
                category=category,
                rules_applied=rules_applied,
                mappings_applied=mappings_applied,
                reasoning=reasoning
                + [
                    "destination is occupied: "
                    f"{destination}"
                    + (
                        f" by media lineage {owned}"
                        if owned
                        else ""
                    )
                    + "; review required",
                ],
                confidence=confidence,
                review_state=REVIEW_COLLISION,
                mutation={
                    "strategy": STRATEGY_COLLISION,
                    "operation_count": 0,
                },
                metadata_cited={
                    "observation_ids": observation_ids,
                    "fingerprint": fingerprint,
                },
                association=association,
                metadata_summary=merged_metadata,
                matched_rule=matched_rule,
                )

        # Provider-managed path review. Overlap never
        # blocks planning silently: the file stays
        # actionable, but carries an explicit review
        # condition that scope approval must cover.
        # Per-file execution outside an approved scope
        # action refuses provider-overlapping moves.
        provider_review = False

        provider_hit = self._provider_managed_hit(
            evidence.path, destination, snapshots
        )

        if provider_hit is not None:
            provider_review = True
            reasoning.append(provider_hit)

        strategy = (
            STRATEGY_RENAME_FILE
            if os.path.dirname(
                os.path.abspath(evidence.path or "")
            )
            == os.path.dirname(os.path.abspath(destination))
            else STRATEGY_MOVE_FILE
        )

        if strategy == STRATEGY_MOVE_FILE and _is_cross_device(
            evidence.path, destination
        ):
            strategy = STRATEGY_COPY_VERIFY_DELETE
            reasoning.append(
                "source and destination live on different "
                "filesystems; execution must copy, verify "
                "the destination, and only then remove the "
                "original (never a bare rename)"
            )

        return FilePlan(
            media_id=media_id,
            provider_priority=provider_priority,
            current_path=evidence.path,
            source_observation_id=evidence.observation_id,
            expected_destination=destination,
            destination_root=dest_root,
            destination_token=dest_token,
            template=dest_template,
            classification=classification,
            category=category,
            rules_applied=rules_applied,
            mappings_applied=mappings_applied,
            reasoning=reasoning,
            confidence=confidence,
            review_state=review_state,
            provider_review=provider_review,
            mutation={
                "strategy": strategy,
                "operation_count": 1,
            },
            metadata_cited={
                "observation_ids": observation_ids,
                "fingerprint": fingerprint,
            },
            association=association,
            metadata_summary=merged_metadata,
            matched_rule=matched_rule,
        )

    # ---------------------------------------------------------
    # scope-level planning
    # ---------------------------------------------------------

    def plan_scope(
        self,
        scope,
        *,
        profile: dict | None = None,
        preferences=None,
        metadata_scope: str | dict = "cached",
    ) -> ScopePlan:
        """
        Deterministic plan for a directory, subtree, or
        explicit lineage set. Structural operations are
        preferred where they safely achieve the desired
        state; otherwise per-file actions are emitted
        with the reason recorded.
        """

        profile = dict(profile or {})

        if isinstance(scope, dict):
            scope_path = scope.get("path", "")
            lineage_ids = list(scope.get("media_ids") or [])
        else:
            scope_path = str(scope or "")
            lineage_ids = []

        if not lineage_ids and not scope_path:
            return ScopePlan(
                scope_path=scope_path,
                strategy=STRATEGY_REVIEW,
                operation_count=0,
                reasoning=["empty scope; nothing to plan"],
                file_plans=[],
            )

        if not lineage_ids and scope_path:
            lineage_ids = self._lineages_under(scope_path)

        file_plans = []

        for media_id in sorted(set(lineage_ids)):
            try:
                file_plans.append(
                    self.plan_file(
                        media_id,
                        profile=profile,
                        preferences=preferences,
                        metadata_scope=metadata_scope,
                    )
                )
            except ValueError as error:
                file_plans.append(
                    FilePlan(
                        media_id=media_id,
            provider_priority=None,
                        reasoning=[
                            f"{error}; review required",
                        ],
                    )
                )

        actionable = [
            plan for plan in file_plans
            if plan.review_state == REVIEW_READY
        ]

        if not actionable:
            states = sorted(
                {plan.review_state for plan in file_plans}
            )
            return ScopePlan(
                scope_path=scope_path,
                strategy=(
                    STRATEGY_NO_MUTATION
                    if states == [REVIEW_ALREADY_CORRECT]
                    else STRATEGY_REVIEW
                ),
                operation_count=0,
                reasoning=[
                    "no actionable file plans in scope; "
                    f"states present: "
                    f"{', '.join(states) or 'none'}",
                ],
                file_plans=file_plans,
            )

        structural = self._structural_action(
            scope_path,
            actionable,
            profile,
            preferences,
        )

        if structural is not None:
            return ScopePlan(
                scope_path=scope_path,
                strategy=structural.strategy,
                operation_count=structural.operation_count,
                reasoning=structural.reasoning,
                file_plans=file_plans,
                structural_actions=[structural],
                review_conditions=list(
                    structural.review_conditions
                ),
            )

        reasons = [
            "no safe structural transformation covers "
            "the scope; falling back to individual "
            "file operations",
        ]

        conditions = []

        for plan in file_plans:
            if plan.provider_review:
                conditions.append(
                    {
                        "kind": "provider-managed-path",
                        "detail": (
                            f"media {plan.media_id} path "
                            f"overlaps a provider-managed "
                            f"location; per-file approval "
                            f"covers this reviewed impact"
                        ),
                    }
                )

        conditions = sorted(
            conditions, key=lambda item: item["detail"]
        )

        return ScopePlan(
            scope_path=scope_path,
            strategy="per-file operations",
            operation_count=sum(
                plan.mutation.get("operation_count", 1)
                for plan in actionable
            ),
            reasoning=reasons,
            file_plans=file_plans,
            review_conditions=conditions,
        )

    def _structural_action(
        self,
        scope_path: str,
        actionable: list,
        profile: dict,
        preferences,
    ) -> StructuralAction | None:
        """
        Attempt one structural operation covering every
        actionable file plan. Finds the deepest common
        (source ancestor, destination ancestor) pair for
        which every file preserves its relative path, so
        a whole subtree can move with one operation. The
        source ancestor must stay at or below the
        selected scope directory. All of these must hold:
        common ancestor pair, preserved relative
        structure, no foreign files in the source tree,
        destination absent, same filesystem, destination
        inside configured roots, no collisions.
        Provider overlap becomes a recorded review
        condition, never a silent pass.
        """

        pairs = []

        for plan in actionable:
            if not plan.current_path or not (
                plan.expected_destination
            ):
                return None

            pairs.append(
                (
                    os.path.abspath(plan.current_path),
                    os.path.abspath(
                        plan.expected_destination
                    ),
                )
            )

        try:
            scope_anchor = (
                os.path.abspath(scope_path)
                if scope_path and scope_path.strip()
                else None
            )
        except (OSError, ValueError):
            scope_anchor = None

        match = _common_ancestor_pair(pairs, scope_anchor)

        if match is None:
            return None

        source_dir, dest_dir = match

        if _same_path(source_dir, dest_dir):
            return None

        # No foreign files: everything under the source
        # tree must belong to covered NAMOA lineages.
        known = set()
        for plan in actionable:
            known.add(
                normcase_compare(plan.current_path or "")
            )

        try:
            for root, _dirs, files in os.walk(source_dir):
                for name in files:
                    candidate = normcase_compare(
                        os.path.join(root, name)
                    )
                    if candidate not in known:
                        return None
        except OSError:
            return None

        # Same-filesystem requirement: a cross-device
        # rename is never a simple rename.
        try:
            parent = os.path.dirname(dest_dir)
            same_device = (
                os.stat(source_dir).st_dev
                == os.stat(
                    parent if os.path.exists(parent)
                    else source_dir
                ).st_dev
            )
        except OSError:
            return None

        if not same_device:
            return None

        # Destination must be absent (rename/move).
        try:
            dest_exists = os.path.lexists(dest_dir)
        except (OSError, ValueError):
            return None

        if dest_exists:
            return None

        # Destination parent must stay inside the
        # configured roots.
        roots = list(profile.get("roots") or [])

        if roots:
            from app.organisation.paths import (
                is_within_roots,
            )

            if not is_within_roots(dest_dir, roots):
                return None

        # Shared parent means rename, otherwise move.
        if os.path.dirname(
            source_dir
        ) == os.path.dirname(dest_dir):
            action_type = "directory_rename"
            strategy = STRATEGY_RENAME_DIRECTORY
        else:
            action_type = "directory_move"
            strategy = STRATEGY_MOVE_DIRECTORY

        descendant_ids = sorted(
            plan.media_id for plan in actionable
        )

        review_conditions = []

        for plan in actionable:
            if plan.provider_review:
                review_conditions.append(
                    {
                        "kind": "provider-managed-path",
                        "detail": (
                            f"media {plan.media_id} path "
                            f"overlaps a provider-managed "
                            f"location; scope approval "
                            f"covers this reviewed impact"
                        ),
                    }
                )

        review_conditions = sorted(
            review_conditions,
            key=lambda item: item["detail"],
        )

        descendants = []

        for plan in sorted(
            actionable, key=lambda item: item.media_id
        ):
            relative = os.path.relpath(
                os.path.abspath(plan.current_path),
                source_dir,
            )

            try:
                stat = os.stat(plan.current_path)
            except OSError:
                return None

            descendants.append(
                {
                    "media_id": plan.media_id,
                    "relative_path": relative,
                    "size_bytes": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "source_observation_id": (
                        plan.source_observation_id
                    ),
                }
            )

        return StructuralAction(
            action_type=action_type,
            source_path=os.path.abspath(source_dir),
            destination_path=os.path.abspath(dest_dir),
            descendant_media_ids=descendant_ids,
            descendants=descendants,
            strategy=strategy,
            operation_count=1,
            reasoning=[
                f"{strategy} resolves "
                f"{len(descendant_ids)} descendant path "
                f"differences in one filesystem operation",
                "relative structure preserved for every "
                "covered file; no foreign files in the "
                "source tree; destination absent; same "
                "filesystem",
            ],
            review_conditions=review_conditions,
        )

    # ---------------------------------------------------------
    # directory sampling
    # ---------------------------------------------------------

    def sample_directory(
        self,
        directory: str,
        *,
        limit: int = 10,
        seed: int | None = None,
    ) -> dict:
        """
        Thin deterministic sampler: list eligible files
        under a directory and uniformly sample up to
        `limit`. Eligible means a supported video file
        (the scanner's video definition) that is a
        regular file and not a symlink. Anything else
        is outside the sampler scope entirely: never
        listed, counted, analysed, or reported.
        Returns the seed used so "Test Again" (a
        fresh seed) is reproducible. Reads the
        directory listing only; never mutates.
        """

        from app.scanner.scanner import is_video_file
        from pathlib import Path as _Path

        if seed is None:
            seed = random.SystemRandom().randint(0, 2 ** 31)

        if not os.path.isdir(directory):
            return {
                "seed": seed,
                "directory": directory,
                "eligible_count": 0,
                "sampled_paths": [],
                "error": (
                    f"directory does not exist or is not "
                    f"accessible: {directory}"
                ),
            }

        eligible = []

        try:
            for root, _dirs, files in os.walk(directory):
                for name in sorted(files):
                    candidate = os.path.join(root, name)
                    try:
                        if (
                            os.path.isfile(candidate)
                            and not os.path.islink(candidate)
                            and is_video_file(
                                _Path(candidate)
                            )
                        ):
                            eligible.append(candidate)
                    except OSError:
                        continue
        except OSError as error:
            return {
                "seed": seed,
                "directory": directory,
                "eligible_count": 0,
                "sampled_paths": [],
                "error": f"unable to read directory: {error}",
            }

        eligible = sorted(set(eligible))

        rng = random.Random(seed)

        if len(eligible) <= max(int(limit), 0):
            sampled = list(eligible)
        else:
            sampled = rng.sample(eligible, int(limit))

        return {
            "seed": seed,
            "directory": directory,
            "eligible_count": len(eligible),
            "sampled_paths": sorted(sampled),
            "error": None,
        }

    # ---------------------------------------------------------
    # preflight
    # ---------------------------------------------------------

    def preflight(
        self,
        profile: dict,
        *,
        roots: list | None = None,
        provider_paths: list | None = None,
    ) -> dict:
        """
        Advisory validation-only preflight over the
        configured organisation setup. Access-bit and
        containment inspection only; creates no probe
        artifacts. Execution-time validation remains
        authoritative.
        """

        profile = dict(profile or {})

        problems = validate_profile(profile)

        checks = []

        if problems:
            checks.append(
                {
                    "name": "profile configuration valid",
                    "ok": False,
                    "level": "error",
                    "message": "; ".join(problems),
                }
            )
        else:
            checks.append(
                {
                    "name": "profile configuration valid",
                    "ok": True,
                    "level": "error",
                    "message": "profile configuration is valid",
                }
            )

        roots = (
            list(roots)
            if roots is not None
            else list(profile.get("roots") or [])
        )

        from app.organisation.profiles import (
            assign_root_aliases as _assign_aliases,
        )

        assigned_roots, _alias_problems = _assign_aliases(
            roots
        )
        root_paths = [
            path for path, _alias in assigned_roots
            if isinstance(path, str) and path
        ]

        if not roots:
            checks.append(
                {
                    "name": "organisation roots configured",
                    "ok": False,
                    "level": "error",
                    "message": (
                        "no organisation roots configured; "
                        "browse to a directory and add it "
                        "as a root"
                    ),
                }
            )
        else:
            all_patterns = "".join(
                str(
                    (template or {}).get("pattern") or ""
                )
                for template in (
                    profile.get("templates") or {}
                ).values()
                if isinstance(template, dict)
            )

            for path, alias in assigned_roots:
                if alias and f"{{{alias}}}" not in all_patterns:
                    checks.append(
                        {
                            "name": (
                                f"root tag {{{alias}}} unused"
                            ),
                            "ok": True,
                            "level": "warning",
                            "message": (
                                f"library root {path or '?'} "
                                f"({{{alias}}}) is not "
                                f"referenced by any template "
                                f"pattern; it receives "
                                f"nothing until a pattern "
                                f"uses its tag"
                            ),
                        }
                    )

            for root in root_paths:
                if not os.path.isabs(root):
                    checks.append(
                        {
                            "name": f"root configured: {root}",
                            "ok": False,
                            "level": "error",
                            "message": (
                                f"organisation root must be "
                                f"absolute: {root}"
                            ),
                        }
                    )
                    continue

                if not os.path.isdir(root):
                    checks.append(
                        {
                            "name": f"root readable: {root}",
                            "ok": False,
                            "level": "error",
                            "message": (
                                f"Unable to read directory:\n{root}"
                            ),
                        }
                    )
                    continue

                if not (
                    os.access(root, os.R_OK | os.X_OK)
                ):
                    checks.append(
                        {
                            "name": f"root readable: {root}",
                            "ok": False,
                            "level": "error",
                            "message": (
                                f"Unable to read directory:\n{root}"
                            ),
                        }
                    )
                    continue

                checks.append(
                    {
                        "name": f"root readable: {root}",
                        "ok": True,
                        "level": "error",
                        "message": f"root is readable: {root}",
                    }
                )

                parent = root

                if os.path.isdir(parent) and not os.access(
                    parent, os.W_OK | os.X_OK
                ):
                    checks.append(
                        {
                            "name": (
                                f"destination writable: {root}"
                            ),
                            "ok": False,
                            "level": "error",
                            "message": (
                                f"Unable to write directory:\n"
                                f"{root}"
                            ),
                        }
                    )
                else:
                    checks.append(
                        {
                            "name": (
                                f"destination writable: {root}"
                            ),
                            "ok": True,
                            "level": "error",
                            "message": (
                                f"destination is writable: "
                                f"{root}"
                            ),
                        }
                    )

        for provider_path in provider_paths or []:
            for root in root_paths:
                try:
                    overlap = (
                        normcase_compare(provider_path)
                        == normcase_compare(root)
                        or normcase_compare(provider_path)
                        .startswith(
                            normcase_compare(root)
                            + os.sep
                        )
                        or normcase_compare(root).startswith(
                            normcase_compare(provider_path)
                            + os.sep
                        )
                    )
                except (OSError, ValueError):
                    overlap = False

                if overlap:
                    checks.append(
                        {
                            "name": (
                                "provider-managed path "
                                "conflict"
                            ),
                            "ok": True,
                            "level": "warning",
                            "message": (
                                f"organisation root {root} "
                                f"overlaps provider-managed "
                                f"path {provider_path}; "
                                f"structural actions there "
                                f"will require review"
                            ),
                        }
                    )

        errors = [
            check for check in checks
            if not check["ok"] and check["level"] == "error"
        ]

        return {
            "ok": not errors,
            "checks": checks,
        }

    # ---------------------------------------------------------
    # internals
    # ---------------------------------------------------------

    def _metadata_snapshots(
        self,
        media_id: int,
        metadata_scope,
    ) -> list | None:
        """
        Resolve metadata snapshots for planning. "cached"
        reads the latest persisted observation per
        provider/item; "live" calls the injected fetcher
        (no persistence here); a dict maps media_id to
        explicit snapshot payload lists (tests and
        deterministic callers).
        """

        if isinstance(metadata_scope, dict):
            return list(
                metadata_scope.get(media_id, [])
                or metadata_scope.get(str(media_id), [])
            )

        if metadata_scope == "live":
            if self.metadata_fetcher is None:
                return None
            try:
                fetched = self.metadata_fetcher(media_id)
            except Exception as error:
                return [
                    {
                        "provider": "unknown",
                        "error": str(error),
                        "unavailable": True,
                    }
                ]
            return list(fetched or [])

        records = (
            self.organisation_repository
            .list_metadata_observations(media_id)
        )

        latest: dict = {}

        for record in records:
            key = (record.provider, record.provider_item_id)
            current = latest.get(key)
            if current is None or record.id > current:
                latest[key] = record.id

        snapshots = []

        for record in records:
            if record.id not in latest.values():
                continue
            if isinstance(record.payload, dict) and (
                record.payload.get("withdrawn")
            ):
                # Append-only correction: withdrawn
                # observations stay as provenance but
                # never feed planning, What-If, or
                # classification again.
                continue
            snapshots.append(
                {
                    "observation_id": record.id,
                    "provider": record.provider,
                    "provider_item_id": (
                        record.provider_item_id
                    ),
                    "provider_item_kind": (
                        record.provider_item_kind
                    ),
                    "retrieved_at": record.retrieved_at,
                    "source_fingerprint": (
                        record.source_fingerprint
                    ),
                    "association_strength": (
                        record.association_strength
                    ),
                    "association_basis": (
                        record.association_basis
                    ),
                    "relevant": dict(record.payload or {}),
                }
            )

        return snapshots

    def _evaluate_mappings(
        self,
        profile: dict,
        snapshots: list,
    ) -> dict:
        """
        Evaluate explicit tag mappings against the
        combined tag evidence from every reliable
        associated provider. Tags merge (union,
        casefold-deduped): one provider's tags never
        erase another's, and a rule fires when ALL of
        its labels are present anywhere in the
        combined set. Provider-scoped mappings still
        require their labels inside that provider's
        own set. Shared deterministic precedence
        (specificity, priority, rule id) picks the
        winner; exact ties across different
        categories resolve to needs-review with the
        competitors named.
        """

        from app.organisation.profiles import (
            evaluate_tag_mappings,
            tag_mapping_rank,
        )

        mappings = list(profile.get("tag_mappings") or [])

        if not mappings:
            return {"outcome": "no_match"}

        combined_tags, by_provider_map = _combined_tag_sets(
            snapshots
        )

        by_provider = {
            provider: {
                str(tag).strip().casefold(): tag
                for tag in tags
            }
            for provider, tags in by_provider_map.items()
        }

        result = evaluate_tag_mappings(
            [
                mapping for mapping in mappings
                if mapping.get("provider") is None
            ],
            provider="",
            tags=combined_tags,
        )

        hits = []

        if result["outcome"] == "match":
            hit = dict(result["mapping"])
            hit["_providers"] = sorted(by_provider)
            hits.append(hit)
        elif result["outcome"] == "conflict":
            competitors = ", ".join(
                sorted(
                    {
                        f"'{item.get('id')}' → "
                        f"{item.get('category')}"
                        for item in (
                            result.get("candidates") or []
                        )
                        if isinstance(item, dict)
                    }
                )
            )

            return {
                "outcome": "conflict",
                "reason": (
                    "multiple tag mappings match with "
                    "equal precedence"
                    + (
                        f" for different categories "
                        f"({competitors})"
                        if competitors
                        else ""
                    )
                    + "; review required"
                ),
                "candidates": result.get("candidates", []),
            }

        for provider, folded_map in by_provider.items():
            scoped = [
                mapping for mapping in mappings
                if str(mapping.get("provider") or "")
                .strip()
                .casefold()
                == str(provider or "").strip().casefold()
            ]

            if not scoped:
                continue

            scoped_result = evaluate_tag_mappings(
                scoped,
                provider=provider or "",
                tags=sorted(folded_map.values()),
            )

            if scoped_result["outcome"] == "match":
                hit = dict(scoped_result["mapping"])
                hit["_providers"] = [provider]
                hits.append(hit)
            elif scoped_result["outcome"] == "conflict":
                return {
                    "outcome": "conflict",
                    "reason": scoped_result["reason"],
                    "candidates": scoped_result.get(
                        "candidates", []
                    ),
                }

        if not hits:
            return {"outcome": "no_match"}

        ordered = sorted(hits, key=tag_mapping_rank)

        winner = ordered[0]

        tied = [
            candidate for candidate in ordered[1:]
            if tag_mapping_rank(candidate)
            == tag_mapping_rank(winner)
            and candidate.get("category")
            != winner.get("category")
        ]

        if tied:
            competitors = ", ".join(
                sorted(
                    {
                        f"'{item.get('id')}' → "
                        f"{item.get('category')}"
                        for item in [winner, *tied]
                    }
                )
            )

            return {
                "outcome": "conflict",
                "reason": (
                    "multiple tag mappings match with "
                    "equal precedence for different "
                    f"categories ({competitors}); review "
                    "required"
                ),
                "candidates": [
                    {
                        "id": item.get("id"),
                        "category": item.get("category"),
                        "labels": item.get("labels"),
                    }
                    for item in [winner, *tied]
                ],
            }

        contributors = ", ".join(
            winner.get("_providers") or []
        )

        return {
            "outcome": "match",
            "mapping": winner,
            "reason": (
                f"explicit tag mapping "
                f"'{winner.get('id')}' matched for "
                f"category '{winner.get('category')}'"
                + (
                    f" on combined tags from {contributors}"
                    if contributors
                    else ""
                )
            ),
        }

    def _suitability_checks(
        self,
        profile: dict,
        merged_metadata: dict,
        category,
    ) -> list:
        from app.organisation.rules import (
            CategorySuitabilityRules,
        )

        checks = []

        intelligent = dict(
            profile.get("intelligent_rules") or {}
        )

        safety_categories = intelligent.get(
            "safety_categories", []
        ) or []

        for entry in safety_categories:
            if isinstance(entry, dict):
                watched = entry.get("category")
                signals = entry.get("signals", {})
            else:
                watched = entry
                signals = {}

            if watched is None:
                continue

            verdict = CategorySuitabilityRules.assess(
                metadata=merged_metadata,
                category=watched,
                category_signals={watched: signals},
            )

            checks.append(
                {
                    "rule": (
                        f"{CategorySuitabilityRules.name}@"
                        f"{CategorySuitabilityRules.semantic_version}"
                    ),
                    "verdict": verdict.verdict,
                    "reason": (
                        f"suitability for '{watched}': "
                        f"{verdict.verdict}: "
                        + "; ".join(verdict.reasoning)
                    ),
                }
            )

        return checks

    def _destination(
        self,
        profile: dict,
        evidence,
        category,
        classification,
        category_source,
        merged_metadata=None,
        local_kind=None,
    ) -> tuple:
        """
        Calculate the canonical destination. Template
        choice follows the category provenance: explicit
        policy categories (certification, collection,
        signals, tags) render through the category
        template with the configured folder; a locally
        classified category with an exactly configured
        folder does the same; otherwise local movies
        render through the movie template and local TV
        through the TV template. Without a usable
        profile the existing destination template rules
        apply (zero-integration fallback preserved).

        Template values prefer resolved provider
        metadata (title/year/season/episode) with
        filename-derived evidence as fallback, so a
        reliable provider title wins over
        release-filename text. Filenames follow the
        profile filename policy (keep/clean/custom);
        clean names fall back to the existing
        filename when metadata is insufficient.
        """

        from app.organisation.profiles import (
            root_token_fields,
        )
        from app.organisation.rules import (
            DestinationTemplateRules,
            select_library_root,
        )

        roots = list(profile.get("roots") or [])

        if not roots:
            return (
                None,
                "no organisation roots configured; "
                "review required",
                None,
            )

        fields = root_token_fields(roots)

        root_paths = list(fields.values())

        root = select_library_root(root_paths, evidence.path)

        if root is None and root_paths:
            root = root_paths[0]

        title, year, season, episode = _split_title_parts(
            evidence.name or ""
        )

        title, series, year, season, episode, episode_title = (
            _resolve_template_values(
                merged_metadata, title, year, season, episode
            )
        )

        filename_policy = (
            profile.get("filename_policy") or {}
            if isinstance(
                profile.get("filename_policy"), dict
            )
            else {}
        )

        final_name, naming_reason, naming_error = _clean_filename(
            filename_policy,
            evidence.name or "",
            tv=(local_kind == "tv"),
            title=title,
            series=series,
            year=year,
            season=season,
            episode=episode,
            episode_title=episode_title,
        )

        if naming_error is not None:
            return None, naming_error, None

        reasoning_note = naming_reason

        templates = dict(profile.get("templates") or {})
        categories = dict(profile.get("categories") or {})

        windows = (
            True
            if profile.get("platform") == "windows"
            else (
                False
                if profile.get("platform") == "posix"
                else None
            )
        )

        template_name = None

        tv_fallback_folder = None

        if category and category_source in (
            "certification",
            "collection",
            "metadata",
            "tagmap",
            "rule",
            "fallback",
        ):
            template_name = profile.get("category_template")

            if (
                category_source == "fallback"
                and local_kind == "tv"
            ):
                # Fallback TV keeps the season-bearing
                # TV structure inside its configured
                # category folder: the folder carries
                # the vocabulary (TV/), the TV
                # template carries the seasons.
                folder = categories.get(category, "")

                if folder:
                    template_name = profile.get(
                        "tv_template"
                    )
                    tv_fallback_folder = folder
        elif classification == "tv" or (
            category == "tv" and category_source == "local"
        ):
            # Normal TV always keeps the TV template:
            # only it carries Season structure, and a
            # baseline category never forces the
            # generic Category template.
            template_name = profile.get("tv_template")
        elif category and category_source == "local":
            # Normal movies render through the Movie
            # template for the same reason: the
            # Category template applies only when an
            # explicit policy selected a configured
            # category.
            template_name = profile.get("movie_template")

        template = (
            templates.get(template_name or "")
            if template_name
            else None
        )

        if template is not None:
            values = {
                "Title": title,
                "Year": year,
                "Series": series,
                "Season": season,
                "Episode": episode,
                "Category": categories.get(
                    category, category or ""
                ),
                "TitleOrSeries": (
                    f"{title} ({year})".strip()
                    if year
                    else title
                ),
            }

            destination, error = render_template(
                template,
                root=root,
                values=values,
                windows=windows,
                root_fields=fields,
            )

            if (
                destination is not None
                and tv_fallback_folder
            ):
                destination = _prefix_folder_under_root(
                    root_paths, destination,
                    tv_fallback_folder,
                )

            if destination is not None:
                return (
                    os.path.join(destination, final_name),
                    f"profile template "
                    f"'{template_name}' rendered "
                    f"canonical destination"
                    + (
                        f"; {reasoning_note}"
                        if reasoning_note
                        else ""
                    ),
                    template.get("pattern"),
                )

            return None, error, None

        category_dir = (
            DestinationTemplateRules.destination_directory(
                root, category or "unclassified"
            )
        )

        return (
            DestinationTemplateRules.full_destination(
                category_dir, final_name
            ),
            "existing destination template rules applied",
            None,
        )

    def _owned_by_other_lineage(
        self,
        media_id: int,
        destination: str,
    ):
        try:
            lineages = (
                self.media_repository.get_active_lineages()
            )
        except Exception:
            return None

        target = normcase_compare(destination)

        for lineage in lineages:
            if lineage.id == media_id:
                continue
            try:
                if (
                    normcase_compare(
                        lineage.file_path or ""
                    )
                    == target
                ):
                    return lineage.id
            except (OSError, ValueError):
                continue

        return None

    def _provider_managed_hit(
        self,
        current_path,
        destination,
        snapshots,
    ) -> str | None:
        """
        Detect overlap between the planned move and
        provider-known paths (roots/parent paths cited
        in metadata payloads). Any overlap is a review
        condition, never silent.
        """

        managed = set()

        for snapshot in snapshots or []:
            relevant = snapshot.get("relevant") or {}
            for key in (
                "root_folder_path",
                "provider_path",
                "series_path",
                "path",
            ):
                value = relevant.get(key)
                if value:
                    managed.add(normcase_compare(value))
                    # Provider-known folders matter as
                    # much as exact file paths: moving
                    # into or out of a managed folder
                    # affects provider consistency even
                    # for files the provider never
                    # tracked individually.
                    try:
                        managed.add(
                            normcase_compare(
                                os.path.dirname(value)
                            )
                        )
                    except (OSError, ValueError):
                        continue

        if not managed:
            return None

        for candidate in (current_path, destination):
            if not candidate:
                continue
            key = normcase_compare(candidate)
            for path in managed:
                if (
                    key == path
                    or key.startswith(path + os.sep)
                    or path.startswith(key + os.sep)
                ):
                    return (
                        "path overlaps provider-managed "
                        "location; review required before "
                        "execution"
                    )

        return None

    def _lineages_under(self, scope_path: str) -> list:
        try:
            lineages = (
                self.media_repository.get_active_lineages()
            )
        except Exception:
            return []

        try:
            anchor = os.path.realpath(scope_path)
        except (OSError, ValueError):
            return []

        matched = []

        for lineage in lineages:
            try:
                current = os.path.realpath(
                    lineage.file_path or ""
                )
            except (OSError, ValueError):
                continue

            if current == anchor or current.startswith(
                anchor + os.sep
            ):
                matched.append(lineage.id)

        return matched


def _association_candidates(snapshots: list) -> list:
    candidates = []

    for snapshot in snapshots or []:
        if snapshot.get("unavailable"):
            continue
        relevant = snapshot.get("relevant") or {}
        candidates.append(
            {
                "provider": snapshot.get("provider"),
                "provider_item_id": snapshot.get(
                    "provider_item_id"
                ),
                "kind": snapshot.get(
                    "provider_item_kind"
                ),
                "path": relevant.get("path"),
                "provider_ids": relevant.get(
                    "provider_ids", {}
                ),
                "parent_provider_id": relevant.get(
                    "parent_provider_id"
                ),
                "parent_provider_ids": relevant.get(
                    "parent_provider_ids", {}
                ),
                "title": relevant.get("title"),
                "year": relevant.get("year"),
                "season_number": relevant.get(
                    "season_number"
                ),
                "episode_number": relevant.get(
                    "episode_number"
                ),
            }
        )

    return candidates


def _evaluate_certification_policy(
    rules, merged_metadata: dict, local_kind
) -> dict:
    """
    Match the merged (priority-resolved) certification
    against the profile's explicit certification
    policy. Returns no_match / match / conflict.
    Matching uses the normalised certification; the
    original provider values stay as provenance in
    the merged summary. A kind-specific rule
    (movie/tv) beats a generic any-kind rule for the
    same certification; remaining exact ties across
    different categories are conflicts, never silent
    picks.
    """

    if not rules:
        return {"outcome": "no_match"}

    cert = normalise_certification(
        (merged_metadata or {}).get("certification")
    )

    if not cert:
        return {"outcome": "no_match"}

    kind = (local_kind or "any").strip().casefold()

    hits = []

    for rule in rules or []:
        if not isinstance(rule, dict):
            continue

        rule_cert = normalise_certification(
            rule.get("certification")
        )

        if not rule_cert or rule_cert != cert:
            continue

        rule_kind = str(
            rule.get("media_kind") or "any"
        ).strip().casefold()

        if rule_kind in ("movies", "movie"):
            rule_kind = "movie"
        elif rule_kind in ("tv", "series", "show", "shows"):
            rule_kind = "tv"
        elif rule_kind in ("any", "all", "*"):
            rule_kind = "any"
        else:
            continue

        if rule_kind != "any" and rule_kind != kind:
            continue

        hits.append((rule, rule_kind))

    if not hits:
        return {"outcome": "no_match"}

    # Kind-specific rules first, then stable rule id.
    hits.sort(
        key=lambda item: (
            0 if item[1] != "any" else 1,
            str(item[0].get("id") or ""),
        )
    )

    winner, _ = hits[0]

    tied = [
        rule
        for rule, _ in hits[1:]
        if str(rule.get("category") or "")
        != str(winner.get("category") or "")
        and (
            (
                0
                if rule_kind_of(rule) != "any"
                else 1,
                str(rule.get("id") or ""),
            )
            == (
                0
                if rule_kind_of(winner) != "any"
                else 1,
                str(winner.get("id") or ""),
            )
        )
    ]

    if tied:
        competitors = ", ".join(
            sorted(
                {
                    f"'{item.get('id')}' → "
                    f"{item.get('category')}"
                    for item in [winner, *tied]
                }
            )
        )

        return {
            "outcome": "conflict",
            "reason": (
                f"certification '{cert}' matches "
                f"multiple policy rules for different "
                f"categories ({competitors}); review "
                f"required"
            ),
        }

    return {
        "outcome": "match",
        "category": winner.get("category"),
        "rule": winner,
        "reason": (
            f"certification '{cert}' matched the "
            f"profile's '{winner.get('category')}' "
            f"classification policy "
            f"(rule '{winner.get('id')}')"
        ),
    }


def rule_kind_of(rule: dict) -> str:
    """Normalised media kind of one certification rule."""

    kind = str(
        (rule or {}).get("media_kind") or "any"
    ).strip().casefold()

    if kind in ("movies", "movie"):
        return "movie"

    if kind in ("tv", "series", "show", "shows"):
        return "tv"

    return "any"


def _evaluate_collection_policy(
    rules, merged_metadata: dict
) -> dict:
    """
    Match merged collection membership against the
    profile's explicit collection policy. Returns
    no_match / match / conflict. Matching is
    case-insensitive; exact ties across different
    categories are conflicts, never silent picks.
    """

    if not rules:
        return {"outcome": "no_match"}

    collections = {
        str(value).strip().casefold()
        for value in (
            (merged_metadata or {}).get("collections") or []
        )
        if isinstance(value, str) and value.strip()
    }

    if not collections:
        return {"outcome": "no_match"}

    hits = []

    for rule in rules or []:
        if not isinstance(rule, dict):
            continue

        name = rule.get("collection")

        if (
            not isinstance(name, str)
            or not name.strip()
        ):
            continue

        if name.strip().casefold() in collections:
            hits.append(rule)

    if not hits:
        return {"outcome": "no_match"}

    hits.sort(key=lambda item: str(item.get("id") or ""))

    winner = hits[0]

    tied = [
        rule
        for rule in hits[1:]
        if str(rule.get("category") or "")
        != str(winner.get("category") or "")
    ]

    if tied:
        competitors = ", ".join(
            sorted(
                {
                    f"'{item.get('id')}' → "
                    f"{item.get('category')}"
                    for item in [winner, *tied]
                }
            )
        )

        return {
            "outcome": "conflict",
            "reason": (
                f"collections match multiple policy "
                f"rules for different categories "
                f"({competitors}); review required"
            ),
        }

    return {
        "outcome": "match",
        "category": winner.get("category"),
        "rule": winner,
        "reason": (
            f"collection '{winner.get('collection')}' "
            f"matched the profile's "
            f"'{winner.get('category')}' collection "
            f"policy (rule '{winner.get('id')}')"
        ),
    }


def _combined_tag_sets(snapshots: list) -> tuple:
    """
    (combined sorted tags, {provider: [tags]}) across
    every snapshot, casefold-deduped, providers never
    erasing each other. Shared by unified rule
    matching and tag-mapping evaluation so both see
    identical evidence.
    """

    by_provider: dict = {}
    combined: dict = {}

    for snapshot in snapshots or []:
        relevant = snapshot.get("relevant") or {}
        provider = snapshot.get("provider") or ""

        for tag in relevant.get("tags") or []:
            text = str(tag or "").strip()

            if not text:
                continue

            folded = text.casefold()
            by_provider.setdefault(provider, {})

            if folded not in by_provider[provider]:
                by_provider[provider][folded] = text

            if folded not in combined:
                combined[folded] = text

    return (
        sorted(combined.values()),
        {
            provider: sorted(tags.values())
            for provider, tags in by_provider.items()
        },
    )


def _match_unified_rule(
    rules, local_kind, merged_metadata, combined_tags,
    tags_by_provider,
):
    """
    First matching unified organisation rule or
    None. Evidence comes from the merged summary
    (certification, collections, genres) and the
    combined tag sets. Pure wrapper keeping the
    authority call sites uniform.
    """

    if not rules:
        return None

    from app.organisation.profiles import (
        match_organisation_rule,
    )

    merged = (
        merged_metadata
        if isinstance(merged_metadata, dict)
        else {}
    )

    return match_organisation_rule(
        rules,
        media_kind=local_kind or "any",
        certification=merged.get("certification") or "",
        collections=merged.get("collections") or [],
        genres=merged.get("genres") or [],
        combined_tags=combined_tags,
        tags_by_provider=tags_by_provider,
    )


def _legacy_rule_description(
    source: str, rule, category, merged_metadata
) -> dict | None:
    """
    Matched-rule record for legacy policy hits so
    What-If shows one uniform "matched rule" line
    whatever tier decided. Descriptions mirror the
    unified format (media kind + evidence →
    category).
    """

    if not isinstance(rule, dict):
        return None

    rule_id = rule.get("id") or source
    merged = (
        merged_metadata
        if isinstance(merged_metadata, dict)
        else {}
    )

    if source == "certification":
        kind = str(
            rule.get("media_kind") or "any"
        ).strip().lower()
        word = (
            "Movie"
            if kind in ("movie", "movies")
            else ("TV" if kind in ("tv", "series") else "Any kind")
        )
        cert = str(
            rule.get("certification") or ""
        ).strip().upper()
        description = f"{word} + {cert} → {category}"
    elif source == "collection":
        description = (
            f"collection "
            f"'{rule.get('collection')}' → {category}"
        )
    elif source == "tagmap":
        labels = [
            str(label).strip()
            for label in (rule.get("labels") or [])
            if isinstance(label, str) and label.strip()
        ]
        description = (
            f"{' + '.join(labels)} → {category}"
            if labels
            else f"tag rule → {category}"
        )
    else:
        description = f"{source} → {category}"

    return {
        "id": rule_id,
        "description": description,
        "category": category,
        "fallback": False,
    }


def _merge_metadata(snapshots: list, priority=()) -> dict:
    """
    Merge cited metadata snapshots into one normalised
    record for classification, keeping source labels so
    reasoning stays attributable.

    Scalar fields resolve by provider priority
    (default Radarr > Sonarr > Jellyfin): the
    highest-priority non-null value wins and is
    recorded in _sources, while differing values
    from other providers are retained in
    _disagreements as provenance. They never
    become conflicts, and they never erase
    compatible tags.
    List fields and tags union across every reliable
    provider with duplicates removed; one provider's
    lack of a tag never erases another's.
    """

    order = list(priority or ()) or list(
        DEFAULT_PROVIDER_PRIORITY
    )

    def _rank(provider):
        name = str(provider or "").strip().casefold()

        for index, entry in enumerate(order):
            if str(entry or "").strip().casefold() == name:
                return (0, index)

        return (1, name)

    merged: dict = {}
    tag_sets: dict = {}
    sources: dict = {}
    seen_values: dict = {}

    for snapshot in sorted(
        snapshots or [],
        key=lambda item: (
            _rank(item.get("provider")),
            str(item.get("provider") or ""),
            str(item.get("provider_item_id") or ""),
        ),
    ):
        relevant = snapshot.get("relevant") or {}
        provider = str(snapshot.get("provider") or "")

        for key in (
            "title",
            "year",
            "season_number",
            "episode_number",
            "runtime",
            "studio",
            "network",
            "overview",
            "certification",
        ):
            value = relevant.get(key)

            if value is None:
                continue

            seen_values.setdefault(key, [])

            if not any(
                entry["value"] == value
                for entry in seen_values[key]
            ):
                seen_values[key].append(
                    {"provider": provider, "value": value}
                )

            if key not in merged:
                merged[key] = value
                sources[key] = provider

        for key in ("genres", "collections", "provider_flags"):
            merged.setdefault(key, [])
            for value in relevant.get(key) or []:
                if value not in merged[key]:
                    merged[key].append(value)

        tags = relevant.get("tags") or []
        if tags:
            tag_sets.setdefault(provider, [])
            for tag in tags:
                if tag not in tag_sets[provider]:
                    tag_sets[provider].append(tag)

    merged["_tags_by_provider"] = tag_sets
    merged["_sources"] = sources
    merged["_provider_priority"] = list(order)
    merged["_disagreements"] = {
        key: entries
        for key, entries in seen_values.items()
        if len(entries) > 1
    }

    return merged


def _common_ancestor_pair(pairs, scope_anchor):
    """
    Find the deepest (source ancestor, destination
    ancestor) pair shared by every (source, destination)
    file pair such that each file preserves its path
    relative to the ancestors. The source ancestor must
    stay at or below `scope_anchor` when one is given
    (a scope never renames above the selected
    directory). Returns (source_dir, dest_dir) or None.
    Pure path arithmetic; no filesystem access.
    """

    if not pairs:
        return None

    def ancestors(path):
        chain = []
        current = os.path.dirname(path)

        while True:
            chain.append(current)
            parent = os.path.dirname(current)

            if parent == current:
                break

            current = parent

            if len(chain) > 64:
                break

        return chain

    try:
        src_chains = [ancestors(source) for source, _ in pairs]
        dst_chains = [ancestors(dest) for _, dest in pairs]
    except (OSError, ValueError):
        return None

    src_common = set(src_chains[0])

    for chain in src_chains[1:]:
        src_common &= set(chain)

    dst_common = set(dst_chains[0])

    for chain in dst_chains[1:]:
        dst_common &= set(chain)

    def depth(ancestor, chain):
        try:
            return chain.index(ancestor)
        except ValueError:
            return None

    candidates = []

    for src in src_common:
        if scope_anchor is not None and not (
            src == scope_anchor
            or src.startswith(scope_anchor + os.sep)
        ):
            continue

        for dst in dst_common:
            depths = []

            for (source, dest), src_chain, dst_chain in zip(
                pairs, src_chains, dst_chains
            ):
                depth_src = depth(src, src_chain)
                depth_dst = depth(dst, dst_chain)

                if depth_src is None or depth_dst is None:
                    break

                try:
                    rel_src = os.path.relpath(source, src)
                    rel_dst = os.path.relpath(dest, dst)
                except ValueError:
                    break

                if (
                    rel_src.startswith("..")
                    or rel_dst.startswith("..")
                    or rel_src != rel_dst
                ):
                    break

                depths.append((depth_src, depth_dst))
            else:
                candidates.append((src, dst, depths))

    if not candidates:
        return None

    # Deepest source ancestor wins (least disruptive);
    # ties prefer the deepest destination ancestor.
    candidates.sort(
        key=lambda item: (
            min(depth[0] for depth in item[2]),
            min(depth[1] for depth in item[2]),
        )
    )

    return candidates[0][0], candidates[0][1]


def _sanitise_name_component(text: str) -> str:
    """
    Make one provider-supplied name safe inside a
    path: path separators become "-", surrounding
    whitespace/dots are stripped. Never raises;
    empty stays empty so callers can fall back.
    """

    import re

    cleaned = re.sub(r"[/\\\\]+", "-", str(text or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.strip(".")


def _resolve_template_values(
    merged_metadata, file_title, file_year, file_season, file_episode
) -> tuple:
    """
    (title, series, year, season, episode,
    episode_title) preferring resolved provider
    metadata with filename-derived evidence as
    fallback. Reliable provider titles therefore
    win over release-filename text; when metadata
    is absent or silent the filename values stand
    unchanged. Pure.
    """

    meta = (
        merged_metadata
        if isinstance(merged_metadata, dict)
        else {}
    )

    def _text(value):
        if isinstance(value, bool):
            return ""
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            return value.strip()
        return ""

    meta_title = _sanitise_name_component(
        _text(meta.get("title"))
    )
    parent_title = _sanitise_name_component(
        _text(meta.get("parent_title"))
    )
    meta_year = _text(meta.get("year"))
    meta_season = _text(meta.get("season_number"))
    meta_episode = _text(meta.get("episode_number"))

    title = meta_title or file_title
    series = parent_title or meta_title or file_title
    year = meta_year or file_year
    season = meta_season or file_season
    episode = meta_episode or file_episode

    episode_title = ""

    if parent_title and meta_title and meta_title != parent_title:
        episode_title = meta_title

    return title, series, year, season, episode, episode_title


def _clean_base(tv, title, series, year, season, episode,
                episode_title) -> str:
    """
    Canonical base name (no extension): movies
    "Title (Year)", TV "Series - SxxEyy [-
    EpisodeTitle]" with graceful omission. Returns
    "" when nothing reliable exists. Pure.
    """

    if tv:
        base = _sanitise_name_component(series)

        if not base:
            return ""

        season_no, episode_no = _number(season), _number(
            episode
        )

        if season_no is not None and episode_no is not None:
            base = (
                f"{base} - S{season_no:02d}"
                f"E{episode_no:02d}"
            )

            if episode_title:
                base = (
                    f"{base} - "
                    f"{_sanitise_name_component(episode_title)}"
                ).strip()
        elif year:
            base = f"{base} ({year})".strip()

        return base

    base = _sanitise_name_component(title)

    if not base:
        return ""

    if year:
        base = f"{base} ({year})".strip()

    return base


def _clean_filename(
    policy,
    evidence_name: str,
    *,
    tv: bool = False,
    title: str,
    series: str,
    year: str,
    season: str,
    episode: str,
    episode_title: str,
) -> tuple:
    """
    (filename, reason, error): exactly one of
    filename/error is not None. Modes:

    - keep (default when the profile sets no
      policy): today's separator cleanup only.
    - clean: readable names from resolved
      metadata; falls back to the existing
      filename whenever metadata is
      insufficient (never fabricates).
    - template: an advanced custom pattern
      rendered with the existing strict
      renderer (Title/Series/Year/Season/
      Episode/EpisodeTitle/Extension);
      unknown fields or path separators fail
      closed to review. Tags never feed
      filenames; they route categories only.
    Pure string work; never touches the
    filesystem.
    """

    from app.organisation.profiles import (
        FILENAME_CLEAN,
        FILENAME_EXTENDED,
        FILENAME_TEMPLATE,
        normalise_filename_policy,
    )
    try:
        normalised = normalise_filename_policy(policy)
    except ValueError as error:
        return None, "", f"{error}; review required"

    mode = normalised["mode"]

    stem, dot, extension = str(evidence_name or "").rpartition(".")

    if not dot:
        stem, extension = str(evidence_name or ""), ""

    def _with_extension(base: str) -> str:
        base = (base or "").strip()

        if not base:
            return ""

        if extension:
            return f"{base}.{extension}"

        return base

    if mode == FILENAME_CLEAN:
        base = _clean_base(
            tv, title, series, year, season, episode,
            episode_title,
        )

        if not base:
            return _keep_filename(evidence_name)

        return (
            _with_extension(base),
            f"clean filename from resolved metadata: "
            f"{_with_extension(base)}",
            None,
        )

    if mode == FILENAME_EXTENDED:
        from app.organisation.file_evidence import (
            extract_file_evidence,
        )

        pattern = normalised.get("pattern") or ""
        separator = normalised.get("separator") or " "

        if "/" in separator or "\\" in separator:
            return (
                None,
                "",
                "extended filename separator must not "
                "contain path separators; review "
                "required",
            )

        base = _clean_base(
            tv, title, series, year, season, episode,
            episode_title,
        )

        if not base:
            return _keep_filename(evidence_name)

        if not pattern.strip():
            return (
                _with_extension(base),
                f"clean filename from resolved metadata "
                f"(no extended pattern configured): "
                f"{_with_extension(base)}",
                None,
            )

        media_fields = {
            "title": title,
            "year": year,
            "series": series,
            "season": season,
            "episode": episode,
            "episode_title": episode_title,
        }
        file_fields = extract_file_evidence(
            evidence_name or ""
        )

        suffix, missing, suffix_error = (
            _render_extended_suffix(
                pattern, media_fields, file_fields
            )
        )

        if suffix_error is not None:
            return None, "", suffix_error

        if not suffix:
            return (
                _with_extension(base),
                "extended filename components unavailable "
                f"({', '.join(missing) or 'no tokens'}); "
                f"base name only: "
                f"{_with_extension(base)}",
                None,
            )

        full = f"{base}{separator}{suffix}".strip()

        return (
            _with_extension(full),
            f"extended filename from resolved metadata "
            f"plus file evidence: "
            f"{_with_extension(full)}"
            + (
                f" (unavailable: {', '.join(missing)})"
                if missing
                else ""
            ),
            None,
        )

    if mode == FILENAME_TEMPLATE:
        pattern = normalised.get("pattern") or ""
        fields = {
            "Title": title,
            "Series": series,
            "Year": year,
            "Season": season,
            "Episode": episode,
            "EpisodeTitle": episode_title,
            "Extension": extension,
        }

        try:
            from app.organisation.profiles import (
                _StrictFields,
            )

            rendered = pattern.format_map(
                _StrictFields(fields)
            )
        except KeyError as error:
            return (
                None,
                "",
                f"filename pattern references unknown "
                f"field {error}; review required",
            )

        if not rendered or "/" in rendered or "\\" in rendered:
            return (
                None,
                "",
                "custom filename pattern produced no "
                "usable filename; review required",
            )

        return (
            rendered,
            f"custom filename pattern rendered: {rendered}",
            None,
        )

    return _keep_filename(evidence_name)


def _render_extended_suffix(
    pattern: str, media_fields: dict, file_fields: dict
) -> tuple:
    """
    (suffix, missing, error): render one extended
    naming pattern. Tokens are namespaced so the
    origin is never ambiguous: {media[title|year|
    series|season|episode|episode_title]} for
    resolved media metadata, {file[quality|
    resolution|bitrate|codec|audio|source|hdr|
    edition]} for analysed file evidence. Literal
    text passes through untouched. Missing values
    render empty and the result is tidied (no
    doubled/leading/trailing separators), so the
    caller can omit the component instead of
    printing blanks. Unknown tokens fail closed.
    Returns the tidied suffix ("" when nothing
    resolved), the sorted missing token names, and
    an error string (or None). Pure.
    """

    import re

    token_re = re.compile(r"\{(media|file)\[([A-Za-z_]+)\]\}")

    media_ok = {
        "title",
        "year",
        "series",
        "season",
        "episode",
        "episode_title",
    }
    file_ok = {
        "quality",
        "resolution",
        "bitrate",
        "codec",
        "audio",
        "source",
        "hdr",
        "edition",
    }

    missing = set()

    def _fill(match):
        namespace, name = match.group(1), match.group(2)

        if namespace == "media" and name in media_ok:
            value = str(media_fields.get(name) or "")
        elif namespace == "file" and name in file_ok:
            value = str(file_fields.get(name) or "")
        else:
            raise KeyError(match.group(0))

        if not value:
            missing.add(match.group(0))

        return value

    try:
        bare = token_re.sub("", pattern or "")
    except Exception:
        bare = pattern or ""

    brace_re = re.compile(r"\{[^{}]*\}|\{|\}")

    unknown = brace_re.search(bare)

    if unknown:
        return (
            "",
            sorted(missing),
            f"filename pattern uses unknown token "
            f"'{unknown.group(0)}'; review required",
        )

    try:
        rendered = token_re.sub(_fill, pattern or "")
    except KeyError as error:
        return (
            "",
            sorted(missing),
            f"filename pattern uses unknown token "
            f"{error}; review required",
        )

    tidied = re.sub(r"\s+", " ", rendered).strip()
    tidied = tidied.strip(" .-_")

    # Collapse runs of separator punctuation to the
    # last one ("2160p.WEB-DL.-LAMA" becomes
    # "2160p.WEB-DL-LAMA"): an emptied token leaves
    # no unexplained blanks. Spaced separators
    # (" - ") are intentional and untouched.
    tidied = re.sub(
        r"[.\-_]{2,}", lambda m: m.group(0)[-1], tidied
    )

    tidied = re.sub(r" {2,}", " ", tidied).strip()
    tidied = tidied.strip(" .-_")

    return tidied, sorted(missing), None


def _prefix_folder_under_root(
    root_paths, destination, folder
) -> str:
    """
    Insert a category folder directly below the
    destination root that prefixes the rendered
    destination (longest match wins). Used for
    fallback TV: the TV template selects the root
    via its own token, while the configured
    category folder carries the vocabulary.
    Pure path arithmetic; containment was already
    validated, so a missing prefix leaves the
    destination untouched (fail safe, never
    invent a root).
    """

    try:
        key = normcase_compare(destination or "")
    except (OSError, ValueError):
        return destination

    best = ""

    for root in root_paths or []:
        if not isinstance(root, str) or not root:
            continue

        try:
            root_key = normcase_compare(root)
        except (OSError, ValueError):
            continue

        if (
            key == root_key
            or key.startswith(root_key + os.sep)
        ) and len(root_key) > len(best):
            best = root

    if not best:
        return destination

    try:
        relative = os.path.relpath(destination, best)
    except ValueError:
        return destination

    if relative.startswith(".."):
        return destination

    return os.path.join(best, folder, relative)


def _number(value):
    """int(value) or None for season/episode fields."""

    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _keep_filename(evidence_name: str) -> tuple:
    """
    Existing-filename fallback (keep mode): the
    source filename is preserved byte-identical.
    Organisation may move the file into the
    correct folder structure, but keep mode never
    renames. A rename happens only under an
    explicit clean/extended/template policy.
    """

    return evidence_name or "", "", None


def _split_title_parts(name: str) -> tuple:
    """
    Split a filename into (title, year, season,
    episode) for template values. Deterministic and
    conservative: the year is the first plausible
    four-digit year; season/episode come from explicit
    S..E.. markers only; the title is the stem with
    the year removed and separators normalised to
    single spaces. Never raises.
    """

    import re

    stem = str(name or "")

    if "." in stem:
        stem = stem.rpartition(".")[0]

    year = ""
    year_match = re.search(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", stem)

    if year_match:
        year = year_match.group(0)

    season = ""
    episode = ""

    marker = re.search(
        r"[Ss](\d{1,2})\s?[Ee](\d{1,3})", stem
    )

    if marker:
        season = str(int(marker.group(1)))
        episode = str(int(marker.group(2)))

    title = stem

    if year:
        title = title.replace(year, " ", 1)

    title = re.sub(r"[._\-+]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip()

    return title, year, season, episode


def _safe_component(name: str) -> str:
    return (name or "").strip()


def canonical_path_key(path: str) -> str | None:
    """
    Stable read-only comparison key for filesystem
    paths (normcase/normpath/abspath). Returns None
    when the path cannot be normalised. Pure path
    arithmetic; never touches the filesystem beyond
    abspath.
    """

    try:
        return os.path.normcase(
            os.path.normpath(os.path.abspath(str(path or "")))
        )
    except (OSError, ValueError):
        return None


def index_lineages_by_path(lineages: list) -> dict:
    """
    Map canonical path keys to lineage ids for
    sampler and live-fetch matching. Read-only.
    """

    index = {}

    for lineage in lineages or []:
        key = canonical_path_key(
            getattr(lineage, "file_path", "") or ""
        )

        if key is not None:
            index[key] = lineage.id

    return index


def _is_cross_device(source, destination) -> bool:
    """
    True when source and destination demonstrably live
    on different filesystems (st_dev differs), comparing
    the source against the nearest existing ancestor of
    the destination directory. False when either side
    cannot be stated (fail toward the ordinary move;
    execution re-checks immediately before mutation).
    Read-only.
    """

    try:
        source_device = os.stat(source).st_dev
    except OSError:
        return False

    target = os.path.dirname(os.path.abspath(destination or ""))

    while target and not os.path.exists(target):
        parent = os.path.dirname(target)

        if parent == target:
            break

        target = parent

    if not target or not os.path.exists(target):
        return False

    try:
        return os.stat(target).st_dev != source_device
    except OSError:
        return False


def _same_path(first: str | None, second: str | None) -> bool:
    if not first or not second:
        return False

    try:
        return normcase_compare(first) == normcase_compare(
            second
        )
    except (OSError, ValueError):
        return False


def resolve_destination_root(roots, destination):
    """
    (token, path) of the profile root whose path is the
    longest prefix of destination, else (None, None).
    Pure; the pattern token explicitly selected this
    root at render time, and this only reports which
    one it was for What-If and preview display.
    Identical resolution feeds What-If, preview, and
    execution because all three read the same planner.
    """

    if not destination:
        return None, None

    try:
        fields = root_token_fields(roots)
    except Exception:
        return None, None

    target = os.path.normpath(str(destination))

    best = (None, None)
    best_length = -1

    for token, path in fields.items():
        try:
            prefix = os.path.normpath(str(path))
        except (OSError, ValueError):
            continue

        if target == prefix or target.startswith(
            prefix + os.sep
        ):
            if len(prefix) > best_length:
                best = ("{" + token + "}", str(path))
                best_length = len(prefix)

    return best
