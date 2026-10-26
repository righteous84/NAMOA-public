"""
NAMOA operational CLI.

Sprint 8 operational workflows over the application-service boundary.
Every command consumes application services exclusively; this module
must never import scanner internals, database repositories, the
persistence pipeline, or intelligence-engine internals (enforced by
scripts/test_sprint8_cli.py).

Entry point: run(argv, services_factory=build_services) -> exit code.

Lifecycle/bootstrap commands that are NOT operational workflows
(migrate: schema bootstrap; serve: GUI launch) remain in app/main.py.
"""

import json
import sys

from app.application.composition import build_services

from app.application.queue_manifest import (
    build_queue_manifest,
)


# ---------------------------------------------------------
# formatting helpers (deliberately small)
# ---------------------------------------------------------

def _fmt_bytes(count):

    if count is None:

        return "-"

    step = 1024.0

    value = float(count)

    for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:

        if value < step:

            return f"{value:.1f} {unit}"

        value /= step

    return f"{value:.1f} PiB"


def _print_table(rows, headers):

    if not rows:

        print("(none)")

        return

    widths = []

    for column, header in enumerate(headers):

        width = len(str(header))

        for row in rows:

            cell = str(row[column])

            if len(cell) > width:

                width = len(cell)

        widths.append(width)

    line = "  ".join(
        str(header).ljust(widths[index])
        for index, header in enumerate(headers)
    )

    print(line)

    print("  ".join("-" * width for width in widths))

    for row in rows:

        print(
            "  ".join(
                str(cell).ljust(widths[index])
                for index, cell in enumerate(row)
            )
        )


def _emit(payload, *, as_json, human_renderer):

    if as_json:

        print(json.dumps(payload, indent=2))

    else:

        human_renderer()


# ---------------------------------------------------------
# command implementations (services only)
# ---------------------------------------------------------

def cmd_scan(services, args):

    as_json = "--json" in args

    positional = [
        arg for arg in args if not arg.startswith("--")
    ]

    if len(positional) != 1:

        raise _UsageError("scan <path>")

    path = positional[0]

    report = services.scan_service.scan_with_report(path)

    def human():

        print(f"Scan complete: {report['path']}")

        print(
            f"  files discovered: "
            f"{report['files_discovered']}"
        )

        print(
            f"  analyses persisted: "
            f"{report['persisted_count']}"
        )

    _emit(report, as_json=as_json, human_renderer=human)

    return 0


def cmd_status(services, args):

    as_json = "--json" in args

    entries = services.library_service.get_lineage_statuses()

    def human():

        rows = [
            (
                entry.media_id,
                entry.file_name or "-",
                entry.media_status,
                entry.validity_reason,
                "yes" if entry.analysis_required else "no",
            )
            for entry in entries
        ]

        print("Analysis status per lineage:")

        _print_table(
            rows,
            [
                "id",
                "name",
                "status",
                "validity",
                "analysis required",
            ],
        )

    _emit(
        {
            "lineages": [
                {
                    "media_id": entry.media_id,
                    "file_name": entry.file_name,
                    "media_status": entry.media_status,
                    "validity_reason": entry.validity_reason,
                    "analysis_required": (
                        entry.analysis_required
                    ),
                    "is_stale": entry.is_stale,
                }
                for entry in entries
            ]
        },
        as_json=as_json,
        human_renderer=human,
    )

    return 0


def cmd_media(services, args):

    as_json = "--json" in args

    positional = [
        arg for arg in args if not arg.startswith("--")
    ]

    if len(positional) > 1:

        raise _UsageError("media [id]")

    if positional:

        media_id = int(positional[0])

        item = services.media_service.get_media_item(media_id)

        history = (
            services.media_service.get_observation_history(
                media_id
            )
        )

        payload = {
            "id": item.id,
            "file_path": item.file_path,
            "file_name": item.file_name,
            "status": item.status,
            "file_size_bytes": item.file_size_bytes,
            "observations": len(history.observations),
        }

        def human():

            print(f"Media {item.id}: {item.file_name}")

            print(f"  path: {item.file_path}")

            print(f"  status: {item.status}")

            print(
                f"  size: {_fmt_bytes(item.file_size_bytes)}"
            )

            print(
                f"  observations: {len(history.observations)}"
            )

        _emit(payload, as_json=as_json, human_renderer=human)

        return 0

    lineages = services.media_service.get_active_lineages()

    def human_list():

        rows = [
            (
                item.id,
                item.file_name,
                _fmt_bytes(item.file_size_bytes),
            )
            for item in lineages
        ]

        print(f"{len(lineages)} active lineages:")

        _print_table(rows, ["id", "name", "size"])

    _emit(
        {
            "active_lineages": [
                {
                    "id": item.id,
                    "file_path": item.file_path,
                    "file_name": item.file_name,
                    "file_size_bytes": item.file_size_bytes,
                }
                for item in lineages
            ]
        },
        as_json=as_json,
        human_renderer=human_list,
    )

    return 0


