"""
HTTP server for the NAMOA GUI (Sprint 6.12).

Standard-library-only (http.server). Routing is explicit; handlers
consume the wired application services; errors are consistent and
never expose persistence internals.

Routes:

    GET  /                        dashboard
    GET  /media                   media inventory
    GET  /media/<id>              media detail
    GET  /analysis                analysis status
    GET  /scan                    scan page (form)
    POST /scan                    start a background scan
                                  (GUI/UX Phase 5)
    GET  /intelligence            library intelligence
    GET  /opportunities           recommendation list
    GET  /opportunities/<id>      opportunity detail
    GET  /recommendations/<id>    durable recommendation record
                                  detail (Sprint 11)
    POST /opportunities/accept-selected
                                  confirmation step for the
                                  selected recommendations
                                  (no side effects; Sprint 11)
    POST /opportunities/confirm-acceptance
                                  perform the confirmed batch
                                  approval via ExecutionService
                                  (Sprint 11)
    GET  /preferences             Preference Centre (Phase 16)
    GET  /preferences/wizard      Preference Wizard (Phase 16;
                                  ?session= resumes a live session)
    GET  /preferences/review      preference suggestion review
                                  (Phase 16)
    POST /preferences/wizard/start
                                  open a wizard session from the
                                  intent triple (Phase 16)
    POST /preferences/wizard/answer
                                  record one explicit answer
                                  (Phase 16)
    POST /preferences/wizard/undo finish, cancel, save
                                  session navigation and review
                                  handoff (Phase 16)
    POST /preferences/review/refresh
                                  generate suggestions from
                                  accepted rules (Phase 16)
    POST /preferences/review/accept, reject, change,
         reopen, accept-all       durable review lifecycle
                                  transitions (Phase 16)
    GET  /organisation            organisation proposals view
                                  (Sprint 13)
    GET  /organisation/proposals/<id>
                                  durable organisation proposal
                                  detail (Sprint 13)
    POST /organisation/generate   run one deterministic,
                                  non-destructive organisation
                                  decision pass (Sprint 13)
    POST /organisation/accept-selected
                                  confirmation step for selected
                                  proposals (no side effects;
                                  Sprint 13)
    POST /organisation/confirm-acceptance
                                  record durable acceptance of
                                  the confirmed proposals via
                                  OrganisationService; ZERO
                                  filesystem effect (Sprint 13)
    GET  /runs                    analysis history
    GET  /runs/<id>               run provenance/explanation
    GET  /runs/<id>/compare       comparison view (with=run id)
    GET  /executions              optimisation queue (Sprint 9
                                  executions, grouped Sprint 11)
    GET  /executions/<id>         execution detail
    POST /executions/<id>/run     run one approved execution
    POST /executions/<id>/rollback
                                  revert a succeeded execution
    POST /media/<id>/analyse      targeted analysis (validity gate
                                  respected; Sprint 8)
    GET  /queue-export            queue manifest download
                                  (non-destructive; Sprint 8)
    GET  /api/...                 JSON mirrors of the page data
    GET  /static/...              css / js

The /api/... surface is an INTERNAL, unofficial JSON mirror of the
page handlers. It is not a versioned public API and carries no
stability guarantee (Sprint 8 Phase 4 decision).
"""

import json
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from app.web import handlers
from app.web import templates

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Background scans run off the request path; SCAN_LOCK serialises the
# pipeline writes so concurrent scans cannot interleave them.
SCAN_LOCK = threading.Lock()

# GUI/UX Phase 5: background scan execution. One scan runs at a time
# per server process; a second scan request is refused honestly while
# one is running. This preserves SCAN_LOCK serialisation (concurrent
# scans can never interleave pipeline writes) without piling up
# blocked worker threads.
_ACTIVE_SCANS = {}

_ACTIVE_SCANS_LOCK = threading.Lock()

# POST /executions/<id>/run executes FFmpeg synchronously; a lock
# serialises executions for the same reason (Sprint 9).
EXECUTION_LOCK = threading.Lock()

# Phase 6B: background execution queue. One queue run at a time per
# server process; the worker executes one job at a time under
# EXECUTION_LOCK and recovers eligible unfinished jobs before new
# work. Explicit user action starts the queue.
_ACTIVE_QUEUE = {}

_ACTIVE_QUEUE_LOCK = threading.Lock()

# Sprint 15 productisation: background metadata sync. One sync
# operation at a time per server process (single provider or Sync
# All); a second request is refused honestly with 409 while one is
# running. Live progress snapshots live here only while running;
# the durable per-run ledger in metadata_sync_runs is the
# surviving record, so a refresh never loses the final summary.
_ACTIVE_SYNCS = {}

_ACTIVE_SYNCS_LOCK = threading.Lock()


