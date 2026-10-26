import os

from app.database.db import get_connection

from app.database.service_graph import (
    build_service_graph,
)

from app.database.repositories.scan_status import (
    ScanStatus
)

from app.versioning import (
    PIPELINE_VERSION,
    build_component_versions,
    build_policy_values,
    get_git_revision,
    intelligence_identity_digest,
)

from app.services.exclusion_service import (
    get_excluded_paths
)

from app.services.run_applicability_service import (
    RunApplicabilityService,
)

from app.utils.file_identity import (
    FileIdentityError,
    capture_sha256,
)

from app.analysis_engine.ffprobe_analyzer import (
    probe_file_summary,
)

from app.analysis_engine.media_classifier.evidence_builder import (
    ClassificationEvidenceBuilder,
)

from app.experts.source_expert import SourceExpert
from app.decision_engine.rules.source_rule import SourceRule


from app.decision_engine.decision_engine import DecisionEngine

from app.decision_engine.rules.codec_rule import (
    CodecRule
)

from app.decision_engine.rules.container_rule import (
    ContainerRule,
)

from app.decision_engine.rules.bitrate_rule import (
    BitrateRule
)

from app.decision_engine.rules.hdr_rule import (
    HDRRule
)
from app.decision_engine.rules.resolution_rule import (
    ResolutionRule
)
from app.decision_engine.rules.source_rule import (
    SourceRule
)
from app.decision_engine.rules.audio_rule import (
    AudioRule
)

from app.experts.container_expert import (
    ContainerExpert,
)

from app.experts.manager_expert import ExpertManager

from app.experts.classification_expert import (
    ClassificationExpert
)

from app.experts.codec_expert import (
    CodecExpert
)

from app.experts.audio_expert import (
    AudioExpert
)

from app.experts.hdr_expert import HDRExpert

from app.experts.quality_expert import (
    QualityExpert
)

from app.experts.resolution_expert import (
    ResolutionExpert
)

from app.utils.logger import logger

from app.models.media_context import (
    MediaContext
)

from app.models.analysis_context import (
    AnalysisContext
)

from app.models.user_policy import UserPolicy

from app.preferences.continuity import evaluate_scan

from app.services.recommendation_semantics_service import (
    RecommendationSemanticsService,
)

from app.services.savings_conversion import SavingsConversion



def select_source_from_evidence(evidence):
    source_evidence = sorted(
        evidence.by_domain("source"),
        key=lambda item: item.confidence,
        reverse=True,
    )

    return (
        source_evidence[0].value
        if source_evidence
        else None
    )