def cmd_recommendations(services, args):

    as_json = "--json" in args

    prioritised = (
        services.recommendation_service
        .get_prioritised_recommendations()
    )

    sets = services.recommendation_service.get_recommendation_sets()

    projection = (
        services.recommendation_service.get_savings_projection()
    )

    def human():

        rows = []

        for item in prioritised:

            candidate = item.candidate

            rows.append(
                (
                    item.rank,
                    candidate.file_name,
                    candidate.opportunity,
                    f"{item.priority_score:.3f}",
                    _fmt_bytes(candidate.estimated_saved_bytes),
                )
            )

        print("Prioritised recommendations:")

        _print_table(
            rows,
            ["rank", "name", "opportunity", "priority", "saved"],
        )

        print("")

        print("Recommendation sets:")

        for set_item in sets:

            print(
                f"  {set_item.name}: {set_item.count} items, "
                f"{_fmt_bytes(set_item.total_saved_bytes)} "
                f"potential savings"
            )

        print("")

        print(
            f"Savings projection: "
            f"{projection.total_opportunities} opportunities, "
            f"{_fmt_bytes(projection.total_saved_bytes)} total "
            f"potential savings"
        )

    _emit(
        {
            "prioritised": [
                {
                    "rank": item.rank,
                    "media_id": item.candidate.media_id,
                    "file_name": item.candidate.file_name,
                    "opportunity": item.candidate.opportunity,
                    "priority_score": item.priority_score,
                    "estimated_saved_bytes": (
                        item.candidate.estimated_saved_bytes
                    ),
                }
                for item in prioritised
            ],
            "sets": [
                {
                    "name": set_item.name,
                    "count": set_item.count,
                    "total_saved_bytes": (
                        set_item.total_saved_bytes
                    ),
                }
                for set_item in sets
            ],
            "projection": {
                "total_opportunities": (
                    projection.total_opportunities
                ),
                "total_saved_bytes": (
                    projection.total_saved_bytes
                ),
            },
        },
        as_json=as_json,
        human_renderer=human,
    )

    return 0


def cmd_queue(services, args):

    as_json = "--json" in args

    queue = services.recommendation_service.get_current_queue()

    def human():

        rows = [
            (
                candidate.media_id,
                candidate.file_name,
                candidate.opportunity,
                f"{candidate.opportunity_score:.3f}",
                _fmt_bytes(candidate.estimated_saved_bytes),
            )
            for candidate in queue
        ]

        print(f"Current-valid opportunity queue ({len(queue)}):")

        _print_table(
            rows,
            ["id", "name", "opportunity", "score", "saved"],
        )

    _emit(
        {
            "queue": [
                {
                    "media_id": candidate.media_id,
                    "file_path": candidate.file_path,
                    "opportunity": candidate.opportunity,
                    "opportunity_score": (
                        candidate.opportunity_score
                    ),
                    "estimated_saved_bytes": (
                        candidate.estimated_saved_bytes
                    ),
                    "risk": candidate.risk,
                }
                for candidate in queue
            ]
        },
        as_json=as_json,
        human_renderer=human,
    )

    return 0


def cmd_explain(services, args):

    as_json = "--json" in args

    positional = [
        arg for arg in args if not arg.startswith("--")
    ]

    if len(positional) != 1:

        raise _UsageError("explain <run_id>")

    explanation = services.provenance_service.explain(
        int(positional[0])
    )

    def human():

        print(f"Explanation: {explanation.summary}")

        print("")

        print("Expert contributions:")

        for line in explanation.expert_contributions:

            print(f"  - {line}")

        print("Evidence:")

        for line in explanation.evidence_summary:

            print(f"  - {line}")

        print("Decisions:")

        for line in explanation.decision_summary:

            print(f"  - {line}")

        print("Knowledge:")

        for line in explanation.knowledge_summary:

            print(f"  - {line}")

        print(f"Confidence: {explanation.confidence_summary}")

    _emit(
        {
            "summary": explanation.summary,
            "expert_contributions": list(
                explanation.expert_contributions
            ),
            "evidence_summary": list(
                explanation.evidence_summary
            ),
            "decision_summary": list(
                explanation.decision_summary
            ),
            "knowledge_summary": list(
                explanation.knowledge_summary
            ),
            "confidence_summary": (
                explanation.confidence_summary
            ),
        },
        as_json=as_json,
        human_renderer=human,
    )

    return 0