class NamoaRequestHandler(BaseHTTPRequestHandler):
    """Route requests to page/API handlers over application services."""

    server_version = "NAMOA/0.1"

    service_factory = None

    database_path = None

    # -------------------------------------------------
    # HTTP plumbing
    # -------------------------------------------------

    def log_message(self, format, *args):  # noqa: A002
        """Quiet default logging; the application logger owns logs."""

    def _services(self):
        if self.service_factory is None:
            raise RuntimeError("No service factory configured")

        return self.service_factory()

    def _send_redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        return True

    def _send_html(self, body, status=200):
        payload = body.encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, data, status=200):
        payload = json.dumps(
            data,
            default=str,
            indent=2,
        ).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_json_attachment(self, data, filename):
        payload = json.dumps(
            data,
            default=str,
            indent=2,
        ).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{filename}"',
        )
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_error_json(self, message, status=500):
        self._send_json(
            {"error": message},
            status=status,
        )

    def _send_static(self, path):
        try:
            name = Path(path).name
            content = (STATIC_DIR / name).read_bytes()
        except OSError:
            return self._send_not_found(
                f"Static file not found: /static/{path}"
            )

        content_type = {
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
        }.get(Path(name).suffix, "application/octet-stream")

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    @staticmethod
    def _media_content_type(path):
        return {
            ".mp4": "video/mp4",
            ".mkv": "video/x-matroska",
            ".avi": "video/x-msvideo",
            ".mov": "video/quicktime",
            ".wmv": "video/x-ms-wmv",
            ".ts": "video/mp2t",
        }.get(Path(path).suffix.lower(), "application/octet-stream")

    def _send_file_range(self, path, content_type):
        """
        Serve one resolved media file with byte-range support.

        The path must already be resolved and authorised by the
        caller (Preview registry paths only); this method never
        interprets request input as a filesystem path. Single
        ranges yield 206 Partial Content; absent ranges yield the
        whole file; unsatisfiable ranges yield 416. Content is
        streamed in chunks so multi-gigabyte sources never load
        fully into memory.
        """

        import os

        try:
            size = os.path.getsize(path)
        except OSError:
            return self._send_not_found(
                "Media file is not available."
            )

        start, end = 0, size - 1
        status = 200

        raw_range = (self.headers.get("Range") or "").strip()

        if raw_range:
            parsed = self._parse_range(raw_range, size)

            if parsed is None:
                self.send_response(416)
                self.send_header(
                    "Content-Range", f"bytes */{size}"
                )
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()

                return True

            start, end = parsed
            status = 206

        length = end - start + 1

        try:
            handle = open(path, "rb")
        except OSError:
            return self._send_not_found(
                "Media file is not available."
            )

        try:
            handle.seek(start)

            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")

            if status == 206:
                self.send_header(
                    "Content-Range",
                    f"bytes {start}-{end}/{size}",
                )

            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

            remaining = length

            while remaining > 0:
                chunk = handle.read(min(262144, remaining))

                if not chunk:
                    break

                self.wfile.write(chunk)
                remaining -= len(chunk)

        finally:
            handle.close()

        return True

    @staticmethod
    def _parse_range(raw_range, size):
        """
        Parse a single HTTP byte range. Returns (start, end)
        inclusive, or None when unsatisfiable. Multipart ranges
        are not supported and read as unsatisfiable.
        """

        if not raw_range.startswith("bytes="):
            return None

        spec = raw_range[len("bytes="):].strip()

        if "," in spec:
            return None

        first, dash, last = spec.partition("-")

        if not dash:
            return None

        try:
            if first == "":
                suffix = int(last)

                if suffix <= 0:
                    return None

                start = max(0, size - suffix)
                end = size - 1
            elif last == "":
                start = int(first)
                end = size - 1
            else:
                start = int(first)
                end = int(last)
        except ValueError:
            return None

        if start < 0 or end < start or start >= size:
            return None

        return start, min(end, size - 1)

    def _send_not_found(self, message, *, api=False):
        if api:
            return self._send_error_json(message, status=404)

        return self._send_html(
            templates.not_found_page(message),
            status=404,
        )

    def _send_server_error(self, error, *, api=False):
        traceback.print_exc()

        message = (
            "The request could not be completed. "
            "See the NAMOA log for details."
        )

        try:
            if api:
                return self._send_error_json(message, status=500)

            return self._send_html(
                templates.server_error_page(message),
                status=500,
            )
        except (BrokenPipeError, ConnectionResetError):
            # Client disconnected while the error page itself
            # was being delivered. Same rationale as _dispatch:
            # nobody left to report to.
            return None

    # -------------------------------------------------
    # Request dispatch
    # -------------------------------------------------

    def do_GET(self):
        self._dispatch(expect_body=False)

    def do_POST(self):
        self._dispatch(expect_body=True)

    def _dispatch(self, *, expect_body):
        parsed = urlparse(self.path)

        path = parsed.path
        query = parse_qs(parsed.query)

        api = path.startswith("/api/")

        # The JSON API mirrors the HTML routes: strip the /api prefix
        # and route through the same table.
        if api:
            path = path[len("/api"):]

            if path == "/dashboard":
                path = "/"

        try:
            if expect_body:
                if not self._dispatch_post(path, query, api):
                    self._send_not_found(
                        f"Unknown route: {self.path}",
                        api=api,
                    )
            else:
                if not self._dispatch_get(path, query, api):
                    self._send_not_found(
                        f"Unknown route: {self.path}",
                        api=api,
                    )

        except handlers.NotFound as error:
            self._send_not_found(error.message, api=api)

        except ValueError as error:
            if api:
                self._send_error_json(str(error), status=400)
            else:
                self._send_html(
                    templates.error_page(
                        "Invalid request",
                        str(error),
                        status_kind="warn",
                    ),
                    status=400,
                )

        except (BrokenPipeError, ConnectionResetError):
            # The client disconnected before the response could
            # be delivered (typical after a long-running preview
            # request the browser abandoned). The response was
            # already computed; there is nobody left to report
            # to, so swallow silently instead of logging a
            # secondary traceback. Error semantics are unchanged.
            pass

        except Exception as error:
            self._send_server_error(error, api=api)

    # -------------------------------------------------
    # GET routes
    # -------------------------------------------------

    def _dispatch_get(self, path, query, api):
        services = self._services()

        # API-only JSON routes (GUI/UX Phases 4 + 5): scan status,
        # notifications, and the read-only folder browser.
        if api:

            if path == "/notifications":
                return self._send_json(
                    handlers.notifications_data(services)
                )

            scan_status_match = self._match(
                path,
                r"^/scan/(\d+)$",
            )

            if scan_status_match:
                return self._send_json(
                    handlers.scan_status_data(
                        services,
                        int(scan_status_match),
                    )
                )

            if path == "/fs/browse":
                return self._send_json(
                    handlers.filesystem_browse_data(
                        services,
                        self._optional_query(query, "path"),
                        include_files=bool(
                            self._optional_query(
                                query, "files"
                            )
                        ),
                    )
                )

            if path == "/operations":
                return self._send_json(
                    handlers.operations_data(services)
                )

        if path == "/":
            return self._page(
                api,
                handlers.dashboard_data,
                services,
                templates.render_dashboard,
            )

        if path == "/media":
            return self._page(
                api,
                handlers.media_index_data,
                services,
                templates.render_media,
            )

        if path == "/analysis":
            return self._page(
                api,
                handlers.analysis_status_data,
                services,
                templates.render_analysis,
            )

        if path == "/scan":
            services = self._services()
            data = handlers.scan_page_data(services)
            data["initial_path"] = (
                self._optional_query(query, "path")
            )
            data["autostart"] = (
                self._optional_query(query, "autostart")
                == "1"
            )

            if api:
                return self._send_json(data)

            return self._send_html(
                templates.render_scan(data)
            )

        if path == "/quick-find":
            return self._page(
                api,
                handlers.quick_find_page_data,
                services,
                templates.render_quick_find,
            )

        if path == "/intelligence":
            return self._page(
                api,
                handlers.intelligence_data,
                services,
                templates.render_intelligence,
            )

        if path == "/opportunities":
            return self._page(
                api,
                handlers.opportunities_data,
                services,
                templates.render_opportunities,
            )

        if path == "/preferences":
            return self._page(
                api,
                handlers.preferences_data,
                services,
                templates.render_preferences,
            )

        if path == "/preferences/wizard":
            return self._page(
                api,
                handlers.preferences_wizard_data,
                services,
                templates.render_preferences_wizard,
                self._optional_query(query, "session"),
            )

        if path == "/preferences/review":
            return self._page(
                api,
                handlers.preferences_review_data,
                services,
                templates.render_preference_review,
                self._optional_query(query, "view"),
            )

        if path == "/preferences/review/carousel":
            return self._page(
                api,
                handlers.preferences_carousel_data,
                services,
                templates.render_preference_carousel,
                self._optional_query(query, "index"),
            )

        if path == "/preview/new":
            return self._page(
                api,
                handlers.preview_new_data,
                services,
                templates.render_preview,
                self._optional_query(query, "origin"),
                self._optional_query(query, "ref"),
            )

        preview_media_match = self._match_preview_media(path)

        if preview_media_match is not None:
            token, kind = preview_media_match

            return self._preview_media(token, kind, api=api)

        preview_match = self._match(
            path, r"^/preview/([A-Za-z0-9_-]{8,64})$"
        )

        if preview_match:
            return self._page(
                api,
                handlers.preview_page_data,
                services,
                templates.render_preview,
                preview_match,
            )

        if path == "/organisation":
            return self._page(
                api,
                handlers.organisation_data,
                services,
                templates.render_organisation,
            )

        proposal_match = self._match(
            path, r"^/organisation/proposals/(\d+)$"
        )

        if proposal_match:
            return self._page(
                api,
                handlers.proposal_detail_data,
                services,
                templates.render_proposal_detail,
                int(proposal_match),
            )

        if path == "/organisation/executions":
            return self._page(
                api,
                handlers.organisation_executions_data,
                services,
                templates.render_organisation_executions,
            )

        organisation_execution_match = self._match(
            path,
            r"^/organisation/executions/(\d+)$",
        )

        if organisation_execution_match:
            return self._page(
                api,
                handlers.organisation_execution_detail_data,
                services,
                templates.render_organisation_execution_detail,
                int(organisation_execution_match),
            )

        if path == "/runs":
            return self._page(
                api,
                handlers.runs_data,
                services,
                templates.render_runs,
                self._optional_query(query, "status"),
                self._optional_int_query(query, "media"),
            )

        if path == "/queue-export":
            manifest = handlers.queue_export_data(services)

            if api:
                self._send_json(manifest)
            else:
                self._send_json_attachment(
                    manifest,
                    "queue-manifest.json",
                )
            return True

        if path == "/executions":
            return self._page(
                api,
                handlers.executions_list_data,
                services,
                templates.render_executions,
                self._optional_query(query, "state"),
            )

        recommendation_match = self._match(
            path, r"^/recommendations/(\d+)$"
        )

        if recommendation_match:
            return self._page(
                api,
                handlers.recommendation_detail_data,
                services,
                templates.render_recommendation_detail,
                int(recommendation_match),
            )

        recommendation_compare_match = self._match(
            path,
            r"^/recommendations/(\d+)/compare$",
        )

        if recommendation_compare_match:

            other = self._optional_query(query, "with")

            if other is None:

                return self._page(
                    api,
                    handlers
                    .recommendation_compare_select_data,
                    services,
                    templates
                    .render_recommendation_compare_select,
                    int(recommendation_compare_match),
                )

            return self._page(
                api,
                handlers.recommendation_compare_data,
                services,
                templates.render_recommendation_compare,
                int(recommendation_compare_match),
                int(other),
            )

        execution_match = self._match(
            path, r"^/executions/(\d+)$"
        )

        if execution_match:
            return self._page(
                api,
                handlers.execution_detail_data,
                services,
                templates.render_execution_detail,
                int(execution_match),
            )

        media_match = self._match(path, r"^/media/(\d+)$")
        if media_match:
            return self._page(
                api,
                handlers.media_detail_data,
                services,
                templates.render_media_detail,
                int(media_match),
            )

        media_history_match = self._match(
            path, r"^/media/(\d+)/history$"
        )

        if media_history_match:
            return self._page(
                api,
                handlers.media_history_data,
                services,
                templates.render_media_history,
                int(media_history_match),
            )

        opportunity_match = self._match(path, r"^/opportunities/(\d+)$")
        if opportunity_match:
            return self._page(
                api,
                handlers.opportunity_detail_data,
                services,
                templates.render_opportunity_detail,
                int(opportunity_match),
            )

        run_match = self._match(path, r"^/runs/(\d+)$")
        if run_match:
            return self._page(
                api,
                handlers.run_detail_data,
                services,
                templates.render_run_detail,
                int(run_match),
            )

        compare_match = self._match(path, r"^/runs/(\d+)/compare$")
        if compare_match:
            run_a = int(compare_match)
            run_b = query.get("with", [None])[0]
            if run_b is None:
                return self._page(
                    api,
                    handlers.compare_select_data,
                    services,
                    templates.render_compare_select,
                    run_a,
                )
            return self._page(
                api,
                handlers.compare_runs_data,
                services,
                templates.render_compare,
                run_a,
                run_b,
            )

        if path == "/organisation/integrations":
            return self._page(
                api,
                handlers.organisation_integrations_data,
                services,
                templates.render_organisation_integrations,
            )

        if path == "/organisation/integrations/sync-status":
            services = self._services()

            with _ACTIVE_SYNCS_LOCK:
                live = {
                    "running": bool(
                        _ACTIVE_SYNCS.get("running")
                    ),
                    "providers": list(
                        _ACTIVE_SYNCS.get("providers", [])
                    ),
                    "started_at": _ACTIVE_SYNCS.get(
                        "started_at"
                    ),
                    "live": {
                        name: dict(snapshot)
                        for name, snapshot in (
                            _ACTIVE_SYNCS.get("live", {})
                            .items()
                        )
                    },
                    "results": {
                        name: dict(summary)
                        for name, summary in (
                            _ACTIVE_SYNCS.get(
                                "results", {}
                            ).items()
                        )
                    },
                }

            self._send_json(
                handlers.integration_sync_status_data(
                    services, live
                )
            )
            return True

        if path == "/organisation/profiles":
            return self._page(
                api,
                handlers.organisation_profiles_data,
                services,
                templates.render_organisation_profiles,
            )

        organisation_profile_match = self._match(
            path, r"^/organisation/profiles/(\d+)$"
        )

        if organisation_profile_match:
            return self._page(
                api,
                handlers.organisation_profile_detail_data,
                services,
                templates.render_organisation_profile_detail,
                int(organisation_profile_match),
            )

        if path == "/organisation/scan-handoff":
            directory = self._optional_query(query, "dir")

            try:
                data = (
                    handlers.organisation_scan_handoff_data(
                        services,
                        directory or "",
                    )
                )
            except ValueError as error:
                return self._send_html(
                    templates.error_page(
                        "Scan handoff needs a directory",
                        str(error),
                        status_kind="warn",
                    ),
                    status=400,
                )

            if api:
                return self._send_json(data)

            return self._send_html(
                templates.render_organisation_scan_handoff(
                    data
                )
            )

        if path == "/organisation/whatif":
            return self._page(
                api,
                handlers.organisation_whatif_data,
                services,
                templates.render_organisation_whatif,
            )

        if path == "/organisation/reconcile":
            return self._page(
                api,
                handlers.organisation_reconcile_data,
                services,
                templates.render_organisation_reconcile,
            )

        if path == "/organisation/preflight":
            return self._page(
                api,
                handlers.organisation_preflight_data,
                services,
                templates.render_organisation_preflight,
            )

        organisation_scope_action_match = self._match(
            path, r"^/organisation/scope-actions/(\d+)$"
        )

        if organisation_scope_action_match:
            return self._page(
                api,
                handlers.organisation_scope_action_detail_data,
                services,
                templates
                .render_organisation_scope_action_detail,
                int(organisation_scope_action_match),
            )

        if path == "/organisation/scope-executions":
            return self._page(
                api,
                handlers.organisation_scope_executions_data,
                services,
                templates
                .render_organisation_scope_executions,
            )

        organisation_scope_execution_match = self._match(
            path, r"^/organisation/scope-executions/(\d+)$"
        )

        if organisation_scope_execution_match:
            return self._page(
                api,
                handlers
                .organisation_scope_execution_detail_data,
                services,
                templates
                .render_organisation_scope_execution_detail,
                int(organisation_scope_execution_match),
            )

        if path.startswith("/static/"):
            self._send_static(path[len("/static/"):])
            return True

        return False

    # -------------------------------------------------
    # POST routes
    # -------------------------------------------------

    def _dispatch_post(self, path, query, api):

        if path == "/organisation/generate":
            services = self._services()
            handlers.organisation_generate_data(services)
            data = handlers.organisation_data(services)
            if api:
                self._send_json(data)
            else:
                self._send_html(
                    templates.render_organisation(data)
                )
            return True

        organisation_execute_match = self._match(
            path,
            r"^/organisation/proposals/(\d+)/execute$",
        )

        if organisation_execute_match is not None:
            body = self._read_form_body()
            services = self._services()
            try:
                data = handlers.organisation_execution_execute_data(
                    services,
                    int(organisation_execute_match),
                    body,
                )
            except handlers.NotFound as error:
                return self._organisation_execution_error(
                    api, error.message
                )
            if api:
                self._send_json(data)
            else:
                self._send_html(
                    templates.render_organisation_execution_detail(data)
                )
            return True

        organisation_recover_match = self._match(
            path,
            r"^/organisation/executions/(\d+)/recover$",
        )

        if organisation_recover_match is not None:
            services = self._services()
            try:
                data = handlers.organisation_execution_recover_data(
                    services,
                    int(organisation_recover_match),
                )
            except handlers.NotFound as error:
                return self._organisation_execution_error(
                    api, error.message
                )
            if api:
                self._send_json(data)
            else:
                self._send_html(
                    templates.render_organisation_execution_detail(data)
                )
            return True

        if path == "/organisation/accept-selected":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers
                .organisation_accept_confirmation_data,
                services=self._services(),
                body=body,
                render_fn=(
                    templates
                    .render_organisation_accept_confirmation
                ),
            )

        if path == "/organisation/confirm-acceptance":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.organisation_accept_apply_data,
                services=self._services(),
                body=body,
                render_fn=(
                    templates
                    .render_organisation_acceptance_report
                ),
            )

        if path == "/organisation/integrations/save":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.organisation_integrations_save_data,
                services=self._services(),
                body=body,
                render_fn=(
                    templates
                    .render_organisation_integrations
                ),
            )

        organisation_integration_test_match = self._match(
            path,
            r"^/organisation/integrations/([A-Za-z0-9_-]+)/test$",
        )

        if organisation_integration_test_match is not None:
            services = self._services()
            try:
                data = handlers.organisation_integration_test_data(
                    services,
                    organisation_integration_test_match,
                )
            except handlers.NotFound as error:
                if api:
                    self._send_error_json(
                        error.message,
                        status=404,
                    )
                else:
                    self._send_html(
                        templates.error_page(
                            "Integration error",
                            error.message,
                            status_kind="warn",
                        ),
                        status=404,
                    )
                return True
            if api:
                self._send_json(data)
            else:
                self._send_html(
                    templates.render_organisation_integrations(
                        data
                    )
                )
            return True

        organisation_integration_remove_match = self._match(
            path,
            (
                r"^/organisation/integrations/"
                r"([A-Za-z0-9_-]+)/remove-credential$"
            ),
        )

        if organisation_integration_remove_match is not None:
            services = self._services()
            try:
                data = (
                    handlers
                    .organisation_integration_remove_credential_data(
                        services,
                        organisation_integration_remove_match,
                    )
                )
            except handlers.NotFound as error:
                if api:
                    self._send_error_json(
                        error.message,
                        status=404,
                    )
                else:
                    self._send_html(
                        templates.error_page(
                            "Integration error",
                            error.message,
                            status_kind="warn",
                        ),
                        status=404,
                    )
                return True
            if api:
                self._send_json(data)
            else:
                self._send_html(
                    templates.render_organisation_integrations(
                        data
                    )
                )
            return True

        if path == "/organisation/integrations/mappings":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.organisation_integration_mapping_add_data,
                services=self._services(),
                body=body,
                render_fn=(
                    templates
                    .render_organisation_integrations
                ),
            )

        if path == "/organisation/integrations/mappings/remove":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers
                .organisation_integration_mapping_remove_data,
                services=self._services(),
                body=body,
                render_fn=(
                    templates
                    .render_organisation_integrations
                ),
            )

        organisation_integration_tags_match = self._match(
            path,
            (
                r"^/organisation/integrations/"
                r"([A-Za-z0-9_-]+)/tags$"
            ),
        )

        if organisation_integration_tags_match is not None:
            services = self._services()
            try:
                data = (
                    handlers
                    .organisation_integration_tags_data(
                        services,
                        organisation_integration_tags_match,
                    )
                )
            except handlers.NotFound as error:
                if api:
                    self._send_error_json(
                        error.message,
                        status=404,
                    )
                else:
                    self._send_html(
                        templates.error_page(
                            "Integration error",
                            error.message,
                            status_kind="warn",
                        ),
                        status=404,
                    )
                return True
            if api:
                self._send_json(data)
            else:
                self._send_html(
                    templates.render_organisation_integrations(
                        data
                    )
                )
            return True

        if path == "/organisation/integrations/jellyfin/users":
            services = self._services()
            data = handlers.organisation_integration_users_data(
                services
            )
            if api:
                self._send_json(data)
            else:
                self._send_html(
                    templates.render_organisation_integrations(
                        data
                    )
                )
            return True

        if path == "/organisation/integrations/jellyfin/user":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.organisation_integration_user_save_data,
                services=self._services(),
                body=body,
                render_fn=(
                    templates
                    .render_organisation_integrations
                ),
            )

        if path == "/organisation/integrations/sync-all":
            return self._start_metadata_sync(
                api, providers=None
            )

        organisation_integration_sync_match = self._match(
            path,
            (
                r"^/organisation/integrations/"
                r"([A-Za-z0-9_-]+)/sync$"
            ),
        )

        if organisation_integration_sync_match is not None:
            return self._start_metadata_sync(
                api,
                providers=[
                    organisation_integration_sync_match
                ],
            )

        if path == "/organisation/profiles/save":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.organisation_profile_save_data,
                services=self._services(),
                body=body,
                render_fn=(
                    templates.render_organisation_profiles
                ),
            )

        if path == "/organisation/profiles/preset":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.organisation_profile_preset_data,
                services=self._services(),
                body=body,
                render_fn=(
                    templates.render_organisation_profiles
                ),
            )

        organisation_profile_update_match = self._match(
            path, r"^/organisation/profiles/(\d+)/save$"
        )

        if organisation_profile_update_match is not None:
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.organisation_profile_update_data,
                services=self._services(),
                body=body,
                render_fn=(
                    templates
                    .render_organisation_profile_detail
                ),
                extra=[int(organisation_profile_update_match)],
            )

        organisation_profile_delete_match = self._match(
            path, r"^/organisation/profiles/(\d+)/delete$"
        )

        if organisation_profile_delete_match is not None:
            services = self._services()
            try:
                data = handlers.organisation_profile_delete_data(
                    services,
                    self._read_form_body(),
                    int(organisation_profile_delete_match),
                )
            except handlers.NotFound as error:
                return self._organisation_execution_error(
                    api, error.message
                )
            if api:
                self._send_json(data)
            elif "deleted" in data:
                self._send_html(
                    templates.render_organisation_profiles(
                        data
                    )
                )
            else:
                self._send_html(
                    templates
                    .render_organisation_profile_detail(data)
                )
            return True

        organisation_profile_autofill_match = self._match(
            path,
            r"^/organisation/profiles/(\d+)/autofill-tags$",
        )

        if organisation_profile_autofill_match is not None:
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.organisation_profile_autofill_data,
                services=self._services(),
                body=body,
                render_fn=(
                    templates
                    .render_organisation_profile_detail
                ),
                extra=[
                    int(organisation_profile_autofill_match)
                ],
            )

        organisation_profile_clone_match = self._match(
            path, r"^/organisation/profiles/(\d+)/clone$"
        )

        if organisation_profile_clone_match is not None:
            services = self._services()
            try:
                data = handlers.organisation_profile_clone_data(
                    services,
                    int(organisation_profile_clone_match),
                )
            except handlers.NotFound as error:
                return self._organisation_execution_error(
                    api, error.message
                )
            if api:
                self._send_json(data)
            else:
                self._send_html(
                    templates.render_organisation_profiles(
                        data
                    )
                )
            return True

        organisation_profile_signal_match = self._match(
            path, r"^/organisation/profiles/(\d+)/signals$"
        )

        if organisation_profile_signal_match is not None:
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.organisation_profile_signal_save_data,
                services=self._services(),
                body=body,
                render_fn=(
                    templates
                    .render_organisation_profile_detail
                ),
                extra=[int(organisation_profile_signal_match)],
            )

        organisation_profile_mapping_match = self._match(
            path, r"^/organisation/profiles/(\d+)/mappings$"
        )

        if organisation_profile_mapping_match is not None:
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.organisation_profile_mapping_add_data,
                services=self._services(),
                body=body,
                render_fn=(
                    templates
                    .render_organisation_profile_detail
                ),
                extra=[int(organisation_profile_mapping_match)],
            )

        organisation_profile_mapping_remove_match = self._match(
            path, r"^/organisation/profiles/(\d+)/mappings/remove$"
        )

        if organisation_profile_mapping_remove_match is not None:
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.organisation_profile_mapping_remove_data,
                services=self._services(),
                body=body,
                render_fn=(
                    templates
                    .render_organisation_profile_detail
                ),
                extra=[int(organisation_profile_mapping_remove_match)],
            )

        organisation_profile_category_match = self._match(
            path, r"^/organisation/profiles/(\d+)/categories$"
        )

        if organisation_profile_category_match is not None:
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.organisation_profile_category_add_data,
                services=self._services(),
                body=body,
                render_fn=(
                    templates
                    .render_organisation_profile_detail
                ),
                extra=[int(organisation_profile_category_match)],
            )

        organisation_profile_category_remove_match = self._match(
            path, r"^/organisation/profiles/(\d+)/categories/remove$"
        )

        if organisation_profile_category_remove_match is not None:
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.organisation_profile_category_remove_data,
                services=self._services(),
                body=body,
                render_fn=(
                    templates
                    .render_organisation_profile_detail
                ),
                extra=[int(organisation_profile_category_remove_match)],
            )

        if path == "/organisation/scan-handoff":
            body = self._read_form_body()

            def _first(name):
                try:
                    return (body.get(name) or [None])[0]
                except (AttributeError, TypeError, IndexError):
                    return None

            directory = str(_first("dir") or "").strip()
            confirmed = str(
                _first("confirm") or ""
            ).strip().lower() in ("yes", "true", "1", "on")

            if not directory or not confirmed:
                if api:
                    return self._send_error_json(
                        "Confirmation with a directory is "
                        "required for scan handoff.",
                        status=400,
                    )

                try:
                    data = (
                        handlers.organisation_scan_handoff_data(
                            self._services(),
                            directory,
                        )
                    )
                except ValueError as error:
                    return self._send_html(
                        templates.error_page(
                            "Scan handoff needs a directory",
                            str(error),
                            status_kind="warn",
                        ),
                        status=400,
                    )

                return self._send_html(
                    templates.render_organisation_scan_handoff(
                        data
                    )
                )

            location = (
                "/scan?path=" + quote(directory, safe="")
                + "&autostart=1"
            )

            if api:
                return self._send_json({"redirect": location})

            return self._send_redirect(location)

        if path == "/organisation/whatif/file":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.organisation_whatif_file_data,
                services=self._services(),
                body=body,
                render_fn=(
                    templates.render_organisation_whatif_result
                ),
                error_render_fn=(
                    templates.render_organisation_whatif
                ),
            )

        if path == "/organisation/whatif/sample":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.organisation_whatif_sample_data,
                services=self._services(),
                body=body,
                render_fn=(
                    templates
                    .render_organisation_sampler_result
                ),
                error_render_fn=(
                    templates.render_organisation_whatif
                ),
            )

        if path == "/organisation/reconcile/preview":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.organisation_reconcile_preview_data,
                services=self._services(),
                body=body,
                render_fn=(
                    templates
                    .render_organisation_reconcile_preview
                ),
                error_render_fn=(
                    templates.render_organisation_reconcile
                ),
            )

        if path == "/organisation/preflight/run":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.organisation_preflight_data,
                services=self._services(),
                body=body,
                render_fn=(
                    templates.render_organisation_preflight
                ),
            )

        if path == "/organisation/reconcile/confirm-acceptance":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.organisation_reconcile_confirm_data,
                services=self._services(),
                body=body,
                render_fn=(
                    templates
                    .render_organisation_reconcile_report
                ),
            )

        organisation_scope_accept_match = self._match(
            path,
            r"^/organisation/scope-actions/(\d+)/accept$",
        )

        if organisation_scope_accept_match is not None:
            services = self._services()
            try:
                data = handlers.organisation_scope_action_accept_data(
                    services,
                    int(organisation_scope_accept_match),
                )
            except handlers.NotFound as error:
                return self._organisation_execution_error(
                    api, error.message
                )
            if api:
                self._send_json(data)
            else:
                self._send_html(
                    templates
                    .render_organisation_scope_action_detail(
                        data
                    )
                )
            return True

        organisation_scope_execute_match = self._match(
            path,
            r"^/organisation/scope-actions/(\d+)/execute$",
        )

        if organisation_scope_execute_match is not None:
            body = self._read_form_body()
            services = self._services()
            try:
                data = handlers.organisation_scope_action_execute_data(
                    services,
                    int(organisation_scope_execute_match),
                    body,
                )
            except handlers.NotFound as error:
                return self._organisation_execution_error(
                    api, error.message
                )
            if api:
                self._send_json(data)
            else:
                self._send_html(
                    templates
                    .render_organisation_scope_execution_detail(
                        data
                    )
                )
            return True

        organisation_scope_recover_match = self._match(
            path,
            r"^/organisation/scope-executions/(\d+)/recover$",
        )

        if organisation_scope_recover_match is not None:
            services = self._services()
            try:
                data = (
                    handlers
                    .organisation_scope_execution_recover_data(
                        services,
                        int(organisation_scope_recover_match),
                    )
                )
            except handlers.NotFound as error:
                return self._organisation_execution_error(
                    api, error.message
                )
            if api:
                self._send_json(data)
            else:
                self._send_html(
                    templates
                    .render_organisation_scope_execution_detail(
                        data
                    )
                )
            return True

        if path == "/opportunities/accept-selected":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.accept_selected_confirmation_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_accept_confirmation,
            )

        if path == "/opportunities/confirm-acceptance":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.accept_selected_apply_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_acceptance_report,
            )

        if path == "/opportunities/reject-selected":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.dashboard_reject_selected_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_rejection_report,
            )

        if path == "/preferences/wizard/start":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.preferences_wizard_start_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_preferences_wizard,
            )

        if path == "/preferences/wizard/answer":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.preferences_wizard_answer_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_preferences_wizard,
            )

        if path == "/preferences/wizard/undo":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.preferences_wizard_undo_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_preferences_wizard,
            )

        if path == "/preferences/wizard/finish":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.preferences_wizard_finish_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_preferences_wizard,
            )

        if path == "/preferences/wizard/cancel":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.preferences_wizard_cancel_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_preferences_wizard,
            )

        if path == "/preferences/wizard/save":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.preferences_wizard_save_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_preferences_wizard,
            )

        if path == "/preferences/wizard/reset":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.preferences_wizard_reset_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_preferences_wizard,
            )

        if path == "/preferences/review/refresh":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.preferences_review_refresh_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_preference_review,
            )

        if path == "/preferences/review/accept":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.preferences_review_accept_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_preference_review,
            )

        if path == "/preferences/review/reject":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.preferences_review_reject_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_preference_review,
            )

        if path == "/preferences/review/change":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.preferences_review_change_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_preference_review,
            )

        if path == "/preferences/review/specify":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.preferences_review_specify_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_preference_review,
            )

        if path == "/preferences/review/manual":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.preferences_review_manual_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_preference_review,
            )

        if path == "/preferences/review/carousel/accept":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.preferences_carousel_accept_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_preference_carousel,
            )

        if path == "/preferences/review/carousel/reject":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.preferences_carousel_reject_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_preference_carousel,
            )

        if path == "/preferences/review/carousel/manual":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.preferences_carousel_manual_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_preference_carousel,
            )

        if path == "/preferences/review/reopen":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.preferences_review_reopen_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_preference_review,
            )

        if path == "/preferences/review/accept-all":
            body = self._read_form_body()
            return self._form_page(
                api,
                handlers.preferences_review_accept_all_data,
                services=self._services(),
                body=body,
                render_fn=templates.render_preference_review,
            )

        preview_action_match = self._match_preview_action(path)

        if preview_action_match is not None:
            token, action = preview_action_match
            body = self._read_form_body()

            if body is None:
                body = {}

            body = dict(body)
            body.setdefault("token", [token])

            preview_routes = {
                "generate": handlers.preview_generate_data,
                "override": handlers.preview_override_data,
                "accept": handlers.preview_accept_data,
                "reject": handlers.preview_reject_data,
                "close": handlers.preview_close_data,
                "acknowledge": (
                    handlers.preview_acknowledge_data
                ),
                "preserve": handlers.preview_preserve_data,
            }

            return self._form_page(
                api,
                preview_routes[action],
                services=self._services(),
                body=body,
                render_fn=templates.render_preview,
            )

                # Phase 11: standing-decision actions are API-only.
        if api:

            standing_decision_refuse_match = self._match(
                path,
                r"^/opportunities/(\d+)/refuse$",
            )

            if standing_decision_refuse_match is not None:
                body = self._read_form_body()
                services = self._services()

                data = handlers.standing_decision_refuse_data(
                    services,
                    int(standing_decision_refuse_match),
                    body,
                )

                return self._send_json(data)

            standing_decision_revoke_match = self._match(
                path,
                r"^/opportunities/(\d+)/revoke$",
            )

            if standing_decision_revoke_match is not None:
                body = self._read_form_body()
                services = self._services()

                data = handlers.standing_decision_revoke_data(
                    services,
                    int(standing_decision_revoke_match),
                    body,
                )

                return self._send_json(data)

        opportunity_approve_match = self._match(
            path,
            r"^/opportunities/(\d+)/approve$",
        )

        if opportunity_approve_match is not None:
            body = self._read_form_body()
            services = self._services()
            try:
                data = handlers.execution_approve_data(
                    services,
                    int(opportunity_approve_match),
                    body,
                )
            except handlers.NotFound as error:
                return self._execution_error(
                    api, error.message
                )
            if api:
                self._send_json(data)
            else:
                self._send_html(
                    templates.render_execution_detail(data)
                )
            return True

        opportunity_reject_match = self._match(
            path,
            r"^/opportunities/(\d+)/reject$",
        )

        if opportunity_reject_match is not None:
            body = self._read_form_body()
            services = self._services()
            try:
                data = handlers.dashboard_reject_data(
                    services,
                    int(opportunity_reject_match),
                    body,
                )
            except handlers.NotFound as error:
                return self._execution_error(
                    api, error.message
                )
            if api:
                self._send_json(data)
            else:
                self._send_html(
                    templates.render_rejection_report(data)
                )
            return True

        execution_action = self._match(
            path,
            r"^/executions/(\d+)/(run|rollback)$",
        )

        if execution_action is not None:
            job_id = int(execution_action)
            action = path.rsplit("/", 1)[1]
            services = self._services()
            handler = (
                handlers.execution_run_data
                if action == "run"
                else handlers.execution_rollback_data
            )
            try:
                with EXECUTION_LOCK:
                    data = handler(services, job_id)
            except handlers.NotFound as error:
                return self._execution_error(
                    api, error.message
                )
            if api:
                self._send_json(data)
            else:
                self._send_html(
                    templates.render_execution_detail(data)
                )
            return True

        execution_delete_match = self._match(
            path,
            r"^/executions/(\d+)/delete-original$",
        )

        if execution_delete_match is not None:
            services = self._services()
            try:
                data = handlers.execution_delete_original_data(
                    services,
                    int(execution_delete_match),
                )
            except handlers.NotFound as error:
                return self._execution_error(
                    api, error.message
                )
            if api:
                self._send_json(data)
            else:
                self._send_html(
                    templates.render_execution_detail(data)
                )
            return True

        if path == "/executions/start-queue":
            services = self._services()
            if not self._acquire_queue_slot():
                if api:
                    self._send_error_json(
                        "The optimisation queue is already "
                        "running; one queue runs at a time.",
                        status=409,
                    )
                else:
                    self._send_html(
                        templates.error_page(
                            "Queue already running",
                            "The optimisation queue is already "
                            "running; one queue runs at a time.",
                            status_kind="warn",
                        ),
                        status=409,
                    )
                return True
            threading.Thread(
                target=self._background_queue_worker,
                daemon=True,
            ).start()
            if api:
                self._send_json(
                    {"status": "started", "refreshed_at": handlers.now_timestamp()}
                )
            else:
                self._send_html(
                    templates.render_queue_started()
                )
            return True

        if path == "/quick-find":
            body = self._read_form_body()
            services = self._services()
            try:
                data = handlers.quick_find_data(
                    services,
                    body,
                )
            except handlers.NotFound as error:
                if api:
                    self._send_error_json(
                        error.message,
                        status=404,
                    )
                else:
                    page = handlers.quick_find_page_data(
                        services
                    )
                    page["form_error"] = {
                        "title": (
                            "Unable to use this location"
                        ),
                        "message": error.message,
                        "guidance": (
                            "Check that the path exists "
                            "and that NAMOA has permission "
                            "to access it, then try again."
                        ),
                    }
                    raw_path = None
                    if isinstance(body, dict):
                        raw_path = (
                            body.get("path") or [None]
                        )[0]
                    page["input"] = {
                        "path": raw_path or ""
                    }
                    self._send_html(
                        templates.render_quick_find(page),
                        status=404,
                    )
                return True
            if api:
                self._send_json(data)
            else:
                self._send_html(
                    templates.render_quick_find_result(data)
                )
            return True

        opportunity_advanced_match = self._match(
            path,
            r"^/opportunities/(\d+)/advanced-approve$",
        )

        if opportunity_advanced_match is not None:
            body = self._read_form_body()
            services = self._services()
            try:
                data = handlers.execution_advanced_approve_data(
                    services,
                    int(opportunity_advanced_match),
                    body,
                )
            except handlers.NotFound as error:
                return self._execution_error(
                    api, error.message
                )
            if api:
                self._send_json(data)
            else:
                self._send_html(
                    templates.render_execution_detail(data)
                )
            return True

        media_analyse_match = self._match(
            path,
            r"^/media/(\d+)/analyse$",
        )

        if media_analyse_match:
            services = self._services()

            try:
                data = handlers.analyse_media_data(
                    services,
                    int(media_analyse_match),
                )
            except handlers.NotFound as error:
                if api:
                    self._send_error_json(
                        error.message,
                        status=404,
                    )
                else:
                    self._send_html(
                        templates.error_page(
                            "Not found",
                            error.message,
                            status_kind="warn",
                        ),
                        status=404,
                    )
                return True

            if api:
                self._send_json(data)
            else:
                self._send_html(
                    templates.render_analyse_report(data)
                )
            return True

        # GUI/UX Phase 4: notification dismissal actions (API-only).
        if api:

            dismiss_match = self._match(
                path,
                r"^/notifications/(\d+)/dismiss$",
            )

            if dismiss_match:
                services = self._services()
                return self._send_json(
                    handlers.notification_dismiss_data(
                        services,
                        int(dismiss_match),
                    )
                )

            if path == "/notifications/dismiss-all":
                services = self._services()
                return self._send_json(
                    handlers.notification_dismiss_all_data(
                        services
                    )
                )

        if path == "/scan":
            body = self._read_form_body()

            try:
                scan_path = body.get("path", [None])[0]
            except (TypeError, IndexError):
                scan_path = None

            if not scan_path or not scan_path.strip():
                if api:
                    self._send_error_json(
                        "A scan path is required",
                        status=400,
                    )
                else:
                    self._send_html(
                        templates.error_page(
                            "Invalid scan request",
                            "A scan path is required.",
                            status_kind="warn",
                        ),
                        status=400,
                    )
                return True

            scan_path = scan_path.strip()

            # One background scan at a time: refuse honestly while
            # another is running (SCAN_LOCK still serialises the
            # pipeline writes for the running scan).
            if not self._acquire_scan_slot(scan_path):
                if api:
                    self._send_error_json(
                        "A scan is already running; wait for it "
                        "to finish.",
                        status=409,
                    )
                else:
                    self._send_html(
                        templates.error_page(
                            "Scan already running",
                            "A scan is already running; wait for "
                            "it to finish.",
                            status_kind="warn",
                        ),
                        status=409,
                    )
                return True

            services = self._services()

            try:
                scan_id = (
                    services.scan_service.start_scan(
                        scan_path,
                        database_path=self.database_path,
                    )
                )
            except Exception as error:
                self._release_scan_slot()
                if api:
                    self._send_error_json(
                        str(error),
                        status=500,
                    )
                else:
                    self._send_html(
                        templates.error_page(
                            "Scan could not be started",
                            str(error),
                            status_kind="error",
                        ),
                        status=500,
                    )
                return True

            with _ACTIVE_SCANS_LOCK:
                _ACTIVE_SCANS["scan_id"] = scan_id

            worker = threading.Thread(
                target=self._background_scan_worker,
                args=(scan_id, scan_path),
                daemon=True,
            )
            worker.start()

            data = {
                "scan_id": scan_id,
                "path": scan_path,
                "status": "running",
                "refreshed_at": handlers.now_timestamp(),
            }

            if api:
                self._send_json(data)
            else:
                page_data = handlers.scan_page_data(services)
                page_data["active_scan"] = {
                    "scan_id": scan_id,
                    "path": scan_path,
                }
                self._send_html(
                    templates.render_scan(page_data)
                )
            return True

        return False

    # -------------------------------------------------
    # GUI/UX Phase 5: background scan execution
    # -------------------------------------------------

    def _acquire_scan_slot(self, scan_path):
        """
        Register intent to run one background scan. Returns True when
        a slot was acquired, False when a scan is already running.
        """

        with _ACTIVE_SCANS_LOCK:
            if _ACTIVE_SCANS:
                return False
            _ACTIVE_SCANS["path"] = scan_path
            _ACTIVE_SCANS["scan_id"] = None
            return True

    def _release_scan_slot(self):
        with _ACTIVE_SCANS_LOCK:
            _ACTIVE_SCANS.clear()

    def _background_scan_worker(self, scan_id, scan_path):
        """
        Run the scan off the request path. A fresh service graph is
        built inside this thread (the factory creates a thread-local
        connection), and SCAN_LOCK serialises the pipeline writes.
        """

        try:
            with SCAN_LOCK:
                services = self._services()
                handlers.run_scan(
                    services,
                    scan_path,
                    database_path=self.database_path,
                    scan_id=scan_id,
                )
        except Exception:
            traceback.print_exc()
        finally:
            self._release_scan_slot()

    def _acquire_queue_slot(self):
        """
        Register intent to run one background queue pass. Returns True
        when a slot was acquired, False when a queue pass is already
        running.
        """

        with _ACTIVE_QUEUE_LOCK:
            if _ACTIVE_QUEUE:
                return False
            _ACTIVE_QUEUE["running"] = True
            return True

    def _release_queue_slot(self):
        with _ACTIVE_QUEUE_LOCK:
            _ACTIVE_QUEUE.clear()

    # -------------------------------------------------
    # Sprint 15 productisation: background metadata sync
    # -------------------------------------------------

    def _acquire_sync_slot(self, providers):
        """
        Register intent to run one background metadata
        sync. Returns True when the slot was acquired,
        False when a sync is already running. Finished
        summaries stay in memory until the next sync
        starts, so a refresh never loses them; the
        durable ledger survives restarts too.
        """

        with _ACTIVE_SYNCS_LOCK:
            if _ACTIVE_SYNCS.get("running"):
                return False
            _ACTIVE_SYNCS.clear()
            _ACTIVE_SYNCS["running"] = True
            _ACTIVE_SYNCS["providers"] = list(providers)
            _ACTIVE_SYNCS["started_at"] = time.time()
            _ACTIVE_SYNCS["live"] = {}
            _ACTIVE_SYNCS["results"] = {}
            return True

    def _release_sync_slot(self):
        with _ACTIVE_SYNCS_LOCK:
            _ACTIVE_SYNCS["running"] = False

    def _start_metadata_sync(self, api, *, providers):
        """
        Validate then start one background metadata sync
        (single provider or Sync All). Validation errors
        and a busy sync slot are reported in context on
        the integrations page (or as JSON for the API);
        the worker thread does the fetching off the
        request path.
        """

        from app.application.integration_service import (
            PROVIDERS,
        )

        services = self._services()

        try:
            if providers is None:
                data = (
                    handlers
                    .organisation_integrations_sync_all_data(
                        services
                    )
                )
                wanted = list(data.get("sync_providers") or [])
                started_label = "all"
            else:
                data = (
                    handlers
                    .organisation_integration_sync_data(
                        services, providers[0]
                    )
                )
                wanted = [
                    data["sync_started"]["provider"]
                ]
                started_label = wanted[0]
        except handlers.NotFound as error:
            if api:
                self._send_error_json(
                    error.message, status=404
                )
            else:
                self._send_html(
                    templates.error_page(
                        "Integration error",
                        error.message,
                        status_kind="warn",
                    ),
                    status=404,
                )
            return True
        except handlers.UserError as error:
            denied_provider = (
                (providers or [None])[0]
                if providers is not None
                else None
            )
            data = {
                "sync_denied": {
                    "provider": denied_provider,
                    "message": str(error),
                    "title": error.title,
                },
                "providers": (
                    services.integration_service
                    .list_providers()
                ),
                "refreshed_at": (
                    handlers.now_timestamp()
                ),
            }
            if api:
                self._send_error_json(str(error), status=400)
            else:
                self._send_html(
                    templates
                    .render_organisation_integrations(data),
                    status=400,
                )
            return True

        if not self._acquire_sync_slot(wanted):
            busy = {
                "sync_denied": {
                    "provider": started_label,
                    "message": (
                        "a metadata sync is already "
                        "running; wait for it to finish, "
                        "then sync again if needed."
                    ),
                    "title": "Sync already running",
                },
                "providers": (
                    services.integration_service
                    .list_providers()
                ),
                "refreshed_at": (
                    handlers.now_timestamp()
                ),
            }
            if api:
                self._send_error_json(
                    busy["sync_denied"]["message"],
                    status=409,
                )
            else:
                self._send_html(
                    templates
                    .render_organisation_integrations(busy),
                    status=409,
                )
            return True

        worker = threading.Thread(
            target=self._background_sync_worker,
            args=(wanted,),
            daemon=True,
        )
        worker.start()

        if api:
            self._send_json(data)
        else:
            self._send_html(
                templates.render_organisation_integrations(
                    data
                )
            )
        return True

    def _background_sync_worker(self, providers):
        """
        Run provider metadata sync off the request path. A
        fresh service graph is built inside this thread
        (the factory creates a thread-local connection).
        Progress snapshots are published to _ACTIVE_SYNCS
        as each provider syncs; the durable sync run
        ledger keeps every final summary.
        """

        started = time.time()

        try:
            services = self._services()

            for provider in providers:
                def _record(
                    snapshot, _provider=provider
                ):
                    snapshot = dict(snapshot)
                    elapsed = time.time() - started
                    snapshot["elapsed"] = round(elapsed, 1)

                    inspected = snapshot.get("inspected", 0)
                    total = snapshot.get("total_items", 0)

                    if (
                        snapshot.get("phase") == "syncing"
                        and inspected > 0
                        and total > inspected
                    ):
                        remaining = (
                            (elapsed / inspected)
                            * (total - inspected)
                        )
                        snapshot["eta_seconds"] = round(
                            remaining, 1
                        )
                    else:
                        snapshot["eta_seconds"] = None

                    with _ACTIVE_SYNCS_LOCK:
                        _ACTIVE_SYNCS["live"][
                            _provider
                        ] = snapshot

                try:
                    summary = (
                        services.integration_service
                        .sync_provider(
                            provider, progress=_record
                        )
                    )
                except Exception as error:
                    summary = {
                        "provider": provider,
                        "state": "failed",
                        "total_items": 0,
                        "inspected": 0,
                        "matched": 0,
                        "observed": 0,
                        "updated": 0,
                        "unchanged": 0,
                        "unmatched": 0,
                        "errors": [
                            f"{type(error).__name__}: "
                            f"{error}"
                        ],
                    }

                summary["elapsed"] = round(
                    time.time() - started, 1
                )
                summary["phase"] = "done"

                with _ACTIVE_SYNCS_LOCK:
                    _ACTIVE_SYNCS["live"][provider] = (
                        dict(summary)
                    )
                    _ACTIVE_SYNCS["results"][provider] = (
                        dict(summary)
                    )
        except Exception:
            traceback.print_exc()
        finally:
            self._release_sync_slot()

    def _background_queue_worker(self):
        """
        Run the optimisation queue off the request path. One job
        executes at a time under EXECUTION_LOCK; eligible unfinished
        jobs are recovered before new work. The worker never invents
        work and never executes an unapproved job.
        """

        try:
            with EXECUTION_LOCK:
                services = self._services()
                handlers.execution_run_queue_data(
                    services,
                    {},
                )
        except Exception:
            traceback.print_exc()
        finally:
            self._release_queue_slot()

    # -------------------------------------------------
    # Helpers
    # -------------------------------------------------

    def _execution_error(self, api, message):
        if api:
            self._send_error_json(message, status=404)
        else:
            self._send_html(
                templates.error_page(
                    "Execution error",
                    message,
                    status_kind="warn",
                ),
                status=404,
            )

    def _organisation_execution_error(self, api, message):
        if api:
            self._send_error_json(message, status=404)
        else:
            self._send_html(
                templates.error_page(
                    "Organisation execution error",
                    message,
                    status_kind="warn",
                ),
                status=404,
            )

    def _page(
        self,
        api,
        data_fn,
        services,
        render_fn,
        *args,
    ):
        data = data_fn(services, *args)

        if api:
            self._send_json(data)
        else:
            self._send_html(render_fn(data))

        return True

    def _form_page(
        self,
        api,
        data_fn,
        *,
        services,
        body,
        render_fn,
        extra=(),
        error_render_fn=None,
    ):
        """
        POST form handler following the same data/render split as
        _page. ValueError (invalid input) becomes a 400 in both
        the HTML and JSON surfaces. Extra positional handler
        arguments (for example a profile id from the URL) ride
        along after the form body. When a handler returns an
        in-context form error, the originating form is
        re-rendered (error_render_fn, defaulting to
        render_fn) with the error panel and preserved input.
        """

        try:
            data = data_fn(services, body, *extra)
        except handlers.UserError as error:
            if api:
                self._send_error_json(str(error), status=400)
            else:
                self._send_html(
                    templates.error_page(
                        error.title or "Invalid selection",
                        str(error),
                        status_kind="warn",
                    ),
                    status=400,
                )
            return True
        except ValueError as error:
            if api:
                self._send_error_json(str(error), status=400)
            else:
                self._send_html(
                    templates.error_page(
                        "Invalid selection",
                        str(error),
                        status_kind="warn",
                    ),
                    status=400,
                )
            return True

        if api:
            if (
                isinstance(data, dict)
                and isinstance(data.get("form_error"), dict)
            ):
                form_error = data["form_error"]

                self._send_error_json(
                    form_error.get("message", "invalid input"),
                    status=form_error.get("status", 400),
                )
            else:
                self._send_json(data)
        elif (
            isinstance(data, dict)
            and isinstance(data.get("form_error"), dict)
        ):
            form_error = data["form_error"]
            error_render = error_render_fn or render_fn

            self._send_html(
                error_render(data),
                status=form_error.get("status", 400),
            )
        else:
            self._send_html(render_fn(data))

        return True

    @staticmethod
    def _match_preview_media(path):
        """(token, kind) for preview media routes, else None."""
        import re

        match = re.fullmatch(
            r"/preview/([A-Za-z0-9_-]{8,64})/(original|sample)",
            path or "",
        )

        if match is None:
            return None

        return match.group(1), match.group(2)

    @staticmethod
    def _match_preview_action(path):
        """(token, action) for preview POST routes, else None."""

        import re

        match = re.fullmatch(
            r"/preview/([A-Za-z0-9_-]{8,64})/"
            r"(generate|override|accept|reject|close|"
            r"acknowledge|preserve)",
            path or "",
        )

        if match is None:
            return None

        return match.group(1), match.group(2)

    def _preview_media(self, token, kind, *, api=False):
        """
        Serve one preview-owned media file with byte ranges. The
        token is the only request input; the filesystem path comes
        from the server-side preview registry and is revalidated
        there, so no request can cause an arbitrary filesystem
        read. PreviewError surfaces as a 400 like other invalid
        input.
        """

        from app.application.preview_service import PreviewError

        services = self._services()

        try:
            if kind == "sample":
                resolved = (
                    services.preview_service
                    .resolve_sample_path(token)
                )
            else:
                resolved = (
                    services.preview_service
                    .resolve_original_path(token)
                )
        except PreviewError as error:
            if api:
                return self._send_error_json(
                    str(error), status=400
                )

            return self._send_html(
                templates.error_page(
                    "Preview unavailable",
                    str(error),
                    status_kind="warn",
                ),
                status=400,
            )

        return self._send_file_range(
            resolved, self._media_content_type(resolved)
        )

    def _match(self, path, pattern):
        import re

        match = re.fullmatch(pattern, path)

        if match is None:
            return None

        return match.group(1)

    @staticmethod
    def _optional_query(query, name):
        """
        First value of a query parameter, or None. Blank values are
        treated as absent so filter forms can be submitted empty.
        """

        values = query.get(name)

        if not values:

            return None

        value = values[0]

        if value is None or not str(value).strip():

            return None

        return value

    @staticmethod
    def _optional_int_query(query, name):
        """
        Integer query parameter, or None. Non-numeric values raise
        ValueError and surface as a 400 like other invalid input.
        """

        value = NamoaRequestHandler._optional_query(
            query, name
        )

        if value is None:

            return None

        try:

            return int(value)

        except (TypeError, ValueError):

            raise ValueError(f"invalid {name} filter")

    def _read_form_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0

        raw = self.rfile.read(length).decode("utf-8")

        return parse_qs(raw)


def make_handler(service_factory, database_path=None):
    """Bind the service factory into a handler class."""

    class BoundHandler(NamoaRequestHandler):
        pass

    # Class bodies do not capture enclosing-function locals; assign
    # the bound configuration as class attributes after creation.
    # staticmethod prevents instance access from binding `self`.
    BoundHandler.service_factory = staticmethod(service_factory)
    BoundHandler.database_path = database_path

    return BoundHandler


def create_server(service_factory, *, host="127.0.0.1", port=8080, database_path=None):
    """
    Create a ThreadingHTTPServer serving the NAMOA GUI.

    Each request builds a fresh service graph via `service_factory`
    (a callable returning app.web.composition.Services).
    """

    handler = make_handler(service_factory, database_path=database_path)

    server = ThreadingHTTPServer((host, port), handler)

    server.daemon_threads = True

    return server