def save_to_db(
    files,
    database_path=None,
    scan_root=None,
    excluded_paths=None,
    user_policy=None,
    scan_id=None,
    preference_state=None,
):
    """
    Scan and analyse media files through the canonical pipeline.

    `user_policy` is an optional UserPolicy active for every run in
    this invocation. Policy is a decision input only: it never alters
    factual observations or expert conclusions. When omitted the
    standard default policy applies.

    `preference_state` is an optional accepted-preference input
    (`PreferenceScanState` from app.preferences.continuity). When
    supplied, each analysed file is evaluated through Phase 15F
    continuity and a covered file uses its derived effective
    policy; all other outcomes leave the policy unchanged. When
    omitted (the default) this step is skipped entirely and
    behaviour is unchanged.

    `scan_id` is an optional durable Scan identity opened by the
    application Scan boundary (ScanService). When provided, the
    pipeline records one scan_items grouping row per encountered file
    (outcome: analysed / reused / failed / skipped) and maintains the
    scan's useful counts. Scan creation/finalisation remains owned by
    the calling boundary; the pipeline never fabricates analysis runs
    merely to associate a file with a Scan (reused analyses stay
    reused).
    """

    enriched_list = []

    # -------------------------
    # Repository setup
    # -------------------------

    connection = get_connection(
        database_path
    )

    # -------------------------
    # Repository / shared-domain-service setup
    #
    # Repositories and the shared validity authority are wired by the
    # shared construction helper so that pipeline and GUI composition
    # have a single source of truth. Pipeline-specific authorities
    # (expert system, decision engine) are constructed here.
    # -------------------------

    graph = build_service_graph(
        connection
    )

    media_repository = graph.media_repository

    analysis_repository = graph.analysis_repository

    evidence_repository = graph.evidence_repository

    expert_result_repository = graph.expert_result_repository

    provenance_repository = graph.provenance_repository

    knowledge_repository = graph.knowledge_repository

    knowledge_service = graph.knowledge_service

    decision_signal_repository = graph.decision_signal_repository

    recommendation_repository = (
        graph.recommendation_repository
    )

    validity_service = graph.validity_service

    # -------------------------
    # Expert system setup
    # -------------------------

    expert_manager = ExpertManager([
        ClassificationExpert(),

        CodecExpert(
            knowledge_service
        ),

        AudioExpert(
            knowledge_service
        ),

        ResolutionExpert(
            knowledge_service
        ),

        HDRExpert(
            knowledge_service
        ),

        ContainerExpert(
            knowledge_service
        ),
        SourceExpert(
            knowledge_service
        ),

        QualityExpert(),
    ])

    # -------------------------
    # Decision Engine setup
    # -------------------------

    decision_engine = DecisionEngine(
        rules=[
            CodecRule(knowledge_service),
            BitrateRule(knowledge_service),
            ResolutionRule(knowledge_service),
            HDRRule(knowledge_service),
            ContainerRule(knowledge_service),
            SourceRule(knowledge_service),
            AudioRule(knowledge_service),
        ]
    )

    # -------------------------
    # Versioning / provenance
    #
    # Capture the semantic version manifest, policy values, and the Git
    # revision once for this pipeline invocation and reuse it for every
    # analysis run. The configuration snapshot is the immutable
    # run-level attribution record.
    # -------------------------

    component_versions = build_component_versions(
        expert_manager,
        decision_engine,
    )

    policy_values = build_policy_values(
        user_policy
    )

    git_revision = get_git_revision()

    # -------------------------
    # Intelligence applicability
    #
    # Separate concern from filesystem currentness: whether an
    # existing completed run was produced under the CURRENTLY
    # applicable intelligence (component versions, policy values
    # incl. active evidence weighting, consulted knowledge versions).
    # Irrelevant software/runtime changes never participate.
    # -------------------------

    applicability_service = RunApplicabilityService(
        provenance_repository=provenance_repository,
        knowledge_repository=knowledge_repository,
        current_component_versions=component_versions,
        current_policy_values=policy_values,
    )

    inserted = 0

    scan_analysed = 0
    scan_reused = 0
    scan_failed = 0
    scan_skipped = 0


    for f in files:

        analysis_run_id = None

        media_id = None

        file_observation_id = None


        try:


            # =========================
            # FFPROBE
            # =========================

            summary = probe_file_summary(
                f["path"]
            )


            if not summary:

                if scan_id is not None:

                    scan_skipped += 1

                    graph.scan_repository.record_item(
                        scan_id,
                        outcome="skipped",
                    )

                    graph.scan_repository.increment_counts(
                        scan_id,
                        skipped=1,
                    )

                    connection.commit()

                continue


            if not all(
                k in summary
                for k in [
                    "width",
                    "height",
                    "duration"
                ]
            ):

                if scan_id is not None:

                    scan_skipped += 1

                    graph.scan_repository.record_item(
                        scan_id,
                        outcome="skipped",
                    )

                    graph.scan_repository.increment_counts(
                        scan_id,
                        skipped=1,
                    )

                    connection.commit()

                continue



            # =========================
            # SIZE FACTS
            # =========================

            size_bytes = f.get(
                "size_bytes",
                0
            )


            size_mib = (
                round(
                    size_bytes / (1024 * 1024),
                    2
                )
                if size_bytes
                else None
            )


            size_gib = (
                round(
                    size_bytes / (1024 * 1024 * 1024),
                    2
                )
                if size_bytes
                else None
            )



            # =========================
            # BUILD IMMUTABLE MEDIA CONTEXT
            # =========================

            evidence = (
                ClassificationEvidenceBuilder()
                .build(
                    f["name"]
                )
            )

            source = select_source_from_evidence(
                evidence
            )

            context = MediaContext(

                path=f["path"],

                name=f["name"],

                extension=f.get(
                    "extension"
                ),

                container=summary.get(
                   "container"
                ),

                source=source,

                size_bytes=size_bytes,

                file_mtime_ns=f.get(
                    "file_mtime_ns"
                ),

                size_mib=size_mib,

                size_gib=size_gib,

                duration=summary.get(
                    "duration"
                ),

                bitrate=summary.get(
                    "bitrate"
                ),


                width=summary.get(
                    "width"
                ),

                height=summary.get(
                    "height"
                ),


                video_codec=summary.get(
                    "video_codec"
                ),


                audio_channels=summary.get(
                    "audio_tracks"
                ),

                audio_codec=summary.get(
                    "audio_codec"
                ),

                hdr_format=summary.get(
                    "hdr_format"
                ),

                raw_ffprobe=summary,

                raw_scanner=f
            )



            # =========================
            # CONTENT IDENTITY PREFLIGHT
            # =========================
            #
            # Candidate-bearing observations need SHA-256 content
            # identity. Hashing is performed only when a new analysis
            # is required, or when a current candidate must be
            # content-verified at the scan boundary. Reused
            # non-candidate analyses reuse a prior identity without a
            # full file read.
            #
            # The post-sync validity gate remains authoritative. This
            # preflight only decides whether a hash is needed before
            # the immutable observation is created.

            force_content_analysis = False
            content_identity_required = False

            existing_lineage = (
                media_repository.get_active_lineage_by_path(
                    context.path
                )
            )

            try:
                live_stat = os.stat(context.path)
            except OSError:
                live_stat = None

            scanner_matches_live = bool(
                live_stat is not None
                and live_stat.st_size == context.size_bytes
                and live_stat.st_mtime_ns
                == context.file_mtime_ns
            )

            prior_identity = None
            pre_validity = None
            pre_applicable = False

            if existing_lineage is not None:

                prior_identity = (
                    media_repository.get_latest_content_identity(
                        existing_lineage.id,
                        size_bytes=context.size_bytes,
                        file_mtime_ns=context.file_mtime_ns,
                    )
                )

                pre_validity = validity_service.get_validity(
                    existing_lineage.id,
                    current_size_bytes=context.size_bytes,
                    current_file_mtime_ns=context.file_mtime_ns,
                )

                if pre_validity.valid_analysis_run is not None:

                    pre_applicable = (
                        applicability_service.evaluate_run(
                            pre_validity.valid_analysis_run
                        ).applicable
                    )

            candidate_bearing = bool(
                pre_validity is not None
                and pre_validity.current_opportunity is not None
            )

            if pre_applicable and not candidate_bearing:

                # Reused analysis: carry forward an existing content
                # identity for the same fingerprint without rereading.
                if prior_identity is not None:
                    f["file_hash"] = prior_identity[0]

            else:

                # A new analysis is required, or a candidate must be
                # content-verified at the scan boundary.
                if scanner_matches_live:

                    try:

                        digest, live_stat = capture_sha256(
                            context.path,
                            expected_size_bytes=context.size_bytes,
                            expected_file_mtime_ns=(
                                context.file_mtime_ns
                            ),
                        )

                        f["file_hash"] = digest

                        if candidate_bearing:
                            if prior_identity is None:
                                force_content_analysis = True
                            elif digest != prior_identity[0]:
                                force_content_analysis = True

                    except FileIdentityError as error:

                        logger.warning(
                            f"Content identity unavailable for "
                            f"'{context.name}': {error}. "
                            "No hash will be attached to this "
                            "observation."
                        )

                else:

                    logger.warning(
                        f"Scanner fingerprint for '{context.name}' "
                        "does not match the live file; content "
                        "identity will not be attached to this "
                        "observation."
                    )


            media_id, scan_status, file_observation_id = (
                media_repository.sync_media(
                    context
                )
            )

            if content_identity_required:

                observation = (
                    media_repository.get_observation_by_id(
                        file_observation_id
                    )
                )

                if (
                    observation is None
                    or not observation.sha256_hash
                ):

                    scan_failed += 1

                    if scan_id is not None:

                        graph.scan_repository.record_item(
                            scan_id,
                            media_id=media_id,
                            file_observation_id=(
                                file_observation_id
                            ),
                            outcome="failed",
                        )

                        graph.scan_repository.increment_counts(
                            scan_id,
                            failed=1,
                        )

                    connection.commit()

                    logger.error(
                        f"Analysis skipped for '{context.name}': "
                        "the source content identity could not be "
                        "established reliably."
                    )

                    continue


            # =========================
            # ANALYSIS VALIDITY + APPLICABILITY GATE
            # =========================
            #
            # Two distinct questions, two distinct authorities:
            #
            # 1. Filesystem currentness (AnalysisValidityService,
            #    sole authority): does a completed run exist for the
            #    freshly scanned fingerprint?
            #
            # 2. Intelligence applicability (RunApplicabilityService):
            #    was that run produced under the currently applicable
            #    intelligence identity? Irrelevant software changes
            #    never invalidate; relevant intelligence/knowledge
            #    changes do.
            #
            #   reusable        -> skip intelligence
            #   not reusable    -> new run; old run fully preserved

            validity = validity_service.get_validity(
                media_id,
                current_size_bytes=context.size_bytes,
                current_file_mtime_ns=context.file_mtime_ns,
            )

            if validity.valid_analysis_run is not None:

                verdict = (
                    applicability_service.evaluate_run(
                        validity.valid_analysis_run
                    )
                )

                if verdict.applicable and not force_content_analysis:

                    if scan_id is not None:

                        scan_reused += 1

                        graph.scan_repository.record_item(
                            scan_id,
                            media_id=media_id,
                            file_observation_id=(
                                file_observation_id
                            ),
                            analysis_run_id=(
                                validity
                                .valid_analysis_run
                                .id
                            ),
                            outcome="reused",
                        )

                        graph.scan_repository.increment_counts(
                            scan_id,
                            reused=1,
                        )

                    connection.commit()

                    logger.info(
                        f"Reusable analysis exists for "
                        f"'{context.name}' "
                        f"(media_id={media_id}, run="
                        f"{validity.valid_analysis_run.id}, "
                        f"reason={verdict.reason}). "
                        f"Skipping analysis."
                    )

                    continue

                if force_content_analysis:

                    logger.info(
                        f"Content identity for '{context.name}' "
                        "changed or was missing for a current "
                        "candidate; a new analysis is required."
                    )

                else:

                    logger.info(
                        f"Existing analysis for '{context.name}' "
                        f"is not applicable "
                        f"(run={validity.valid_analysis_run.id}, "
                        f"reason={verdict.reason}); creating a new "
                        f"run. Previous run is preserved."
                    )

            else:

                logger.info(
                    f"No completed analysis for current "
                    f"filesystem state of '{context.name}' "
                    f"(media_id={media_id}); analysis required."
                )



            # =========================
            # PROVENANCE START
            # =========================

            analysis_run_id = (
                provenance_repository.begin_run(
                    media_id=media_id,

                    file_observation_id=file_observation_id,

                    configuration={
                        "pipeline_version":
                            PIPELINE_VERSION,

                        "experts": [
                            expert.name
                            for expert in expert_manager.experts
                        ],

                        "decision_rules": [
                            rule.name
                            for rule in decision_engine.rules
                        ],

                        "component_versions":
                            component_versions,

                        "policy_values":
                            policy_values,

                        "git_revision":
                            git_revision,
                    },

                    scanner_input=f
                )
            )


            provenance_repository.start_run(
                analysis_run_id
            )



            # =========================
            # BUILD ANALYSIS CONTEXT
            # =========================

            evidence_repository.save(
                analysis_run_id,
                evidence
            )


            base_policy = (
                user_policy
                if user_policy is not None
                else UserPolicy.default()
            )


            # -------------------------
            # Phase 15F continuity: when accepted preference
            # state is supplied, evaluate this file's facts and
            # narrow the per-file policy through the existing
            # derivation. Covered files use the derived effective
            # policy; every other outcome keeps the base policy.
            # Accepted preference records are read-only inputs
            # here: nothing is accepted, mutated, or persisted by
            # this step. Without preference state this block is
            # skipped entirely.
            # -------------------------

            effective_policy = base_policy

            if preference_state is not None:

                preference_facts = {
                    key: value
                    for key, value in (
                        ("resolution", context.height),
                        ("codec", context.video_codec),
                        ("bitrate_class", context.bitrate),
                        ("container", context.container),
                        ("audio_codec", context.audio_codec),
                        ("hdr", context.hdr_format),
                        ("source_label", context.source),
                        ("size_class", context.size_bytes),
                        ("audio_channels", context.audio_channels),
                    )
                    if value is not None
                }

                continuity_outcomes = evaluate_scan(
                    files=[{
                        "media_id": str(media_id),
                        "facts": preference_facts,
                    }],
                    rules=preference_state.rules,
                    explicit_scopes=preference_state.explicit_scopes,
                    intent=preference_state.intent,
                    base_policy=base_policy,
                    prior_fingerprints=dict(
                        preference_state.prior_fingerprints
                    ),
                ).outcomes

                if continuity_outcomes:
                    file_outcome = continuity_outcomes[0]

                    if (
                        file_outcome.action == "apply"
                        and file_outcome.effective_policy
                        is not None
                    ):
                        effective_policy = (
                            file_outcome.effective_policy
                        )


            analysis_context = AnalysisContext(

                media=context,

                evidence=evidence,

                policy=effective_policy,
            )


            expert_results = (
                expert_manager.run(
                    analysis_context
                )
            )


            analysis_context.expert_results = (
                expert_results
            )

            expert_result_repository.save(
                analysis_run_id,
                expert_results
            )

            # =========================
            # DECISION ENGINE
            # =========================

            assessment = (
                decision_engine.evaluate(
                    analysis_context
                )
            )

            # A run with no decision signals still completes as a
            # valid analysis (FusionEngine returns None when there
            # are no signals). Absence of an opportunity must not
            # fail the run or mark it incomplete.
            decision_signal_repository.save(
                analysis_run_id,
                assessment.signals
                if assessment is not None
                else []
            )

            analysis_context.assessment = (
                assessment
            )



            # =========================
            # BUILD OUTPUT
            # =========================

            enriched = {

                **f,

                **summary,


                "size_bytes":
                    size_bytes,

                "size_mib":
                    size_mib,

                "size_gib":
                    size_gib,


                "classification": {

                    "experts": [

                        r.to_dict()

                        for r in expert_results
                    ]
                },


                "experts": [

                    r.to_dict()

                    for r in expert_results
                ],



                "assessment": (

                    {
                        "opportunity":
                            assessment.opportunity,

                        "opportunity_level":
                            assessment.opportunity_level,

                        "priority_label":
                            assessment.priority_label,

                        "confidence":
                            assessment.confidence,

                        "opportunity_score":
                            assessment.opportunity_score,

                        "estimated_saving_percent":
                            assessment.estimated_saving_percent,

                        "expected_saved_bytes":
                            assessment.expected_saved_bytes,

                        "benefit":
                            assessment.benefit,

                        "cost":
                            assessment.cost,

                        "evidence":
                            assessment.evidence,

                        "reasoning":
                            assessment.reasoning,

                        "preservation_reasons":
                            assessment.preservation_reasons,

                        "suppressed_signals":
                            assessment.suppressed_signals,

                        "contributing_rules":
                            assessment.contributing_rules,

                        "risk":
                            assessment.risk,

                        "signals": [
                            {
                                "rule": signal.rule,
                                "opportunity_score": signal.opportunity_score,
                                "confidence": signal.confidence,
                                "direction": signal.direction,
                                "proposition": signal.proposition,
                                "current_state": signal.current_state,
                                "target_state": signal.target_state,
                                "benefit": signal.benefit,
                                "cost": signal.cost,
                                "risk": signal.risk,
                                "reason": signal.reason,
                                "notes": signal.notes,
                                "evidence": signal.evidence,
                                "provenance": signal.provenance,
                            }

                            for signal in assessment.signals
                        ],

                        "constraints": list(
                            assessment.constraints or []
                        ),

                    }

                    if assessment

                    else None
                )

            }



            # =========================
            # SAVE ANALYSIS
            # =========================

            analysis_repository.save_analysis(
                context=analysis_context,

                media_id=media_id,

                analysis_run_id=analysis_run_id
            )

            provenance_repository.record_knowledge_usage(
                analysis_run_id,
                analysis_context.knowledge_usage
            )

            # =========================
            # INTELLIGENCE IDENTITY
            #
            # Recorded once the run's consulted knowledge sets are
            # known, so the digest covers exactly the relevant
            # knowledge versions alongside component versions and
            # policy values (incl. active evidence weighting). Git
            # revision is deliberately excluded: irrelevant software
            # changes must never invalidate analyses.
            # =========================

            consulted_knowledge_versions = {}

            for usage in (
                analysis_context.knowledge_usage
            ):

                resolved = (
                    knowledge_repository
                    .get_set_name_and_version(
                        usage.knowledge_set_id
                    )
                )

                if resolved is not None:

                    consulted_knowledge_versions[
                        resolved[0]
                    ] = resolved[1]

            intelligence_identity = (
                intelligence_identity_digest(
                    component_versions,
                    policy_values,
                    consulted_knowledge_versions,
                )
            )

            provenance_repository \
                .record_intelligence_identity(
                    analysis_run_id,
                    intelligence_identity,
                )

            # =========================
            # PERSIST RECOMMENDATION
            #
            # The recommendation is a durable historical result of
            # THIS run, preserving the analytical outcome as produced
            # (never re-derived from later intelligence).
            # =========================

            if assessment is not None:

                # The recommendation is the human-readable
                # interpretation of the opportunity assessment. Only a
                # genuine opportunity produces a durable
                # recommendation; a "no worthwhile improvement"
                # conclusion is preserved through the run's decision
                # signals.
                if assessment.opportunity_level != "none":

                    narrative = RecommendationSemanticsService.narrative(
                        assessment,
                        policy_payload=policy_values.get(
                            "user_policy",
                            None,
                        ),
                    )

                    summary = (
                        RecommendationSemanticsService.summary(
                            assessment
                        )
                    )

                    recommendation_repository.create_proposed(
                    media_id=media_id,

                    analysis_run_id=analysis_run_id,

                    file_observation_id=(
                        file_observation_id
                    ),

                    opportunity=(
                        assessment.opportunity
                    ),

                    opportunity_score=(
                        assessment.opportunity_score
                    ),

                    confidence=assessment.confidence,

                    estimated_saving_percent=(
                        assessment.estimated_saving_percent
                    ),

                    estimated_saved_bytes=(
                        assessment.expected_saved_bytes
                        if assessment.expected_saved_bytes is not None
                        # Owned historical fallback: the single
                        # shared percent-derived formula (Phase 9).
                        else SavingsConversion.historical_fallback(
                            assessment.estimated_saving_percent,
                            size_bytes,
                        )
                    ),

                    risk=assessment.risk,

                    rationale=list(narrative),

                    contributing_rules=list(
                        assessment.contributing_rules or []
                    ),

                    intelligence_identity=(
                        intelligence_identity
                    ),

                    opportunity_level=(
                        assessment.opportunity_level
                    ),

                    summary=summary,
                )

            provenance_repository.complete_run(
                analysis_run_id
            )

            if scan_id is not None:

                scan_analysed += 1

                graph.scan_repository.record_item(
                    scan_id,
                    media_id=media_id,
                    file_observation_id=(
                        file_observation_id
                    ),
                    analysis_run_id=analysis_run_id,
                    outcome="analysed",
                )

                graph.scan_repository.increment_counts(
                    scan_id,
                    analysed=1,
                )


            connection.commit()


            inserted += 1


            enriched_list.append(
                enriched
            )



        except Exception as e:


            if analysis_run_id:

                provenance_repository.fail_run(
                    analysis_run_id,

                    str(e)
                )

                connection.commit()


            if scan_id is not None:

                scan_failed += 1

                graph.scan_repository.record_item(
                    scan_id,
                    media_id=media_id,
                    file_observation_id=(
                        file_observation_id
                    ),
                    analysis_run_id=analysis_run_id,
                    outcome="failed",
                )

                graph.scan_repository.increment_counts(
                    scan_id,
                    failed=1,
                )

                connection.commit()



            logger.exception(
                f"Pipeline error processing "
                f"{f.get('path')}"
            )


            print(
                "\n❌ PIPELINE ERROR"
            )

            print(
                "File:",
                f.get("path")
            )

            print(
                "Error:",
                str(e)
            )


            continue



    # =========================
    # EXISTENCE RECONCILIATION
    # =========================
    #
    # A completed scan is authoritative for its root: every active
    # lineage under scan_root that was NOT present in this scan's
    # result set has disappeared and must be marked missing.
    #
    # This is the existence-lifecycle counterpart to the analysis
    # validity gate: AnalysisValidityService is authoritative for
    # "valid analysis", while reconciliation makes media_items.status
    # authoritative for "media exists".
    #
    # Reconciliation ONLY transitions media_items.status. It never
    # mutates observations, runs, evidence, expert results, decision
    # signals, or opportunity assessments.
    #
    # When no scan_root is supplied (e.g. callers that pass files
    # directly) no reconciliation occurs, preserving existing
    # behaviour.

    if scan_root is not None:

        if excluded_paths is None:

            excluded_paths = get_excluded_paths()

        seen_paths = {
            f["path"]
            for f in files
        }

        media_repository.reconcile_existing_paths(
            scan_root=scan_root,
            seen_paths=seen_paths,
            excluded_paths=excluded_paths,
        )

        connection.commit()



    print(
        f"Inserted {inserted} new files into database"
    )

    # =========================
    # SCAN COUNTS
    #
    # When a durable Scan identity was opened by the calling boundary,
    # record the useful scan counts before the connection closes. The
    # terminal status is finalised by the boundary that owns the Scan
    # lifecycle (the pipeline never invents a completed outcome).
    # =========================

    if scan_id is not None:

        graph.scan_repository.set_counts(
            scan_id,
            files_discovered=len(files),
            files_analysed=scan_analysed,
            files_reused=scan_reused,
            files_failed=scan_failed,
            files_skipped=scan_skipped,
        )

        connection.commit()


    connection.close()


    return enriched_list