def cmd_provenance(services, args):

    as_json = "--json" in args

    positional = [
        arg for arg in args if not arg.startswith("--")
    ]

    if len(positional) != 1:

        raise _UsageError("provenance <run_id>")

    provenance = (
        services.provenance_service.get_analysis_provenance(
            int(positional[0])
        )
    )

    run = provenance.analysis_run

    def human():

        print(f"Provenance for analysis run {run.id}")

        print(f"  state: {getattr(run, 'state', '-')}")

        print(
            f"  evidence records: "
            f"{len(provenance.evidence)}"
        )

        print(
            f"  expert results: "
            f"{len(provenance.expert_results)}"
        )

        print(
            f"  decision signals: "
            f"{len(provenance.decision_signals)}"
        )

        opportunity = provenance.opportunity_assessment

        if opportunity is not None:

            print("  opportunity assessment: present")

        else:

            print("  opportunity assessment: none")

        print(
            f"  knowledge versions used: "
            f"{len(provenance.knowledge_usage)}"
        )

    _emit(
        {
            "analysis_run_id": run.id,
            "evidence_count": len(provenance.evidence),
            "expert_result_count": len(
                provenance.expert_results
            ),
            "decision_signal_count": len(
                provenance.decision_signals
            ),
            "has_opportunity_assessment": (
                provenance.opportunity_assessment is not None
            ),
            "knowledge_usage_count": len(
                provenance.knowledge_usage
            ),
        },
        as_json=as_json,
        human_renderer=human,
    )

    return 0


def cmd_library(services, args):

    as_json = "--json" in args

    statistics = services.library_service.get_statistics()

    storage = services.library_service.get_storage_consumption()

    health = services.library_service.get_library_health()

    def human():

        print("Library intelligence:")

        print(
            f"  lineages: {statistics.active_lineages} active, "
            f"{statistics.missing_lineages} missing"
        )

        print(
            f"  analysed: {statistics.analysed_lineages} / "
            f"{statistics.active_lineages} "
            f"({statistics.analysis_coverage_percent:.1f}%)"
        )

        print(f"  stale analyses: {statistics.stale_analyses}")

        print(
            f"  storage consumed: "
            f"{_fmt_bytes(storage.total_library_bytes)}"
        )

        print(f"  overall health: {health.status}")

    _emit(
        {
            "statistics": {
                "active_lineages": (
                    statistics.active_lineages
                ),
                "missing_lineages": (
                    statistics.missing_lineages
                ),
                "analysed_lineages": (
                    statistics.analysed_lineages
                ),
                "stale_analyses": statistics.stale_analyses,
                "analysis_coverage_percent": (
                    statistics.analysis_coverage_percent
                ),
            },
            "storage_total_bytes": storage.total_library_bytes,
            "health_status": health.status,
        },
        as_json=as_json,
        human_renderer=human,
    )

    return 0


def cmd_analyse(services, args):

    positional = [
        arg for arg in args if not arg.startswith("--")
    ]

    if len(positional) != 1:

        raise _UsageError("analyse <media_id>")

    media_id = int(positional[0])

    results = services.analysis_service.analyze_lineage(
        media_id
    )

    print(f"Targeted analysis complete for lineage {media_id}")

    print(f"  files processed: {len(results)}")

    print(
        "  currentness was decided by the validity gate "
        "(already-valid analysis skips)"
    )

    return 0


def cmd_export(services, args):

    positional = [
        arg for arg in args if not arg.startswith("--")
    ]

    if len(positional) > 1:

        raise _UsageError("export [destination|'-']")

    manifest = build_queue_manifest(
        services.recommendation_service
    )

    payload = json.dumps(manifest, indent=2)

    if not positional or positional[0] == "-":

        print(payload)

        return 0

    destination = positional[0]

    with open(destination, "w", encoding="utf-8") as handle:

        handle.write(payload)

        handle.write("\n")

    print(f"Queue manifest written: {destination}")

    print(
        f"  proposals: {manifest['summary']['count']} "
        f"(non-destructive; derived from current-valid reads)"
    )

    return 0


def cmd_execute(services, args):

    positional = [
        arg for arg in args if not arg.startswith("--")
    ]

    flags = {
        arg.split("=", 1)[0][2:]: (
            arg.split("=", 1)[1]
            if "=" in arg
            else None
        )
        for arg in args
        if arg.startswith("--")
    }

    if not positional:

        raise _UsageError(
            "execute <approve|plan|run|status|rollback|recover> "
            "<id> [--by NAME]"
        )

    sub, rest = positional[0], positional[1:]

    executions = services.execution_service

    if sub == "approve":

        if len(rest) != 1:

            raise _UsageError(
                "execute approve <media_id> [--by NAME]"
            )

        approved_by = flags.get("by") or "human"

        job_id = executions.approve(
            int(rest[0]),
            approved_by=approved_by,
        )

        job = executions.get(job_id)

        print(f"Execution {job.id} APPROVED")

        print(f"  media: {job.media_id} ({job.source_path})")

        print(
            f"  fingerprint frozen: "
            f"{job.source_size_bytes} bytes / "
            f"{job.source_mtime_ns} mtime"
        )

        print("next: execute plan "
              f"{job.id} && execute run {job.id}")

        return 0

    if sub == "plan":

        if len(rest) != 1:

            raise _UsageError("execute plan <job_id>")

        job = executions.plan(int(rest[0]))

        print(f"Execution {job.id} PLANNED")

        print(f"  operation: {job.plan.get('operation')}")

        print(f"  argv: {job.plan.get('argv')}")

        return 0

    if sub == "run":

        if len(rest) != 1:

            raise _UsageError("execute run <job_id>")

        job = executions.run(int(rest[0]))

        print(f"Execution {job.id}: {job.state.upper()}")

        if job.error:

            print(f"  detail: {job.error}")

        if job.state == "succeeded":

            print(
                f"  result observation: "
                f"{job.result_observation_id}"
            )

            print(f"  output sha256: {job.output_sha256}")

            print(
                f"  original preserved at: "
                f"{job.backup_path} (rollback available)"
            )

        return 0

    if sub == "status":

        if rest:

            job = executions.get(int(rest[0]))

            jobs = [job]

        else:

            jobs = executions.list_jobs()

        rows = [
            (
                job.id,
                job.media_id,
                job.state,
                (job.opportunity or "-"),
                (job.error or "-")[:60],
            )
            for job in jobs
        ]

        _print_table(
            rows,
            ["job", "media", "state", "opportunity", "note"],
        )

        return 0

    if sub == "rollback":

        if len(rest) != 1:

            raise _UsageError("execute rollback <job_id>")

        job = executions.rollback(int(rest[0]))

        print(f"Execution {job.id}: ROLLED_BACK")

        print(
            "  original restored; restoration recorded as a "
            "new filesystem observation"
        )

        return 0

    if sub == "recover":

        if len(rest) != 1:

            raise _UsageError("execute recover <job_id>")

        job = executions.recover(int(rest[0]))

        print(f"Execution {job.id}: RECOVERED")

        print(f"  detail: {job.error}")

        return 0

    raise _UsageError(
        f"unknown execute action '{sub}'"
    )


class _UsageError(Exception):
    """Raised when a command's arguments are invalid."""


def cmd_organise(services, args):
    """
    Organisation execution (Sprint 14): safely execute an approved
    organisation proposal, or reconcile an interrupted one.

    organise execute <proposal_id> [--by NAME]
    organise recover <execution_id>
    organise status [execution_id]
    """

    positional = [
        arg for arg in args if not arg.startswith("--")
    ]

    flags = {
        arg.split("=", 1)[0][2:]: (
            arg.split("=", 1)[1]
            if "=" in arg
            else None
        )
        for arg in args
        if arg.startswith("--")
    }

    if not positional:

        raise _UsageError(
            "organise <execute|recover|status> ..."
        )

    sub, rest = positional[0], positional[1:]

    executions = services.organisation_execution_service

    if sub == "execute":

        if len(rest) != 1:

            raise _UsageError(
                "organise execute <proposal_id> [--by NAME]"
            )

        actor = flags.get("by") or "human"

        record = executions.execute(
            int(rest[0]),
            actor=actor,
        )

        print(
            f"Organisation execution {record.id}: "
            f"{record.state.upper()}"
        )

        print(
            f"  media: {record.media_id} "
            f"({record.source_path} -> {record.destination_path})"
        )

        if record.state == "succeeded":

            print(
                f"  result observation: "
                f"{record.result_observation_id}"
            )

            print(f"  continuity id: {record.continuity_id}")

        if record.error:

            print(f"  detail: {record.error}")

        return 0

    if sub == "recover":

        if len(rest) != 1:

            raise _UsageError("organise recover <execution_id>")

        record = executions.recover(int(rest[0]))

        print(
            f"Organisation execution {record.id}: "
            f"{record.state.upper()}"
        )

        if record.error:

            print(f"  detail: {record.error}")

        return 0

    if sub == "status":

        if rest:

            records = [executions.get(int(rest[0]))]

        else:

            records = executions.list()

        rows = [
            (
                record.id,
                record.proposal_id,
                record.media_id,
                record.state,
                (record.error or "-")[:60],
            )
            for record in records
        ]

        _print_table(
            rows,
            ["exec", "proposal", "media", "state", "note"],
        )

        return 0

    raise _UsageError(
        f"unknown organise action '{sub}'"
    )


COMMANDS = {
    "scan": (
        cmd_scan,
        "scan <path> [--json]",
        "scan a library path and persist results (existence "
        "reconciliation included)",
    ),
    "status": (
        cmd_status,
        "status [--json]",
        "per-lineage analysis status (current/stale/unanalysed/"
        "missing)",
    ),
    "media": (
        cmd_media,
        "media [id] [--json]",
        "list active lineages or show one lineage's detail",
    ),
    "recommendations": (
        cmd_recommendations,
        "recommendations [--json]",
        "prioritised recommendations, standard sets, and savings "
        "projection",
    ),
    "queue": (
        cmd_queue,
        "queue [--json]",
        "the current-valid opportunity queue",
    ),
    "explain": (
        cmd_explain,
        "explain <run_id> [--json]",
        "human-readable explanation of one analysis run",
    ),
    "provenance": (
        cmd_provenance,
        "provenance <run_id> [--json]",
        "provenance summary for one analysis run",
    ),
    "library": (
        cmd_library,
        "library [--json]",
        "library-intelligence overview",
    ),
    "analyse": (
        cmd_analyse,
        "analyse <media_id>",
        "targeted re-analysis of one lineage (validity gate "
        "respected; no forcing)",
    ),
    "export": (
        cmd_export,
        "export [destination|'-']",
        "write the non-destructive queue manifest as JSON "
        "('-' for stdout)",
    ),
    "execute": (
        cmd_execute,
        "execute <approve|plan|run|status|rollback|recover> ...",
        "explicitly approved, non-destructive-until-verified "
        "optimisation execution",
    ),
    "organise": (
        cmd_organise,
        "organise <execute|recover|status> ...",
        "organisation execution of an approved proposal "
        "(safe move/rename with verification and continuity)",
    ),
}


def usage_text():

    lines = [
        "NAMOA operational commands:",
        "",
    ]

    for name in COMMANDS:

        _, usage, help_text = COMMANDS[name]

        lines.append(f"  {usage}")
        lines.append(f"      {help_text}")

    lines.extend(
        [
            "",
            "Lifecycle commands live in app/main.py:",
            "migrate, serve.",
        ]
    )

    return "\n".join(lines)


def run(argv, services_factory=None):

    """
    Execute one operational CLI invocation and return the process
    exit code (0 success, 1 failure, 2 usage error).
    """

    factory = services_factory or build_services

    if not argv or argv[0] in ("--help", "-h", "help"):

        print(usage_text())

        return 0

    name = argv[0]

    entry = COMMANDS.get(name)

    if entry is None:

        print(
            f"error: unknown command '{name}'",
            file=sys.stderr,
        )

        print(usage_text(), file=sys.stderr)

        return 2

    handler = entry[0]

    try:

        services = factory()

        return handler(services, argv[1:])

    except _UsageError as error:

        print(
            f"error: expected arguments: {error.args[0]}",
            file=sys.stderr,
        )

        return 2

    except ValueError as error:

        print(f"error: {error}", file=sys.stderr)

        return 1
