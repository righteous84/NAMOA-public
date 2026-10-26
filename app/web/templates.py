"""
Server-rendered HTML templates for the NAMOA GUI.

All user-supplied and persisted values are escaped before rendering.
The template layer only formats the already-assembled page data; it
contains no intelligence and no persistence access.
"""

from app.display_labels import validity_reason_label
from app.web.serializers import (
    organisation_intent_label,
    opportunity_label,
    opportunity_set_display,
    esc,
    format_bytes,
    format_bytes_human,
    priority_band,
    risk_display,
)


# ---------------------------------------------------------
# Layout
# ---------------------------------------------------------

NAV_ITEMS = [
    ("/", "Dashboard", "dashboard"),
    ("/media", "Media Library", "media"),
    ("/analysis", "Analysis", "analysis"),
    ("/scan", "Scan", "scan"),
    ("/quick-find", "Quick Find", "quick-find"),
    ("/intelligence", "Intelligence", "intelligence"),
    ("/opportunities", "Opportunities", "opportunities"),
    ("/preferences", "Preferences", "preferences"),
    ("/organisation", "Organisation", "organisation"),
    ("/executions", "Queue", "executions"),
    ("/runs", "Runs", "runs"),
]


NAV_ICONS = {
    "/": "◉",
    "/media": "◍",
    "/analysis": "◎",
    "/scan": "⌗",
    "/quick-find": "✦",
    "/intelligence": "◆",
    "/opportunities": "★",
    "/preferences": "♥",
    "/organisation": "⬔",
    "/executions": "≣",
    "/runs": "●",
}

ORG_NAV_ICONS = {
    "/organisation": "○",
    "/organisation/profiles": "◫",
    "/organisation/integrations": "⎔",
    "/organisation/whatif": "⌁",
    "/organisation/preflight": "⌖",
    "/organisation/reconcile": "◐",
    "/organisation/executions": "▶",
    "/organisation/scope-executions": "↺",
}

SECTION_ICONS = {
    "profile": "◩",
    "presets": "✹",
    "templates": "▤",
    "progress": "◔",
    "sources": "⍋",
    "destinations": "▦",
    "categories": "◈",
    "rules": "≡",
    "folders": "◧",
    "naming": "✎",
    "advanced": "⚙",
    "actions": "✔",
    "summary": "☰",
    "technical": "⎆",
}


# ---------------------------------------------------------
# Sprint 15 organisation workspace secondary navigation.
#
# The top-level nav keeps a single Organisation entry.
# Every organisation page renders this secondary bar so
# no Sprint 15 capability requires a hidden direct URL.
# ---------------------------------------------------------

ORG_NAV_ITEMS = [
    ("/organisation", "Overview"),
    ("/organisation/profiles", "Profiles"),
    ("/organisation/integrations", "Settings"),
    ("/organisation/whatif", "Test"),
    ("/organisation/preflight", "Preflight"),
    ("/organisation/reconcile", "Preview and approve"),
    ("/organisation/executions", "Executions"),
    ("/organisation/scope-executions", "History"),
]


def _organisation_nav():
    links = "".join(
        f'<a class="subnav-item" href="{href}" data-orglink="{href}">'
        f'<span class="subnav-icon" aria-hidden="true">'
        f'{esc(ORG_NAV_ICONS.get(href, "○"))}</span>'
        f"{label}</a>"
        for href, label in ORG_NAV_ITEMS
    )

    return f'<nav class="subnav" aria-label="Organisation workspace">{links}</nav>'


def _sidebar_nav(active):
    parts = []

    for key, label, slug in NAV_ITEMS:
        icon = esc(NAV_ICONS.get(key, "○"))
        matches = key == active or slug == active
        is_active = " active" if matches else ""
        current_attr = ' aria-current="page"' if matches else ""
        parts.append(
            f'<a class="nav-item{is_active}" href="{key}"{current_attr}>'
            f'<span class="nav-icon" aria-hidden="true">'
            f"{icon}</span>"
            f'<span class="nav-label">{label}</span></a>'
        )

        if key == "/organisation" and active == "organisation":
            sub = "".join(
                f'<a class="nav-sub-item" href="{href}" '
                f'data-orglink="{href}">'
                f'<span class="nav-sub-icon" aria-hidden="true">'
                f'{esc(ORG_NAV_ICONS.get(href, "○"))}</span>'
                f"{label}</a>"
                for href, label in ORG_NAV_ITEMS
            )
            parts.append(
                f'<div class="nav-sub" aria-label="Organisation section">'
                f"{sub}</div>"
            )

    return "".join(parts)


def layout(title, active, content, *, page_class="", refreshed_at=None, head_actions=""):

    refresh_attr = (
        f' data-refreshed-at="{esc(refreshed_at)}"'
        if refreshed_at
        else ""
    )

    # The shared approval modal carries optimisation-specific
    # semantics (including delete-original language) and is
    # only ever opened by optimisation flows. Suppress it on
    # Organisation pages so assistive technology and page
    # text never present unrelated optimisation deletion
    # controls inside the organisation workflow.
    approve_modal_html = ""
    if active != "organisation":
        approve_modal_html = """
<div class="modal-backdrop" id="approve-modal" hidden>
  <div class="modal" role="dialog" aria-modal="true" aria-labelledby="approve-modal-title">
    <h2 id="approve-modal-title">Confirm approval</h2>
    <p class="modal-message" id="approve-modal-message"></p>
    <p class="muted" id="approve-modal-note">
      Approval adds approved job(s) to the optimisation queue.
      Nothing will run until you start it.
    </p>
    <form id="approve-modal-form" method="post" action="">
      <div id="approve-modal-fields"></div>
      <label class="check-label">
        <input type="checkbox" name="delete_original" value="true" id="approve-delete-original"/>
        Delete original after successful optimisation
      </label>
      <p class="muted">
        Deletion is a separate lifecycle action that runs only after
        verified successful replacement; it is never automatic.
        After deletion, rollback to the original bytes is no longer
        available.
      </p>
      <div class="modal-actions">
        <button type="submit" class="btn">Confirm approval</button>
        <button type="button" class="btn small ghost" id="approve-modal-cancel">Cancel</button>
      </div>
    </form>
  </div>
</div>
<div class="modal-backdrop" id="reject-modal" hidden>
  <div class="modal" role="dialog" aria-modal="true" aria-labelledby="reject-modal-title">
    <h2 id="reject-modal-title">Reject optimisation</h2>
    <p class="modal-message" id="reject-modal-message"></p>
    <p class="muted" id="reject-modal-note">
      Rejection removes the recommendation from your active
      recommendations. The decision is kept in history.
      Nothing is queued or executed.
    </p>
    <form id="reject-modal-form" method="post" action="">
      <div id="reject-modal-fields"></div>
      <div class="modal-actions">
        <button type="submit" class="btn btn-danger">Reject</button>
        <button type="button" class="btn small ghost" id="reject-modal-cancel">Cancel</button>
      </div>
    </form>
  </div>
</div>"""

    # Every organisation page carries the workspace
    # secondary navigation so no Sprint 15 capability
    # requires a hidden direct URL.
    if active == "organisation":
        content = _organisation_nav() + content

    nav = _sidebar_nav(active)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · NAMOA</title>
<script>
try {{
  var namoaTheme = localStorage.getItem("namoa-theme");
  if (namoaTheme === "light" || namoaTheme === "dark") {{
    document.documentElement.setAttribute("data-theme", namoaTheme);
  }}
}} catch (e) {{}}
</script>
<link rel="stylesheet" href="/static/style.css">
</head>
<body class="{esc(page_class)}"{refresh_attr}>
<div class="app">
  <aside class="sidebar">
    <div class="brand">
      <span class="brand-mark">N</span>
      <span class="brand-name">NAMOA</span>
    </div>
    <nav class="nav">{nav}</nav>
    <div class="sidebar-foot">
      <span class="health" id="namoa-health" data-state="checking" role="status" aria-live="polite">
        <span class="health-dot" aria-hidden="true"></span>
        <span class="health-text" id="namoa-health-text">CHECKING</span>
      </span>
      <span class="sidebar-identity">NAMOA</span>
      <span class="sidebar-mood" id="namoa-mood" aria-hidden="true"></span>
      <span class="sidebar-page">Optimisation Work Queue</span>
    </div>
  </aside>
  <main class="main">
    <header class="page-head">
      <h1>{esc(title)}</h1>
      <div class="page-head-side">
        {head_actions}
        <div class="refresh-note" id="refresh-note"></div>
        <button id="theme-toggle" class="btn small ghost" type="button">Light mode</button>
        <div class="utility-menu">
          <button id="utility-cog" class="icon-btn" type="button" aria-label="Settings" aria-haspopup="menu" aria-expanded="false" aria-controls="utility-dropdown"><span aria-hidden="true">⚙</span></button>
          <div class="utility-dropdown" id="utility-dropdown" role="menu" hidden>
            <a href="/organisation/integrations" role="menuitem"><span aria-hidden="true">⚙</span> Settings</a>
            <button type="button" id="utility-about" role="menuitem"><span aria-hidden="true">ⓘ</span> About NAMOA</button>
          </div>
        </div>
      </div>
    </header>
    {content}
  </main>
</div>
<div
  class="notification-panel"
  id="notification-panel"
  role="region"
  aria-label="Notifications"
  aria-live="polite"></div>
{approve_modal_html}
<div class="modal-backdrop" id="about-modal" hidden>
  <div class="modal modal-narrow" role="dialog" aria-modal="true" aria-labelledby="about-modal-title">
    <div class="about-brand"><span class="brand-mark" aria-hidden="true">N</span><span class="about-name">NAMOA <span class="about-version">v1</span></span></div>
    <h2 id="about-modal-title" class="about-release release-mark">Singing Monkey</h2>
    <svg class="about-scene" viewBox="0 0 200 120" role="img" aria-label="A monkey celebrating under a palm tree with a banana">
      <circle cx="168" cy="22" r="12" fill="#f39c12" opacity="0.85"/>
      <rect x="0" y="102" width="200" height="18" fill="#1abc9c" opacity="0.35"/>
      <ellipse cx="100" cy="108" rx="46" ry="8" fill="#8a5a00" opacity="0.45"/>
      <path d="M52 104 C 56 78, 54 60, 48 44" stroke="#8a5a00" stroke-width="6" fill="none" stroke-linecap="round"/>
      <path d="M48 44 C 34 34, 22 34, 12 40 C 24 42, 34 46, 48 50 Z" fill="#1e8449"/>
      <path d="M48 44 C 44 30, 50 20, 58 14 C 56 26, 56 36, 54 46 Z" fill="#1e8449"/>
      <path d="M48 44 C 60 34, 72 34, 82 40 C 70 42, 60 46, 52 50 Z" fill="#1e8449"/>
      <path d="M128 106 C 140 100, 152 100, 160 106 C 152 104, 142 118, 130 114 C 124 112, 125 108, 128 106 Z" fill="#f5d76e"/>
      <circle cx="100" cy="66" r="10" fill="#8a5a00"/>
      <circle cx="100" cy="70" r="22" fill="#a9713f"/>
      <circle cx="79" cy="62" r="7" fill="#a9713f"/>
      <circle cx="121" cy="62" r="7" fill="#a9713f"/>
      <circle cx="79" cy="62" r="3" fill="#e8b07d"/>
      <circle cx="121" cy="62" r="3" fill="#e8b07d"/>
      <ellipse cx="100" cy="78" rx="11" ry="8" fill="#e8b07d"/>
      <rect x="86" y="64" width="28" height="9" rx="4.5" fill="#16202e"/>
      <line x1="86" y1="68" x2="79" y2="66" stroke="#16202e" stroke-width="2"/>
      <line x1="114" y1="68" x2="121" y2="66" stroke="#16202e" stroke-width="2"/>
      <path d="M94 80 Q 100 84, 106 80" stroke="#5a3a1a" stroke-width="2" fill="none" stroke-linecap="round"/>
      <path d="M84 52 Q 80 40, 88 34" stroke="#a9713f" stroke-width="4" fill="none" stroke-linecap="round"/>
      <path d="M116 52 Q 120 40, 112 34" stroke="#a9713f" stroke-width="4" fill="none" stroke-linecap="round"/>
    </svg>
    <p class="about-tagline">Intelligent media analysis and optimisation system</p>
    <p class="muted">Copyright &copy; 2026 Drewzy</p>
    <details class="disclosure"><summary>Licence</summary><p class="muted">Licence information to be confirmed.</p></details>
    <div class="modal-actions">
      <button type="button" class="btn" id="about-modal-okay">Okay</button>
    </div>
  </div>
</div>
<script src="/static/app.js"></script>
</body>
</html>"""


def error_page(title, message, *, status_kind="error"):
    badge = {
        "error": ("Error", "failed"),
        "empty": ("Nothing here", "unknown"),
        "warn": ("Notice", "stale"),
    }.get(status_kind, ("Notice", "unknown"))

    content = f"""
<section class="card">
  <div class="card-head">
    <span class="badge {badge[1]}">{badge[0]}</span>
    <h2>{esc(title)}</h2>
  </div>
  <p class="muted">{esc(message)}</p>
  <p><a class="btn ghost" href="/">Back to dashboard</a></p>
</section>
"""

    return layout(title, "dashboard", content)


def not_found_page(message):
    return error_page(
        "Not found",
        message,
        status_kind="empty",
    )


def server_error_page(message):
    return error_page(
        "Internal error",
        message,
        status_kind="error",
    )


# ---------------------------------------------------------
# Reusable fragments
# ---------------------------------------------------------


def badge(label, kind):
    return f'<span class="badge {esc(kind)}">{esc(label)}</span>'


def _opportunity_badge(opportunity):
    """
    Human-facing opportunity badge. The stored domain value is
    mapped to user language; the raw value is never altered.
    """

    label, kind = opportunity_label(opportunity)

    return badge(label, kind)


def _priority_cell(score):
    """
    Priority as a human band label primary with the exact stored
    score secondary. Display only: ranking and the stored score
    are untouched.
    """

    band = priority_band(score)

    band_class = {
        "High": "priority-high",
        "Medium": "priority-medium",
    }.get(band, "priority-low")

    try:
        shown = f"{float(score):.2f}"
    except (TypeError, ValueError):
        shown = None

    score_html = (
        f' <span class="muted priority-score">{esc(shown)}</span>'
        if shown is not None
        else ""
    )

    return (
        f'<span class="priority-band {band_class}">'
        f'<span class="band-dot" aria-hidden="true">●</span>'
        f"{esc(band)}</span>{score_html}"
    )


def _risk_cell(risk):
    """
    Stored categorical risk as a human label with dedicated
    risk styling. The risk value and calculation stay
    authoritative; the styling never reuses the Current/Stale/
    Failed badge vocabulary.
    """

    label, css_class = risk_display(risk)

    return f'<span class="risk {css_class}">{esc(label)}</span>'


def _saving_cell(item):
    """
    Potential saving as a human estimate primary with the stored
    percentage secondary. Display only: byte counts and percents
    are unchanged.
    """

    human = format_bytes_human(item.get("estimated_saved_bytes"))
    percent = item.get("saving_percent") or ""

    if human == "n/a" and not percent:
        return '<span class="muted">n/a</span>'

    if not percent:
        return f'<span class="saving-main">{esc(human)}</span>'

    return (
        f'<span class="saving-main">{esc(human)}</span> '
        f'<span class="muted">({esc(percent)})</span>'
    )


def _confidence_cell(item):
    """
    Confidence percent primary with the calibrated value exposed
    as a tooltip rather than a competing column. Display only.
    """

    confidence = item.get("confidence_percent") or "n/a"
    calibrated = item.get("calibrated_confidence_percent") or ""

    if not calibrated:
        return esc(confidence)

    return (
        f'<span title="Calibrated confidence: '
        f'{esc(calibrated)}">{esc(confidence)}</span>'
    )


def _preview_icon_link(media_id, file_name):
    """
    Compact preview affordance for dense table contexts. Native
    link to the existing preview route; the accessible name and
    tooltip carry the meaning so the icon is never the only
    signal for any user.
    """

    label = f"Open preview for {file_name}"

    return (
        f'<a class="preview-icon-link" '
        f'href="/preview/new?origin=analysis&amp;ref={media_id}" '
        f'aria-label="{esc(label)}" title="{esc(label)}">'
        f'<span aria-hidden="true">⌕</span></a>'
    )


def _preview_icon_button(media_id, file_name):
    """
    Preview button for dashboard recommendation cards: a real
    button-styled link with a small inline magnifier icon
    followed by the visible word Preview. Same destination and
    semantics as every other Preview control; the icon uses
    currentColor so it follows the button text in both themes.
    """

    label = f"Preview optimisation for {file_name}"

    return (
        f'<a class="btn small btn-preview" '
        f'href="/preview/new?origin=analysis&amp;ref={media_id}" '
        f'aria-label="{esc(label)}" title="{esc(label)}">'
        f'<svg width="14" height="14" viewBox="0 0 16 16" '
        f'aria-hidden="true" focusable="false">'
        f'<circle cx="7" cy="7" r="5" fill="none" '
        f'stroke="currentColor" stroke-width="2"/>'
        f'<line x1="11" y1="11" x2="15" y2="15" '
        f'stroke="currentColor" stroke-width="2" '
        f'stroke-linecap="round"/>'
        f"</svg><span>Preview</span></a>"
    )


def _validity_reason_cell(reason):
    """
    Stored validity reason as human wording primary with the raw
    value muted secondary. Display only: the stored reason and
    all validity semantics stay authoritative elsewhere.
    """

    label = validity_reason_label(reason)

    if reason and label != reason:
        return f'{esc(label)} <span class="muted">{esc(reason)}</span>'

    return esc(label)


def _job_visibility_badge(job):
    """
    Cross-path execution visibility badge for recommendation
    cards. Queued/in-progress work reads as requested/running
    (never completed); terminal success reads as completed.
    Empty when there is no informative job state.
    """

    if not job:
        return ""

    state = job.get("state", "")

    if state in ("approved", "planned"):
        text = "Optimisation Requested"
    elif state == "succeeded":
        text = "Optimisation Completed"
    else:
        text = job.get("state_label") or "In progress"

    job_id = job.get("id")

    link_html = (
        f' <a href="/executions/{job_id}">Job #{job_id}</a>'
        if job_id is not None
        else ""
    )

    return (
        f'<p class="rec-job">'
        f"{badge(text, job.get('state_badge') or 'pending')}"
        f"{link_html}</p>"
    )


def empty_state(title, message):
    return f"""
<div class="empty-state">
  <h3>{esc(title)}</h3>
  <p>{esc(message)}</p>
</div>
"""


def stat_card(label, value, *, hint="", extra=""):
    hint_html = (
        f'<div class="stat-hint">{esc(hint)}</div>'
        if hint
        else ""
    )

    return f"""
<div class="stat-card">
  <div class="stat-value">{value}</div>
  <div class="stat-label">{esc(label)}</div>
  {hint_html}
  {extra}
</div>
"""


def table(headers, rows, *, empty_title="No data", empty_message=""):
    if not rows:
        return empty_state(
            empty_title,
            empty_message or "There is nothing to show yet.",
        )

    head = "".join(
        f"<th>{esc(header)}</th>" for header in headers
    )

    body = "".join(
        f"<tr>{''.join(f'<td>{cell}</td>' for cell in row)}</tr>"
        for row in rows
    )

    return f"""
<div class="table-wrap">
<table class="data-table">
  <thead><tr>{head}</tr></thead>
  <tbody>{body}</tbody>
</table>
</div>
"""


def link(url, label):
    return f'<a href="{esc(url)}">{esc(label)}</a>'


def media_link(media_id, label):
    return link(f"/media/{media_id}", label)


def run_link(run_id, label=None):
    label = label if label is not None else f"Run #{run_id}"
    return link(f"/runs/{run_id}", label)


def facts(items):
    """Key/value fact grid (idempotent, escaped)."""

    rows = "".join(
        f'<div class="fact"><span class="fact-key">{esc(k)}</span>'
        f'<span class="fact-value">{v}</span></div>'
        for k, v in items
    )

    return f'<div class="facts">{rows}</div>'


# ---------------------------------------------------------
# Pages
# ---------------------------------------------------------


def render_dashboard(data):
    summary = data["summary"]
    storage = data["storage"]
    cards = data.get("cards") or []
    runs = data.get("recent_runs") or []
    scan_meta = data.get("scan_meta") or {}
    queue_counts = data.get("queue_counts") or {}

    stat_cards = "".join(
        [
            stat_card(
                "Active media",
                summary["total_active_lineages"],
                hint="lineages present on disk",
            ),
            stat_card(
                "Missing media",
                summary["total_missing_lineages"],
                hint="observed but absent",
            ),
            stat_card(
                "Current analysis",
                summary["lineages_with_valid_analysis"],
                hint="valid for current file state",
            ),
            stat_card(
                "Needs analysis",
                summary["lineages_requiring_analysis"],
                hint="stale or never analysed",
            ),
            stat_card(
                "Opportunities",
                summary["opportunity_count"],
                hint="Current recommendations",
            ),
            stat_card(
                "Library size",
                format_bytes_human(
                    summary.get("total_library_bytes")
                ),
                hint="active lineages",
            ),
            stat_card(
                "Potential savings",
                format_bytes_human(
                    summary.get("total_estimated_saved_bytes")
                ),
                hint="from current recommendations",
            ),
            stat_card(
                "Last scan",
                summary["last_scanned_at"],
                hint="background scans",
            ),
        ]
    )

    left_content = f"""
<section class="card">
  <div class="card-head">
    <h2>Library overview</h2>
    <a class="btn small" href="/intelligence">Library intelligence</a>
  </div>
  <div class="stat-grid">{stat_cards}</div>
</section>
"""

    if cards:
        rec_cards = "".join(
            _dashboard_rec_card(item) for item in cards
        )

        left_content += f"""
<section class="card">
  <div class="card-head">
    <h2>Recommendations</h2>
    <a class="btn small" href="/opportunities">View all recommendations</a>
  </div>
  <p class="muted">
    What NAMOA suggests changing, in priority order. Approving adds
    approved job(s) to the optimisation queue; nothing runs until
    you start it.
  </p>
  <div class="selection-bar rec-toolbar">
    <label class="select-all-label">
      <input type="checkbox" id="rec-select-all">
      Select all
    </label>
    <button type="button" class="btn small js-approve-selected">Approve Selected Optimisations</button>
    <button type="button" class="btn small js-approve-all">Approve All Optimisations</button>
    <button type="button" class="btn small btn-danger js-reject-selected">Reject selected optimisations</button>
    <span class="muted" id="rec-selection-count"></span>
  </div>
  <div class="rec-cards">{rec_cards}</div>
</section>
"""

    else:
        left_content += f"""
<section class="card">
  <div class="card-head"><h2>Recommendations</h2></div>
  <div class="empty-state">
    <h3>No current recommendations</h3>
    <p>
      No up-to-date analysis produced an optimisation
      opportunity. Run a scan to check your library.
    </p>
    <p><a class="btn small" href="/scan">Run a scan</a></p>
  </div>
</section>
"""

    right_content = _dashboard_right_rail(
        scan_meta=scan_meta,
        queue_counts=queue_counts,
        runs=runs,
        opportunity_count=summary.get("opportunity_count"),
    )

    content = f"""
<div class="dashboard-layout">
  <div class="dashboard-main">{left_content}</div>
  <aside class="dashboard-rail">{right_content}</aside>
</div>
"""

    return layout("Dashboard", "dashboard", content, refreshed_at=data.get("refreshed_at"))


def _dashboard_right_rail(
    *,
    scan_meta,
    queue_counts,
    runs,
    opportunity_count,
):
    """
    The dashboard's right-hand rail: useful authoritative operational
    context (scan status, optimisation-queue summary, recent activity)
    so the available space is used meaningfully without inventing any
    intelligence or statistics.
    """

    scan_items = [
        ("Last scan", esc(scan_meta.get("last_scanned_at") or "never")),
        ("Active lineages", esc(scan_meta.get("active_lineage_count") or 0)),
        ("Missing lineages", esc(scan_meta.get("missing_lineage_count") or 0)),
    ]

    queue_items = [
        ("Approved / queued", esc(queue_counts.get("approved", 0))),
        ("Running", esc(queue_counts.get("running", 0))),
        ("Completed", esc(queue_counts.get("completed", 0))),
        ("Needs attention", esc(queue_counts.get("attention", 0))),
        ("Recommendations", esc(opportunity_count or 0)),
    ]

    recent = ""

    if runs:
        recent = "".join(
            f"""
<div class="rail-run">
  <span class="rail-run-run">{run_link(run["id"], f"Run #{run['id']}")}</span>
  <span class="rail-run-media">{media_link(run["media_id"], run["media_name"] or "media")}</span>
  {badge(run["status_label"], run["status_badge"])}
</div>"""
            for run in runs[:5]
        )
    else:
        recent = '<p class="muted">No analysis runs yet.</p>'

    return f"""
<section class="card rail-card">
  <div class="card-head"><h2>What should I do next?</h2></div>
  <ul class="rail-steps">
    <li>Scan your library to find optimisation opportunities.</li>
    <li>Review the recommendations on this page.</li>
    <li>Approve what you want; nothing runs until you start it.</li>
  </ul>
  <p><a class="btn small" href="/scan">Run a scan</a></p>
</section>
<section class="card rail-card">
  <div class="card-head"><h2>Current scan</h2></div>
  {facts(scan_items)}
</section>
<section class="card rail-card">
  <div class="card-head">
    <h2>Optimisation queue</h2>
    <a class="btn small" href="/executions">Queue</a>
  </div>
  {facts(queue_items)}
</section>
<section class="card rail-card">
  <div class="card-head">
    <h2>Recent activity</h2>
    <a class="btn small" href="/runs">Runs</a>
  </div>
  <div class="rail-runs">{recent}</div>
</section>
"""


def _dashboard_rec_card(item):
    """
    Phase 3 recommendation card: change first, then why, expected
    outcome, confidence/risk, an explicit selection control, and an
    approval action that opens the confirmation modal and reuses the
    existing approval boundary.
    """

    change_summary = item.get("change_summary") or {}

    why_lines = list(item.get("rationale") or [])

    # The metric group below now carries the analytical score,
    # expected saving, confidence, and risk, so the four
    # technical rationale lines (exact format produced by
    # RecommendationPrioritisationService) are filtered out of
    # the supporting text. Any other explanation line is still
    # shown, and the exact values remain in the detail-page
    # technical disclosures.
    why_lines = [
        line
        for line in why_lines
        if not str(line).startswith(
            (
                "Analytical value score ",
                "Absolute expected saving ",
                "Calibrated confidence ",
                "Risk '",
            )
        )
    ]

    why_text = (
        why_lines[0]
        if why_lines
        else ""
    )

    # The headline already states single-line
    # outcomes, so a domain/value line repeating
    # the same values adds nothing; anything with
    # new information stays.
    if why_text and change_summary.get("one_liner"):
        lines = change_summary.get("lines") or []

        if len(lines) == 1:
            only = lines[0] or {}
            headline = str(
                change_summary.get("one_liner") or ""
            ).casefold()
            current = str(only.get("current") or "").casefold()
            target = str(only.get("target") or "").casefold()

            if current and target and (
                current in headline and target in headline
            ):
                change_summary = dict(change_summary)
                change_summary["lines"] = []

    confidence = item.get("confidence_percent")

    try:
        analytical_score = f"{float(item.get('opportunity_score')):.2f}"
    except (TypeError, ValueError):
        analytical_score = "n/a"

    expected_saving = format_bytes_human(
        item.get("estimated_saved_bytes")
    )

    metrics_html = (
        '<div class="rec-metrics">'
        f'<div class="rec-metric"><span class="rec-metric-label">Analytical score</span><span class="rec-metric-value">{esc(analytical_score)}</span></div>'
        f'<div class="rec-metric"><span class="rec-metric-label">Confidence</span><span class="rec-metric-value">{esc(confidence) if confidence else "n/a"}</span></div>'
        f'<div class="rec-metric"><span class="rec-metric-label">Risk</span><span class="rec-metric-value">{_risk_cell(item.get("risk"))}</span></div>'
        f'<div class="rec-metric"><span class="rec-metric-label">Expected Saving</span><span class="rec-metric-value saving-main">{esc(expected_saving)}</span></div>'
        "</div>"
    )

    return f"""
<div class="rec-card" data-media-id="{item["media_id"]}">
  <div class="rec-card-head">
    <label class="rec-select">
      <input type="checkbox" class="rec-select-box" value="{item["media_id"]}"
             aria-label="Select {esc(item["file_name"])}">
      Select
    </label>
    <a class="rec-media" href="/opportunities/{item["media_id"]}" aria-label="Recommendation detail for {esc(item["file_name"])}"><h3 class="rec-media-heading">{esc(item["file_name"])}</h3></a>    {_opportunity_badge(item["opportunity"] or "media_optimisation")}
  </div>
  <div class="rec-body">
    <div class="rec-main">
      {_change_summary_block(change_summary, metrics_html=metrics_html)}
      {('<p class="rec-why">' + esc(why_text) + "</p>") if why_text and why_text != change_summary.get("one_liner") else ""}
    </div>
    <div class="rec-actions">
      <button type="button" class="btn small js-approve-single"
              data-media-id="{item["media_id"]}"
              data-name="{esc(item["file_name"])}">Approve</button>
      <button type="button" class="btn small btn-danger js-reject-single"
              data-media-id="{item["media_id"]}"
              data-name="{esc(item["file_name"])}">Reject</button>
      {_preview_icon_button(item["media_id"], item["file_name"])}
{_job_visibility_badge(item.get("active_job"))}
    </div>
  </div>
</div>
"""


def render_media(data):
    entries = data["entries"]

    if not entries:
        content = empty_state(
            "The library is empty",
            "No media lineages have been observed yet. "
            "Use the Scan page to scan a library path.",
        )
        return layout("Media", "media", content, refreshed_at=data.get("refreshed_at"))

    rows = []

    for item in entries:
        facts = item["technical_facts"]

        codec = facts["video_codec"] if facts else "—"
        resolution = facts["resolution"] if facts else "—"
        hdr = (
            "Yes" if facts and facts["is_hdr"] else "No"
        ) if facts else "—"

        rows.append(
            [
                media_link(item["media"]["id"], item["media"]["file_name"]),
                item["media"]["file_path"],
                format_bytes(item["media"]["file_size_bytes"]),
                badge(item["status_label"], item["status_badge"]),
                codec,
                resolution,
                hdr,
                link(f"/opportunities/{item['media']['id']}", "view"),
            ]
        )

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Media inventory</h2>
    <input
      type="search"
      id="filter-input"
      class="filter-input"
      placeholder="Filter by name or path…"
      aria-label="Filter media table">
  </div>
  {table(
      ["Name", "Path", "Size", "Status", "Codec", "Resolution",
       "HDR", ""],
      rows,
      empty_title="No media",
      empty_message="No media lineages have been observed yet.",
  )}
</section>
"""

    return layout("Media", "media", content, refreshed_at=data.get("refreshed_at"))


def render_media_detail(data):
    entry = data["entry"]
    history = data["history"]
    media = entry["media"]

    status_label_, status_badge = (
        entry["status_label"],
        entry["status_badge"],
    )

    tech_facts = entry["technical_facts"]

    media_id = media["id"]

    fact_items = [
        ("Name", esc(media["file_name"])),
        ("Path", esc(media["file_path"])),
        ("Size", esc(format_bytes(media["file_size_bytes"]))),
        ("Media ID", esc(media["id"])),
        ("Status", badge(status_label_, status_badge)),
        ("Analysis required", "Yes" if entry["analysis_required"] else "No"),
        ("Reason", esc(entry["reason"])),
    ]

    if entry["valid_run_id"] is not None:
        fact_items.append(
            (
                "Current analysis run",
                run_link(entry["valid_run_id"], f"Run #{entry['valid_run_id']}"),
            )
        )

    if entry["opportunity"] is not None:
        fact_items.append(
            (
                "Opportunity",
                link(
                    f"/opportunities/{media['id']}",
                    entry["opportunity"],
                ),
            )
        )

    if tech_facts is not None:
        fact_items += [
            ("Codec", esc(tech_facts["video_codec"])),
            ("Resolution", esc(tech_facts["resolution"])),
            ("Duration", esc(tech_facts["duration"])),
            ("Bitrate", esc(tech_facts["bitrate"])),
            ("Audio tracks", esc(tech_facts["audio_tracks"])),
            ("HDR", "Yes" if tech_facts["is_hdr"] else "No"),
            ("Container", esc(tech_facts["container"])),
            ("Analysed at", esc(tech_facts["analysed_at"])),
        ]

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>{esc(media['file_name'])}</h2>
    <div class="card-actions">
      <a class="btn small" href="/media/{media_id}/history">Full history</a>
      <a class="btn small ghost" href="/media">Back to inventory</a>
    </div>
  </div>
  {facts(fact_items)}
  <form method="post" action="/organisation/whatif/file"
        class="inline-form">
    <input type="hidden" name="media_id" value="{media_id}">
    <button class="btn small" type="submit">
      Preview in What-If
    </button>
    <span class="muted">
      Read-only organisation preview for this media item.
      Nothing is changed.
    </span>
  </form>
</section>
"""

    observations = history["observations"]

    if not observations:
        content += f"""
<section class="card">
  <div class="card-head"><h2>Observation history</h2></div>
  {empty_state(
      "No observations",
      "No filesystem observations have been recorded for this lineage.",
  )}
</section>
"""

    else:
        sections = []

        for item in observations:
            observation = item["observation"]
            runs = item["analysis_runs"]

            run_rows = [
                [
                    run_link(run["id"], f"Run #{run['id']}"),
                    badge(run["status_label"], run["status_badge"]),
                    run["started_at"],
                    run["completed_at"],
                    esc(run["error_message"] or "—"),
                ]
                for run in runs
            ]

            runs_html = table(
                ["Run", "Status", "Started", "Completed", "Error"],
                run_rows,
                empty_title="No runs",
                empty_message="No analysis runs against this observation.",
            )

            sections.append(
                f"""
<div class="observation-block">
  <h3>Observation #{observation['id']}
      <span class="muted">· {esc(observation['observed_at'])}</span></h3>
  {facts([
      ("Path", esc(observation["file_path"])),
      ("Size", esc(observation["size"])),
      ("Identity match", esc(observation["identity_match_method"])),
      ("Extension", esc(observation["file_extension"])),
  ])}
  {runs_html}
</div>
"""
            )

        content += f"""
<section class="card">
  <div class="card-head"><h2>Observation history</h2></div>
  {''.join(sections)}
</section>
"""

    content += f"""
<section class="card">
  <div class="card-head"><h2>Targeted analysis</h2></div>
  <p class="muted">
    Re-runs the canonical analysis for this lineage only. The
    validity authority decides whether a new run is required;
    an already-valid current analysis skips. Non-destructive.
  </p>
  <form method="post" action="/media/{media["id"]}/analyse">
    <button class="btn small" type="submit">Analyse this lineage</button>
  </form>
</section>
"""

    return layout("Media", "media", content, refreshed_at=data.get("refreshed_at"))


def render_media_history(data):
    """
    Per-media historical timeline (Sprint 12).

    Consolidates the existing authoritative reads for one lineage:
    current validity state, observations with their analysis runs,
    durable recommendation records with their lifecycle events,
    and execution outcomes. Sections are progressive-disclosure
    blocks; a section is omitted entirely when that history does
    not exist, so absence stays distinguishable from change.
    """

    entry = data["entry"]
    media = entry["media"]
    history = data.get("history") or {}
    recommendations = data.get("recommendations") or []
    executions = data.get("executions") or []

    media_id = media["id"]

    head = facts(
        [
            ("Media", media_link(media_id, media["file_name"])),
            ("Path", esc(media["file_path"])),
            (
                "Current media state",
                badge(entry["status_label"], entry["status_badge"]),
            ),
            ("Validity reason", esc(entry["reason"])),
            (
                "Analysis required now",
                "Yes" if entry["analysis_required"] else "No",
            ),
            (
                "Valid run",
                run_link(entry["valid_run_id"], f"Run #{entry['valid_run_id']}")
                if entry["valid_run_id"]
                else "(none recorded)",
            ),
            ("Historical runs", entry["historical_run_count"]),
        ]
    )

    sections = []

    observations = history.get("observations") or []

    timeline_blocks = []

    for item in reversed(observations):
        observation = item["observation"]
        runs = item["analysis_runs"]

        run_rows = [
            [
                run_link(run["id"], f"Run #{run['id']}"),
                badge(run["status_label"], run["status_badge"]),
                run["started_at"],
                run["completed_at"],
                link(f"/runs/{run['id']}/compare", "compare"),
            ]
            for run in runs
        ]

        timeline_blocks.append(
            f"""
<details class="disclosure">
  <summary>Observation #{observation['id']}
    <span class="muted">{esc(observation['observed_at'])} · {esc(observation['size'])}
      · {esc(observation['identity_match_method'])}</span>
  </summary>
  {facts([
      ("Path", esc(observation["file_path"])),
      ("Identity match", esc(observation["identity_match_method"])),
  ])}
  <p class="muted">
    {len(runs)} analysis run(s) against this observed file state.
  </p>
  {table(
      ["Run", "Status", "Started", "Completed", ""],
      run_rows,
      empty_title="No runs",
      empty_message="No analysis was executed against this observation.",
  )}
</details>
"""
        )

    if timeline_blocks:
        sections.append(
            f"""
<section class="card">
  <div class="card-head"><h2>Observation and run timeline</h2></div>
  <p class="muted">
    Newest first. Each observation is an immutable filesystem fact;
    each run is tied to the exact observation it analysed.
  </p>
  <div class="disclosure-stack">{''.join(timeline_blocks)}</div>
</section>
"""
        )

    if recommendations:
        rec_rows = [
            [
                link(
                    f"/recommendations/{item['record']['id']}",
                    f"Rec #{item['record']['id']}",
                ),
                badge(
                    item["record"]["state_label"],
                    item["record"]["state_badge"],
                ),
                esc(item["record"]["opportunity"]),
                f'{item["record"]["opportunity_score"]:.2f}'
                if item["record"]["opportunity_score"] is not None
                else "-",
                esc(item["record"]["saving_percent"]),
                len(item["events"]),
                link(
                    f"/recommendations/{item['record']['id']}/compare",
                    "compare",
                ),
            ]
            for item in recommendations
        ]

        sections.append(
            f"""
<section class="card">
  <div class="card-head"><h2>Recommendation history</h2></div>
  <p class="muted">
    Durable records produced by their runs, newest first. Records
    are historical results; newer analyses never rewrite them.
  </p>
  {table(
      ["Record", "State", "Opportunity", "Score", "Savings",
       "Events", ""],
      rec_rows,
  )}
</section>
"""
        )

    if executions:
        exec_rows = [
            [
                link(
                    f"/executions/{job['id']}",
                    f"Job #{job['id']}",
                ),
                badge(job["state_label"], job["state_badge"]),
                esc(job["opportunity"] or "-"),
                job["analysis_run_id"]
                and run_link(
                    job["analysis_run_id"],
                    f"Run #{job['analysis_run_id']}",
                )
                or "-",
                job["result_observation_id"]
                or "-",
                link(
                    f"/executions/{job['id']}",
                    "outcome detail",
                ),
            ]
            for job in executions
        ]

        sections.append(
            f"""
<section class="card">
  <div class="card-head"><h2>Execution outcomes</h2></div>
  <p class="muted">
    Every execution recorded for this lineage, newest first.
    Outcomes are shown exactly as recorded by the execution
    authority.
  </p>
  {table(
      ["Job", "Outcome", "Opportunity", "Producing run",
       "Result obs.", ""],
      exec_rows,
  )}
</section>
"""
        )

    if not sections:

        body = empty_state(
            "No history recorded yet",
            "This lineage has no observations, runs, "
            "recommendations or executions to show. A fresh "
            "library starts empty; history appears as the pipeline "
            "records it.",
        )

        sections.append(body)

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>History: {esc(media['file_name'])}</h2>
    <a class="btn small" href="/media/{media_id}">Media detail</a>
  </div>
  <p class="muted">
    Everything below comes from persisted relationships only:
    observations, runs, durable recommendations and execution
    outcomes are never recomputed or rewritten.
  </p>
  {head}
</section>
{''.join(sections)}
"""

    return layout("History", "media", content, refreshed_at=data.get("refreshed_at"))


def render_recommendation_compare_select(data):
    record = data["record"]
    others = data["others"]

    if not others:
        body = empty_state(
            "Nothing to compare",
            "This lineage has no other durable recommendation "
            "record yet. Comparison needs two records.",
        )
    else:
        options = "".join(
            f'<option value="{item["id"]}">'
            f'Rec #{item["id"]} · {esc(item["opportunity"])} '
            f'· {esc(item["state"])}</option>'
            for item in others
        )

        body = f"""
<form method="get" action="/recommendations/{record["id"]}/compare">
  <label class="compare-label" for="with">Compare Rec #{record["id"]} with</label>
  <div class="scan-row">
    <select id="with" name="with" class="path-input">
      {options}
    </select>
    <button type="submit" class="btn">Compare</button>
  </div>
</form>
"""

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Compare Recommendation #{record['id']}</h2>
    <a class="btn small ghost" href="/recommendations/{record["id"]}">Back to Rec #{record["id"]}</a>
  </div>
  {body}
</section>
"""

    return layout("Compare", "opportunities", content)


def render_recommendation_compare(data):
    comparison = data["comparison"]

    left = comparison["left"]

    right = comparison["right"]

    identity = comparison["intelligence_identity"]

    identity_text = {
        "identical": (
            "Identical recorded intelligence identity"
        ),
        "different": "Different recorded intelligence identities",
        "left_unrecorded": (
            "Not comparable: identity unrecorded on the left"
        ),
        "right_unrecorded": (
            "Not comparable: identity unrecorded on the right"
        ),
    }.get(identity["verdict"], "Identity not recorded on either side")

    def _display(value):

        if value is None:

            return "-"

        if isinstance(value, list):

            return ", ".join(str(item) for item in value) or "-"

        return str(value)

    rows = []

    for field in comparison["fields"]:
        if field["changed"] is True:
            marker = badge("changed", "stale")
        elif field["changed"] is False:
            marker = badge("same", "current")
        else:
            marker = badge("unavailable", "missing")

        rows.append(
            f"""
<tr>
  <td>{esc(field["label"])}</td>
  <td>{marker}</td>
  <td>{esc(_display(field["left"]))}</td>
  <td>{esc(_display(field["right"]))}</td>
</tr>"""
        )

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Comparing Rec #{left['id']} and Rec #{right['id']}</h2>
    <a class="btn small ghost" href="/recommendations/{left["id"]}">Back to Rec #{left["id"]}</a>
  </div>
  {facts([
      ("Left", link(f"/recommendations/{left['id']}", f"Rec #{left['id']}")),
      ("Right", link(f"/recommendations/{right['id']}", f"Rec #{right['id']}")),
      ("Same lineage", "Yes"),
      ("Same producing run", "Yes" if comparison["same_run"] else "No"),
      (
          "Intelligence identity",
          identity_text
          + (
              f' (<code>{esc((identity["left"] or "")[:12])}...</code>)'
              if identity["left"]
              else ""
          ),
      ),
  ])}
  <p class="muted">
    Values come verbatim from the stored records. A field whose
    value was never recorded on one side is marked unavailable
    rather than changed; no cause is implied by any difference.
  </p>
</section>
<section class="card">
  <div class="card-head"><h2>Field comparison</h2></div>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr><th>Field</th><th></th><th>Rec #{left['id']}</th><th>Rec #{right['id']}</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  </div>
</section>
"""

    return layout(
        "Compare",
        "opportunities",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def render_analysis(data):
    entries = data["entries"]

    counts = {}

    for item in entries:
        key = item["status_label"]
        counts[key] = counts.get(key, 0) + 1

    if entries:
        count_badges = "".join(
            f'{badge(f"{label}: {count}", KIND_TO_BADGE.get(label, "unknown"))} '
            for label, count in sorted(counts.items())
        )
        summary = f'<div class="badge-row">{count_badges}</div>'
    else:
        summary = empty_state(
            "No media lineages",
            "The library has no observed media yet.",
        )

    rows = []

    for item in entries:
        rows.append(
            [
                media_link(item["media"]["id"], item["media"]["file_name"]),
                badge(item["status_label"], item["status_badge"]),
                _validity_reason_cell(item["reason"]),
                ", ".join(item["incomplete_run_states"]) or "—",
                item["valid_run_id"] if item["valid_run_id"] else "—",
                item["historical_run_count"],
                link(f"/media/{item['media']['id']}", "view"),
            ]
        )

    content = f"""
<section class="card">
  <div class="card-head"><h2>Analysis status</h2></div>
  {summary}
</section>
<section class="card">
  <div class="card-head">
    <h2>Per-lineage status</h2>
    <input
      type="search"
      id="filter-input"
      class="filter-input"
      placeholder="Filter by name or path…"
      aria-label="Filter analysis status table">
  </div>
  {table(
      ["Media", "Status", "Reason", "Incomplete runs", "Valid run",
       "Historical runs", ""],
      rows,
      empty_title="No media",
      empty_message="No media lineages have been observed yet.",
  )}
</section>
"""

    return layout("Analysis", "analysis", content, refreshed_at=data.get("refreshed_at"))


KIND_TO_BADGE = {
    "Current": "current",
    "Missing": "missing",
    "Failed": "failed",
    "Abandoned": "abandoned",
    "Cancelled": "cancelled",
    "Running": "running",
    "Pending": "pending",
    "Stale": "stale",
    "Not analysed": "stale",
}


def render_scan(data):
    meta = data["meta"]

    active_scan = data.get("active_scan")

    meta_items = [
        ("Last scan recorded", esc(meta["last_scanned_at"])),
        ("Active lineages", esc(meta["active_lineage_count"])),
        ("Missing lineages", esc(meta["missing_lineage_count"])),
    ]

    progress_html = ""

    if active_scan:
        progress_html = f"""
  <div class="scan-progress" id="scan-progress"
       data-scan-id="{esc(active_scan.get("scan_id"))}"
       data-path="{esc(active_scan.get("path"))}"></div>
"""

    content = f"""
<section class="card">
  <div class="card-head"><h2>Run a scan</h2></div>
  <form class="scan-form" method="post" action="/scan" id="scan-form"
        data-autostart="{esc("1" if data.get("autostart") else "")}">
    <label for="scan-path">Library path to scan</label>
    <div class="scan-row">
      <input
        type="text"
        id="scan-path"
        name="path"
        class="path-input"
        placeholder="Path to your media library"
        required
        aria-label="Library path"
        value="{esc(data.get("initial_path") or "")}">
      <button type="button" class="btn small ghost" id="browse-toggle">Browse…</button>
      <button type="submit" class="btn">Scan now</button>
    </div>
    <div class="folder-browser" id="folder-browser" hidden>
      <div class="folder-browser-head">
        <span class="folder-current" id="folder-current">/</span>
        <button type="button" class="btn small ghost" id="folder-up">Up one level</button>
      </div>
      <ul class="folder-list" id="folder-list"></ul>
      <div class="folder-browser-foot">
        <span class="folder-error" id="folder-error"></span>
        <button type="button" class="btn small" id="folder-select">Use this folder</button>
        <button type="button" class="btn small ghost" id="folder-close">Close</button>
      </div>
    </div>
    <p class="muted">
      Scans run in the background. This page shows real progress as
      files are discovered and analysed; the estimated time is
      approximate. Large libraries take time.
    </p>
  </form>
  {progress_html}
</section>
<section class="card">
  <div class="card-head"><h2>Scan state</h2></div>
  {facts(meta_items)}
</section>
"""

    return layout("Scan", "scan", content, refreshed_at=data.get("refreshed_at"))


def render_analyse_report(data):
    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Targeted analysis</h2>
    <span class="badge current">Validity gate respected</span>
  </div>
  {facts([
      ("Lineage", esc(data["media_id"])),
      ("Files processed", esc(data["files_processed"])),
  ])}
  <p class="muted">
    {esc(data["message"])} Targeted analysis never forces a new run
    past a valid currentness result and never reconciles the
    filesystem existence lifecycle.
  </p>
  <p>
    <a class="btn small ghost" href="/media/{data["media_id"]}">Back to media detail</a>
    <a class="btn small" href="/analysis">Inspect analysis status</a>
  </p>
</section>
"""

    return layout("Media", "media", content, refreshed_at=data.get("refreshed_at"))


def render_opportunities(data):
    prioritised = data["prioritised"]
    sets = data["sets"]
    projection = data["projection"]

    if not prioritised:
        content = empty_state(
            "No current opportunities",
            "No up-to-date analysis produced an optimisation "
            "opportunity. Out-of-date or unanalysed media never "
            "appears here.",
        )
        return layout("Opportunities", "opportunities", content, refreshed_at=data.get("refreshed_at"))

    rows = [
        f"""
<tr>
  <td class="select-cell">
    <input type="checkbox" class="select-item" name="selected"
           value="{item["media_id"]}"
           aria-label="Select recommendation for {esc(item["file_name"])}">
  </td>
  <td>#{item["rank"]}</td>
  <td>{media_link(item["media_id"], item["file_name"])}
      {_change_summary_subline(item.get("change_summary"))}</td>
  <td>{_opportunity_badge(item["opportunity"])}</td>
  <td>{_priority_cell(item["priority_score"])}</td>
  <td>{_confidence_cell(item)}</td>
  <td>{_saving_cell(item)}</td>
  <td>{_risk_cell(item["risk"])}</td>
  <td class="actions-cell">{_preview_icon_link(item["media_id"], item["file_name"])}
      {link(f"/opportunities/{item['media_id']}", "details")}</td>
</tr>"""
        for item in prioritised
    ]

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Recommended optimisations</h2>
    <a class="btn small" href="/queue-export">Export queue manifest</a>
    <input
      type="search"
      id="filter-input"
      class="filter-input"
      placeholder="Filter by name…"
      aria-label="Filter recommendations table">
  </div>
  <p class="muted">
    NAMOA found these optimisation opportunities and ordered them
    by expected benefit and confidence.
  </p>
  <details class="disclosure disclosure-tight">
    <summary>How are these prioritised?</summary>
    <p class="muted">
      NAMOA weighs expected storage savings, confidence in the
      recommendation, and potential risk. Higher-value
      opportunities appear first.
    </p>
    <details class="disclosure">
      <summary>Technical details</summary>
      <p class="muted">
        Prioritised by the authoritative
        RecommendationPrioritisationService over the current-valid
        queue. Priority score = score×0.4 + calibrated
        confidence×0.2 + savings×0.3 − risk×0.1; the calibrated
        confidence is shown in parentheses. Ties break by media id.
      </p>
    </details>
  </details>
  <form method="post" action="/opportunities/accept-selected" id="selection-form">
    <div class="selection-bar">
      <label class="select-all-label">
        <input type="checkbox" id="select-all">
        Select all
      </label>
      <button type="button" class="btn small ghost" id="clear-selection">Clear selection</button>
      <span class="muted" id="selection-count"></span>
      <button type="submit" class="btn small">Review selected…</button>
    </div>
    <div class="table-wrap">
    <table class="data-table">
      <thead><tr>
        <th>Select</th><th>#</th><th>File</th><th>Optimisation</th>
        <th>Priority</th><th>Confidence</th>
        <th>Potential saving</th><th>Risk</th><th>Actions</th>
      </tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    </div>
  </form>
  <p class="muted">
    Reviewing selected recommendations leads to an explicit
    confirmation step; approval only queues work and never starts it.
  </p>
</section>
"""

    set_html = ""

    for recommendation_set in sets:
        set_title, set_description = opportunity_set_display(
            recommendation_set["name"],
            recommendation_set.get("description"),
        )

        if recommendation_set["count"] == 0:
            set_html += f"""
<section class="card">
  <div class="card-head"><h2>{esc(set_title)}</h2></div>
  <p class="muted">{esc(set_description)}</p>
  {empty_state(
      "No recommendations in this set",
      "No up-to-date recommendation matches this selection.",
  )}
</section>
"""
            continue

        set_rows = [
            [
                f'#{item["rank"]}',
                media_link(item["media_id"], item["file_name"]),
                _opportunity_badge(item["opportunity"]),
                _priority_cell(item["priority_score"]),
                _confidence_cell(item),
                _saving_cell(item),
                _risk_cell(item["risk"]),
                f'{_preview_icon_link(item["media_id"], item["file_name"])} '
                + link(
                    f"/opportunities/{item['media_id']}",
                    "details",
                ),
            ]
            for item in recommendation_set["recommendations"]
        ]

        set_html += f"""
<section class="card">
  <div class="card-head"><h2>{esc(set_title)}</h2></div>
  <p class="muted">{esc(set_description)}</p>
  <p class="muted">
    {recommendation_set["count"]} recommendation(s),
    {esc(format_bytes_human(recommendation_set.get("total_saved_bytes")))} projected saving.
  </p>
  {table(
      ["#", "File", "Optimisation", "Priority", "Confidence",
       "Potential saving", "Risk", "Actions"],
      set_rows,
  )}
</section>
"""

    projection_rows = [
        [
            _opportunity_badge(category["opportunity"]),
            category["count"],
            esc(format_bytes_human(category.get("total_saved_bytes"))),
        ]
        for category in projection["by_opportunity"]
    ]

    top_n_rows = [
        [
            entry["rank"],
            esc(format_bytes_human(entry.get("cumulative_saved_bytes"))),
        ]
        for entry in projection["top_n_projection"]
    ]

    projection_html = f"""
<section class="card">
  <div class="card-head"><h2>Total projected savings</h2></div>
  <p class="muted">
    {projection["total_opportunities"]} opportunities,
    <span class="saving-main">{esc(format_bytes_human(projection.get("total_saved_bytes")))}</span>
    total projected saving
    ({esc(projection["total_saving_percent_text"])} of those
    files' combined size).
  </p>
  <h3 class="section-title">By optimisation type</h3>
  {table(
      ["Optimisation", "Count", "Projected saving"],
      projection_rows,
      empty_title="No projection",
      empty_message="No current opportunities to project.",
  )}
  <h3 class="section-title">Combined saving for the top selections</h3>
  {table(
      ["Top N", "Combined projected saving"],
      top_n_rows,
      empty_title="No projection",
      empty_message="No current opportunities to project.",
  )}
</section>
"""

    content += set_html + projection_html

    return layout("Opportunities", "opportunities", content, refreshed_at=data.get("refreshed_at"))


def render_intelligence(data):
    statistics = data["statistics"]
    storage = data["storage"]
    health = data["health"]
    savings = data["savings"]
    confidence = data["confidence"]
    statuses = data["lineage_statuses"]

    health_badge = {
        "healthy": ("Healthy", "current"),
        "warning": ("Warning", "stale"),
        "poor": ("Poor", "failed"),
    }.get(health["status"], (health["status"], "unknown"))

    cards = "".join(
        [
            stat_card(
                "Active media",
                statistics["active_lineages"],
                hint="lineages present on disk",
            ),
            stat_card(
                "Missing media",
                statistics["missing_lineages"],
                hint="observed but absent",
            ),
            stat_card(
                "Analysed",
                statistics["analysed_lineages"],
                hint="valid current analysis",
            ),
            stat_card(
                "Unanalysed",
                statistics["unanalysed_lineages"],
                hint="require analysis",
            ),
            stat_card(
                "Stale analyses",
                statistics["stale_analyses"],
                hint="prior analysis no longer current",
            ),
            stat_card(
                "Changed media",
                statistics["changed_media"],
                hint="changed beyond last observation",
            ),
            stat_card(
                "Analysis coverage",
                statistics["coverage_percent"],
                hint="analysed / active",
            ),
            stat_card(
                "Health",
                badge(*health_badge),
                hint=f'score {esc(health["health_score_percent"])}',
            ),
        ]
    )

    health_indicators = "".join(
        f"<li>{esc(indicator)}</li>"
        for indicator in health["indicators"]
    )

    storage_facts = [
        ("Total library size", esc(storage["total_library_size"])),
        ("Analysed bytes", esc(storage["analysed_size"])),
        ("Unanalysed bytes", esc(storage["unanalysed_size"])),
        ("Missing bytes", esc(storage["missing_size"])),
        ("Opportunity bytes", esc(storage["opportunity_size"])),
        ("Opportunity saved", esc(storage["opportunity_saved_size"])),
        (
            "Opportunity saving %",
            esc(storage["opportunity_saved_percent_text"]),
        ),
        (
            "Library saving %",
            esc(storage["library_savings_percent_text"]),
        ),
    ]

    savings_rows = [
        [
            esc(bucket["label"]),
            bucket["count"],
            bucket["saved_size"],
        ]
        for bucket in savings["buckets"]
        if bucket["count"] > 0
    ]

    confidence_rows = [
        [
            esc(bucket["label"]),
            bucket["count"],
            bucket["saved_size"],
        ]
        for bucket in confidence["buckets"]
        if bucket["count"] > 0
    ]

    status_rows = [
        [
            media_link(entry["media_id"], entry["file_name"] or f"#{entry['media_id']}"),
            badge(entry["media_status"], "domain"),
            entry["validity_reason"],
            "Yes" if entry["is_analysed"] else "No",
            "Yes" if entry["is_stale"] else "No",
            "Yes" if entry["is_changed_media"] else "No",
            entry["historical_run_count"],
        ]
        for entry in statuses
    ]

    content = f"""
<section class="card">
  <div class="card-head"><h2>Library statistics</h2></div>
  <div class="stat-grid">{cards}</div>
</section>
<section class="card">
  <div class="card-head"><h2>Library health</h2></div>
  <p class="muted">
    Coverage {esc(health["coverage_percent"])} ({esc(health["coverage_status"])}),
    stale ratio {esc(health["stale_percent"])} ({esc(health["stale_status"])}),
    opportunity ratio {esc(health["opportunity_percent"])} ({esc(health["opportunity_status"])}).
  </p>
  <ul>{health_indicators or "<li>No concerns detected</li>"}</ul>
</section>
<section class="card">
  <div class="card-head"><h2>Storage consumption</h2></div>
  {facts(storage_facts)}
</section>
<section class="card">
  <div class="card-head"><h2>Savings distribution</h2></div>
  <p class="muted">
    {savings["total_opportunities"]} current opportunities,
    {esc(savings["total_saved_size"])} projected saving.
  </p>
  {table(
      ["Savings %", "Count", "Saved"],
      savings_rows,
      empty_title="No opportunities",
      empty_message="No current opportunities to distribute.",
  )}
</section>
<section class="card">
  <div class="card-head"><h2>Confidence distribution</h2></div>
  <p class="muted">
    {confidence["total_opportunities"]} current opportunities,
    {esc(confidence["total_saved_size"])} projected saving.
  </p>
  {table(
      ["Confidence", "Count", "Saved"],
      confidence_rows,
      empty_title="No opportunities",
      empty_message="No current opportunities to distribute.",
  )}
</section>
<section class="card">
  <div class="card-head"><h2>Per-lineage classification</h2></div>
  {table(
      ["Media", "Existence", "Validity reason", "Analysed", "Stale",
       "Changed", "Historical runs"],
      status_rows,
      empty_title="No lineages",
      empty_message="The library has no observed media yet.",
  )}
</section>
"""

    return layout("Intelligence", "intelligence", content, refreshed_at=data.get("refreshed_at"))


def render_opportunity_detail(data):
    entry = data["entry"]
    candidate = data["candidate"]
    prioritised = data.get("prioritised")
    record = data.get("record")
    explanation = data["explanation"]
    media = entry["media"]

    if candidate is None:
        content = f"""
<section class="card">
  <div class="card-head"><h2>{esc(media['file_name'])}</h2></div>
  {empty_state(
      "No current opportunity",
      "This file currently has no opportunity in the current "
      "recommendations. Its analysis may be out of date, missing, "
      "or simply not opportunity-producing.",
  )}
  <p><a class="btn small ghost" href="/opportunities">Back to recommendations</a></p>
</section>
"""
        return layout("Opportunity", "opportunities", content, refreshed_at=data.get("refreshed_at"))

    # Concise top card: identity, current media state, the
    # recommendation itself, and status where supported.
    fact_items = [
        ("Media", media_link(media["id"], media["file_name"])),
        ("Path", esc(media["file_path"])),
        ("Current media state", badge(entry["status_label"], entry["status_badge"])),
        ("Opportunity", _opportunity_badge(candidate["opportunity"])
         + f' <span class="muted">{esc(candidate["opportunity"])}</span>'),
        ("Score", f'{candidate["opportunity_score"]:.2f}'),
        ("Confidence", candidate["confidence_percent"]),
        ("Estimated savings", candidate["saving_percent"]),
        ("File size", candidate["file_size"]),
        ("Estimated saved", candidate["estimated_saved_size"]),
        ("Risk", esc(candidate["risk"])),
    ]

    if prioritised is not None:
        fact_items.append(
            ("Priority rank", f'#{prioritised["rank"]} of the current queue')
        )
        fact_items.append(
            ("Priority score", f'{prioritised["priority_score"]:.4f}')
        )

    if entry["valid_run_id"] is not None:
        fact_items.append(
            (
                "Analysis run",
                run_link(entry["valid_run_id"], f"Run #{entry['valid_run_id']}"),
            )
        )

    if record is not None:
        record_url = f"/recommendations/{record['id']}"
        fact_items.append(
            (
                "Recommendation record",
                link(record_url, f"#{record['id']} {record['state_label']}"),
            )
        )
        if record["execution_job_id"] is not None:
            fact_items.append(
                (
                    "Execution",
                    link(
                        f"/executions/{record['execution_job_id']}",
                        f"Job #{record['execution_job_id']}",
                    ),
                )
            )

    rationale_lines = []

    if prioritised is not None:
        rationale_lines.extend(prioritised["rationale"])

    if explanation is not None:
        rationale_lines.append(explanation["summary"])

    evidence_html = ""

    expert_html = ""

    if explanation is not None:
        evidence_html = _detail_section(
            "Evidence",
            "".join(
                f"<li>{esc(line)}</li>"
                for line in explanation["evidence_summary"]
            ) or "<li>No evidence recorded</li>",
        )

        expert_lines = [
            *explanation["expert_contributions"],
            *explanation["decision_summary"],
        ]

        expert_html = _detail_section(
            "Experts and decision rules",
            "".join(
                f"<li>{esc(line)}</li>"
                for line in expert_lines
            ) or "<li>No expert reasoning recorded</li>",
        )

    intelligence_html = _detail_section(
        "Intelligence version",
        (
            "<li>Producing intelligence identity: "
            f"<code>{esc(_short_digest(record['intelligence_identity']))}</code></li>"
            if record is not None and record["intelligence_identity"]
            else "<li>Not recorded for this recommendation</li>"
        )
        + (
            "<li>Full provenance: "
            + run_link(
                entry["valid_run_id"],
                f"Run #{entry['valid_run_id']}",
            )
            + "</li>"
            if entry["valid_run_id"] is not None
            else ""
        ),
    )

    history_parts = [
        f"<li>{entry['historical_run_count']} historical analysis "
        "run(s); see the media page for observations and runs.</li>",
    ]

    if record is not None:
        history_parts.append(
            "<li>Durable recommendation record with lifecycle "
            "events: "
            + link(
                f"/recommendations/{record['id']}",
                f"Recommendation #{record['id']}",
            )
            + "</li>"
        )

    history_html = _detail_section(
        "Historical context",
        "".join(f"<li>{part}</li>" for part in history_parts),
    )

    advanced_html = _advanced_options_block(
        media["id"],
        data.get("operations") or [],
    )

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Recommended change</h2>
    <a class="btn small ghost" href="/opportunities">Back to recommendations</a>
  </div>
  <p class="muted">For <strong>{esc(media["file_name"])}</strong></p>
  {_change_summary_block(candidate.get("change_summary"))}
  <div class="rec-meta">
    <span class="rec-meta-item">Confidence {esc(candidate["confidence_percent"])}</span>
    <span class="rec-meta-item">Risk {esc(candidate["risk"])}</span>
  </div>
  <div class="rec-actions">
    <button type="button" class="btn js-approve-single"
            data-media-id="{media["id"]}"
            data-name="{esc(media["file_name"])}">Approve Optimisation</button>
    <a class="btn btn-preview" href="/preview/new?origin=analysis&amp;ref={media["id"]}">Preview Optimisation</a>
{_job_visibility_badge(data.get("active_job"))}
  </div>
  <details class="disclosure">
    <summary>Why NAMOA recommends this</summary>
    <ul>{''.join(
        f'<li>{esc(line)}</li>' for line in rationale_lines
    ) or '<li>No rationale recorded</li>'}</ul>
  </details>
</section>
{advanced_html}
<section class="card">
  <div class="card-head"><h2>Technical details</h2></div>
  <details class="disclosure">
    <summary>Analysis and recommendation details</summary>
    {facts(fact_items)}
  </details>
  <div class="disclosure-stack">
    {evidence_html}
    {expert_html}
    {intelligence_html}
    {history_html}
  </div>
</section>
"""

    return layout("Opportunity", "opportunities", content, refreshed_at=data.get("refreshed_at"))


def _advanced_options_block(media_id, operations):
    """
    Advanced controls: the GUI renders controls ONLY for executable
    operations, and ONLY from the authoritative operation registry
    schemas. The application layer validates every submitted value;
    no free-form FFmpeg input exists.
    """

    if not operations:
        return ""

    operation_forms = []

    for operation in operations:

        fields = []

        for param in operation.get("parameters") or []:

            field_html = ""

            if param.get("type") == "enum":

                options = "".join(
                    f'<option value="{esc(option)}"'
                    f'{' selected' if option == param.get("default") else ""}>'
                    f'{esc(option)}</option>'
                    for option in (param.get("allowed_values") or [])
                )

                field_html = (
                    f'<label>{esc(param["name"])} '
                    f'<select name="param_{esc(param["name"])}" '
                    f'class="path-input">'
                    f'{options}</select></label>'
                )

            elif param.get("type") == "bool":

                field_html = (
                    f'<label class="check-label">'
                    f'<input type="checkbox" '
                    f'name="param_{esc(param["name"])}" '
                    f'value="true" '
                    f'{"checked" if param.get("default") else ""}/> '
                    f'{esc(param["name"])}</label>'
                )

            else:

                field_html = (
                    f'<label>{esc(param["name"])} '
                    f'<input class="path-input" type="text" '
                    f'name="param_{esc(param["name"])}" '
                    f'value="{esc(param.get("default") or "")}"/>'
                    f'</label>'
                )

            fields.append(f"<div>{field_html}</div>")

        delete_field = (
            '<label class="check-label">'
            '<input type="checkbox" name="delete_original" '
            'value="true"/> Delete original after successful '
            'optimisation (separate lifecycle action; never '
            'automatic)</label>'
        )

        operation_forms.append(f"""
<details class="disclosure">
  <summary>Advanced: {esc(operation['operation'])}</summary>
  <p class="muted">
    {esc(operation['description'])} Values are validated against the
    closed operation registry before approval.
  </p>
  <form method="post" action="/opportunities/{media_id}/advanced-approve"
        class="selection-bar advanced-form">
    <input type="hidden" name="operation"
           value="{esc(operation['operation'])}"/>
    {''.join(fields)}
    <div>{delete_field}</div>
    <button type="submit" class="btn small">Approve with these settings</button>
  </form>
</details>
""")

    return f"""
<section class="card">
  <div class="card-head"><h2>Advanced options</h2></div>
  <p class="muted">
    Per-file controlled optimisation choices. Only executable
    operations are shown; every submitted value is validated against
    the operation registry. "Advanced" choices are recorded as your
    requested transformation, distinct from the recommendation.
  </p>
  {''.join(operation_forms)}
</section>
"""


def _change_summary_block(change_summary, metrics_html=""):
    """
    Phase 1 recommended-change block. Presents only what the
    assessment actually carries; compatibility-only changes are
    labelled as such and never present a savings figure; savings are
    always labelled as estimates, never as measured results.

    The optional metrics_html is rendered inside the same bordered
    box beside the text on dashboard cards, so the quadrant shares
    the information box geometry. Detail pages omit it and render
    byte-identical output to before.
    """

    if not change_summary or not change_summary.get("available"):

        return (
            '<div class="change-summary">'
            '<p class="muted">Transformation detail is not '
            "recorded for this recommendation.</p>"
            "</div>"
        )

    lines = "".join(
        (
            '<li><span class="change-domain">'
            + esc(line["domain"])
            + "</span> "
            + '<span class="change-value">'
            + esc(line.get("current") or "not recorded")
            + " → "
            + esc(line.get("target") or "not recorded")
            + "</span></li>"
        )
        for line in change_summary.get("lines", [])
    )

    one_liner = change_summary.get("one_liner")

    one_liner_html = (
        f'<p class="change-one-liner">{esc(one_liner)}</p>'
        if one_liner
        else ""
    )

    savings = change_summary.get("savings")

    if change_summary.get("compatibility_only"):

        outcome_html = (
            '<p class="change-outcome change-outcome-compat">'
            "Compatibility improvement · no storage saving"
            "</p>"
        )

    elif savings:

        # Human-readable decimal estimate, consistent with the
        # Expected Saving metric. Same underlying byte value;
        # presentation only.
        human_size = format_bytes_human(
            savings.get("estimated_saved_bytes")
        )

        outcome_html = (
            '<p class="change-outcome">'
            "Estimated saving: "
            + esc(human_size)
            + " "
            + (
                f'<span class="muted">({esc(savings.get("saving_percent") or "not recorded")})</span>'
                if savings.get("saving_percent")
                else ""
            )
            + (
                '<span class="muted"> · '
                + esc(savings.get("note") or "")
                + "</span>"
                if savings.get("note")
                else ""
            )
            + "</p>"
        )

    else:

        outcome_html = (
            '<p class="change-outcome muted">'
            "No expected storage change recorded"
            "</p>"
        )

    inner = (
        one_liner_html
        + (
            f'<ul class="change-summary-lines">{lines}</ul>'
            if lines
            else ""
        )
        + outcome_html
    )

    if metrics_html:
        return (
            '<div class="change-summary with-metrics">'
            '<div class="change-text">'
            + inner
            + "</div>"
            + metrics_html
            + "</div>"
        )

    return (
        '<div class="change-summary">'
        + inner
        + "</div>"
    )


def _change_summary_subline(change_summary):
    """
    A compact single-line change hint for table media cells.
    """

    if not change_summary or not change_summary.get("available"):
        return ""

    lines = change_summary.get("lines") or []

    if not lines:
        return ""

    texts = []

    for line in lines[:2]:
        current = line.get("current") or "not recorded"
        target = line.get("target") or "not recorded"
        texts.append(f"{line['domain']}: {current} → {target}")

    return f'<div class="cell-sub">{esc(" · ".join(texts))}</div>'


def _detail_section(title, inner_html):
    """
    One progressive-disclosure section: collapsed by default so the
    normal presentation stays concise; expansion requires no data
    fetching and performs no actions.
    """

    return f"""
<details class="disclosure">
  <summary>{esc(title)}</summary>
  <ul>{inner_html}</ul>
</details>
"""


def _short_digest(digest):
    """Short display form of a sha256 digest; None stays None."""

    if not digest:

        return digest

    text = str(digest)

    return text[:16] + "…" if len(text) > 16 else text


def render_runs(data):
    runs = data["runs"]

    status_filter = data.get("status_filter")

    media_filter = data.get("media_id_filter")

    if not runs and not status_filter and not media_filter:
        content = empty_state(
            "No analysis runs",
            "The pipeline has not persisted any analysis runs yet.",
        )
        return layout("Runs", "runs", content, refreshed_at=data.get("refreshed_at"))

    rows = [
        [
            run_link(run["id"], f"Run #{run['id']}"),
            media_link(run["media_id"], run["media_name"] or "—"),
            badge(run["status_label"], run["status_badge"]),
            run["started_at"],
            run["completed_at"],
            esc(run["error_message"] or "—"),
            link(f"/runs/{run['id']}/compare", "compare"),
        ]
        for run in runs
    ]

    status_options = ["", "pending", "running", "completed",
                      "failed", "cancelled", "abandoned"]

    status_select = "".join(
        f'<option value="{value}"'
        f'{" selected" if value == (status_filter or "") else ""}>'
        f'{value or "all statuses"}</option>'
        for value in status_options
    )

    filter_note = ""

    if status_filter or media_filter:

        parts = []

        if status_filter:

            parts.append(f"status {esc(status_filter)}")

        if media_filter:

            parts.append(f"media {media_filter}")

        filter_note = (
            '<p class="muted">Filtered to '
            + " and ".join(parts)
            + ' · <a href="/runs">clear filters</a></p>'
        )

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Analysis history</h2>
    <input
      type="search"
      id="filter-input"
      class="filter-input"
      placeholder="Filter by media name…"
      aria-label="Filter runs table">
  </div>
  <p class="muted">
    Runs are listed as persisted by the pipeline. State is displayed
    as recorded; currentness is decided by the validity authority.
  </p>
  <form method="get" action="/runs" class="selection-bar">
    <label for="status">Run status</label>
    <select id="status" name="status" class="path-input">
      {status_select}
    </select>
    <button type="submit" class="btn small">Apply filter</button>
    <a class="btn small ghost" href="/runs">Clear</a>
  </form>
  {filter_note}
  {table(
      ["Run", "Media", "Status", "Started", "Completed", "Error", ""],
      rows,
      empty_title="No matching runs",
      empty_message=(
          "No persisted run matches the current filters. Filters "
          "never create rows; clear them to see the full history."
      ),
  )}
</section>
"""

    return layout("Runs", "runs", content, refreshed_at=data.get("refreshed_at"))


def render_run_detail(data):
    run = data["run"]
    provenance = data["provenance"]
    explanation = data["explanation"]
    media = data["media"]

    run_badge = badge(run["status_label"], run["status_badge"])

    fact_items = [
        ("Run", f"#{run['id']}"),
        ("Status", run_badge),
        ("Media", media_link(run["media_id"], media["file_name"] if media else "—")),
        ("Observation", esc(run["file_observation_id"])),
        ("Configuration", esc(run["configuration_snapshot_id"])),
        ("Started", esc(run["started_at"])),
        ("Completed", esc(run["completed_at"])),
        ("Error", esc(run["error_message"])),
    ]

    evidence_rows = [
        [
            badge(item["domain"], "domain"),
            esc(item["value"]),
            item["confidence_percent"],
            esc(item["source"]),
            esc(item["matched_text"]),
        ]
        for item in provenance["evidence"]
    ]

    expert_rows = [
        [
            esc(item["expert_name"]),
            item["confidence_percent"],
            esc(item["notes"]),
            ", ".join(
                f"{domain}: {analysis['selected_value']}"
                for domain, analysis in item["domains"].items()
            )
            if item["domains"]
            else "—",
        ]
        for item in provenance["expert_results"]
    ]

    signal_rows = [
        [
            esc(item["rule"]),
            esc(item["direction"]),
            f'{item["opportunity_score"]:.2f}',
            item["confidence_percent"],
            esc(item["notes"]),
        ]
        for item in provenance["decision_signals"]
    ]

    knowledge_lines = "".join(
        f"<li>Knowledge set {esc(item['knowledge_set_id'])}</li>"
        for item in provenance["knowledge_usage"]
    )

    assessment = provenance["opportunity_assessment"]

    if assessment is not None:
        assessment_html = facts(
            [
                ("Opportunity", badge(assessment["opportunity"], "opportunity")),
                ("Score", f'{assessment["opportunity_score"]:.2f}'),
                ("Confidence", assessment["confidence_percent"]),
                ("Estimated savings", assessment["saving_percent"]),
                ("Risk", esc(assessment["risk"])),
                ("Contributing rules", esc(", ".join(assessment["contributing_rules"]))),
            ]
        )

        reasoning_lines = "".join(
            f"<li>{esc(line)}</li>"
            for line in assessment["reasoning"]
        )
        assessment_html += (
            f'<h3 class="section-title">Reasoning</h3><ul>{reasoning_lines or "<li>None</li>"}</ul>'
        )
    else:
        assessment_html = empty_state(
            "No opportunity assessment",
            "This run produced no assessment.",
        )

    explanation_summary = "".join(
        f"<li>{esc(line)}</li>"
        for line in explanation["expert_contributions"]
    )

    compare_html = (
        f'<a class="btn small" href="/runs/{run["id"]}/compare">Compare</a>'
    )

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Run #{run['id']}</h2>
    <div class="card-actions">{compare_html}</div>
  </div>
  {facts(fact_items)}
</section>
<section class="card">
  <div class="card-head"><h2>Explanation</h2></div>
  <p class="explanation-summary">{esc(explanation["summary"])}</p>
  <p class="muted">{esc(explanation["confidence_summary"])}</p>
  <h3 class="section-title">Expert contributions</h3>
  <ul>{explanation_summary or "<li>None recorded</li>"}</ul>
</section>
<section class="card">
  <div class="card-head"><h2>Evidence</h2></div>
  {table(
      ["Domain", "Value", "Confidence", "Source", "Matched"],
      evidence_rows,
      empty_title="No evidence",
      empty_message="No classification evidence was recorded for this run.",
  )}
</section>
<section class="card">
  <div class="card-head"><h2>Expert results</h2></div>
  {table(
      ["Expert", "Confidence", "Notes", "Domains"],
      expert_rows,
      empty_title="No expert results",
      empty_message="No expert results were recorded for this run.",
  )}
</section>
<section class="card">
  <div class="card-head"><h2>Decision signals</h2></div>
  {table(
      ["Rule", "Direction", "Score", "Confidence", "Notes"],
      signal_rows,
      empty_title="No decision signals",
      empty_message="No decision signals were recorded for this run.",
  )}
</section>
<section class="card">
  <div class="card-head"><h2>Opportunity assessment</h2></div>
  {assessment_html}
</section>
<section class="card">
  <div class="card-head"><h2>Knowledge usage</h2></div>
  <ul>{knowledge_lines or "<li>No knowledge sets consulted</li>"}</ul>
</section>
"""

    return layout("Run", "runs", content, refreshed_at=data.get("refreshed_at"))


def render_compare_select(data):
    run_a_id = data["run_a_id"]
    others = data["others"]

    if not others:
        body = empty_state(
            "Nothing to compare",
            "No other analysis runs exist yet. Comparison needs at "
            "least two runs.",
        )
    else:
        options = "".join(
            f'<option value="{item["id"]}">'
            f'Run #{item["id"]} · {esc(item["media_name"] or "—")} '
            f'· {esc(item["status_label"])}</option>'
            for item in others
        )

        body = f"""
<form method="get" action="/runs/{run_a_id}/compare">
  <label class="compare-label" for="with">Compare Run #{run_a_id} with</label>
  <div class="scan-row">
    <select id="with" name="with" class="path-input">
      {options}
    </select>
    <button type="submit" class="btn">Compare</button>
  </div>
</form>
"""

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Compare Run #{run_a_id}</h2>
    <a class="btn small ghost" href="/runs/{run_a_id}">Back to Run #{run_a_id}</a>
  </div>
  {body}
</section>
"""

    return layout("Compare", "runs", content)


def render_compare(data):
    comparison = data["comparison"]

    run_a = comparison["run_a"]
    run_b = comparison["run_b"]

    header = facts(
        [
            (
                "Run A",
                run_link(run_a["id"], f"Run #{run_a['id']}"),
            ),
            ("Run A status", badge(run_a["status_label"], run_a["status_badge"])),
            ("Run A started", esc(run_a["started_at"])),
            (
                "Run B",
                run_link(run_b["id"], f"Run #{run_b['id']}"),
            ),
            ("Run B status", badge(run_b["status_label"], run_b["status_badge"])),
            ("Run B started", esc(run_b["started_at"])),
            ("Same observation", "Yes" if comparison["same_observation"] else "No"),
        ]
    )

    differences = comparison["differences"]

    # Sprint 12: an explicit intelligence-identity verdict derived
    # only from the comparison data the provenance authority
    # returned; "unrecorded" is never treated as a value.
    identity_entries = [
        item
        for item in differences
        if item["category"] == "intelligence_identity"
    ]

    if identity_entries:

        identity_item = identity_entries[0]

        before, after = (
            identity_item["before"],
            identity_item["after"],
        )

        if before == after == "unrecorded":

            identity_verdict = (
                "Not comparable: intelligence identity was not "
                "recorded for either run"
            )

        elif "unrecorded" in (before, after):

            identity_verdict = (
                "Not comparable: intelligence identity was not "
                "recorded for one of the runs"
            )

        elif before == after:

            identity_verdict = (
                "Identical recorded intelligence identity: both "
                "runs were produced under the same recorded "
                "intelligence"
            )

        else:

            identity_verdict = (
                "Different recorded intelligence identities: the "
                "two runs were produced under different recorded "
                "intelligence"
            )

        identity_html = f"""
<p class="muted"><strong>{esc(identity_verdict)}</strong>
  ({esc(str(before)[:12])}... vs {esc(str(after)[:12])}...)
</p>
"""

    else:

        # No identity difference was reported. That happens when
        # the recorded identities are equal or when neither run
        # recorded one; derive the verdict from the runs' own
        # serialised fields so the page always answers honestly.
        left_digest = run_a.get("intelligence_identity")

        right_digest = run_b.get("intelligence_identity")

        if left_digest and right_digest:

            identity_verdict = (
                "Identical recorded intelligence identity: both "
                "runs were produced under the same recorded "
                "intelligence"
            )

            digest_note = (
                f'(<code>{esc(str(left_digest)[:12])}...</code>)'
            )

        elif not left_digest and not right_digest:

            identity_verdict = (
                "Not comparable: intelligence identity was not "
                "recorded for either run"
            )

            digest_note = ""

        else:

            identity_verdict = (
                "Not comparable: intelligence identity was not "
                "recorded for one of the runs"
            )

            digest_note = ""

        identity_html = (
            f'<p class="muted"><strong>'
            f"{esc(identity_verdict)}</strong> {digest_note}</p>"
        )

    if not differences:
        body = empty_state(
            "No differences",
            "The two runs are identical across the compared fields.",
        )
    else:
        rows = [
            [
                badge(item["category"], "domain"),
                esc(item["key"]),
                esc(item["before"]),
                esc(item["after"]),
                esc(item["summary"]),
            ]
            for item in differences
        ]

        body = table(
            ["Category", "Field", "Before", "After", "Summary"],
            rows,
        )

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Comparing Run #{run_a['id']} and Run #{run_b['id']}</h2>
    <a class="btn small ghost" href="/runs/{run_a['id']}">Back to Run #{run_a['id']}</a>
  </div>
  {header}
</section>
<section class="card">
  <div class="card-head"><h2>Differences</h2></div>
  {identity_html}
  {body}
</section>
"""

    return layout("Compare", "runs", content, refreshed_at=data.get("refreshed_at"))


def render_accept_confirmation(data):
    """
    Confirmation step between selection and approval. Shows exactly
    what the user is about to approve before any authorisation
    happens; the apply step is a separate explicit action.
    """

    items = data["items"]
    approvable_ids = data["approvable_ids"]

    rows = []

    for item in items:
        if item["approvable"]:
            rows.append(
                f"""
<tr>
  <td>{media_link(item["media_id"], item["file_name"])}
      {_change_summary_subline(item.get("change_summary"))}</td>
  <td>{_opportunity_badge(item["opportunity"])}</td>
  <td>{item["confidence_percent"]}</td>
  <td>{_saving_cell(item)}</td>
  <td>{_risk_cell(item["risk"])}</td>
</tr>"""
            )
        else:
            reason = item["reason"] or ""

            # The backend reason string is also the API contract
            # (pinned by service tests), so it is translated here
            # at render time only.
            if reason.startswith("no current-valid recommendation"):
                reason = (
                    "No current recommendation. The analysis may "
                    "be out of date or the recommendation was "
                    "already handled."
                )

            rows.append(
                f"""
<tr>
  <td>File {item["media_id"]}</td>
  <td colspan="4" class="muted">{esc(reason)}</td>
</tr>"""
            )

    approvable_count = len(approvable_ids)

    if approvable_count == 1:
        lead = "You are about to approve 1 optimisation."
    elif approvable_count > 1:
        lead = (
            f"You are about to approve {approvable_count} "
            f"optimisations."
        )
    else:
        lead = "Nothing in this selection can currently be approved."

    if approvable_ids:
        confirm_form = f"""
<form method="post" action="/opportunities/confirm-acceptance">
  {''.join(
      f'<input type="hidden" name="selected" value="{media_id}">'
      for media_id in approvable_ids
  )}
  <p class="muted">
    Approving queues each optimisation. Nothing runs until you
    start the queue.
  </p>
  <p class="muted">
    No files change now. Verified replacement and the
    original-file choice happen later, and only with your say.
  </p>
  <button class="btn" type="submit">Confirm approval</button>
  <a class="btn small ghost" href="/opportunities">Cancel</a>
</form>
<details class="disclosure">
  <summary>Technical details</summary>
  <p class="muted">
    Facts below reflect the current recommendations at
    confirmation time. Each approved file is recorded with its
    analysis run
    ({", ".join(
        f'Run #{item["analysis_run_id"]}'
        for item in items
        if item["approvable"] and item.get("analysis_run_id")
    ) or "no recorded run"})
    before any queue job is created.
  </p>
</details>
"""
    else:
        confirm_form = f"""
<p class="muted">
  None of the selected recommendations can currently be approved.
  Nothing was changed.
</p>
<p><a class="btn small ghost" href="/opportunities">Back to recommendations</a></p>
"""

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Selected recommendations</h2>
    <span class="badge stale">Confirmation required</span>
  </div>
  <p>{esc(lead)}</p>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr>
      <th>File</th><th>Optimisation</th><th>Confidence</th>
      <th>Potential saving</th><th>Risk</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  </div>
  {confirm_form}
</section>
"""

    return layout("Confirm approval", "opportunities", content, refreshed_at=data.get("refreshed_at"))


def render_acceptance_report(data):
    approved = data["approved"]
    refused = data["refused"]

    approved_rows = [
        f"""
<tr>
  <td>{media_link(entry["media_id"], f'media {entry["media_id"]}')}</td>
  <td>
    {link(f"/executions/{entry['job']['id']}", f"Job #{entry['job']['id']}")}
    {badge(entry["job"]["state_label"], entry["job"]["state_badge"])
        if entry.get("job") else ""}
  </td>
</tr>"""
        for entry in approved
    ]

    refused_rows = []

    for entry in refused:
        refused_rows.append(
            f"""
<tr>
  <td>media {entry["media_id"]}</td>
  <td class="muted">{esc(entry["reason"])}</td>
</tr>"""
        )

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Approved selections</h2>
    <span class="badge current">{len(approved)} queued</span>
  </div>
  {f'<div class="table-wrap"><table class="data-table"><thead><tr><th>Media</th><th>Execution job</th></tr></thead><tbody>{"".join(approved_rows)}</tbody></table></div>'
      if approved_rows else empty_state(
          "Nothing was approved",
          "No selected recommendation could be approved.",
      )}
  <p class="muted">
    Approved jobs are visible in the optimisation queue. Each job
    must be planned and started explicitly; policy validation,
    verification and provenance recording happen inside the
    execution authority.
  </p>
  <p>
    <a class="btn small" href="/executions">Open the optimisation queue</a>
    <a class="btn small ghost" href="/opportunities">Back to recommendations</a>
  </p>
</section>
"""

    if refused_rows:
        content += f"""
<section class="card">
  <div class="card-head"><h2>Not approved</h2></div>
  <p class="muted">
    These selections were refused by the approval boundary; nothing
    was queued for them.
  </p>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr><th>Selection</th><th>Reason</th></tr></thead>
    <tbody>{''.join(refused_rows)}</tbody>
  </table>
  </div>
</section>
"""

    return layout("Approval recorded", "opportunities", content, refreshed_at=data.get("refreshed_at"))


def render_rejection_report(data):
    """
    Result page for confirmed dashboard rejections (single and
    bulk). Mirrors the acceptance report structure: one section
    per outcome, human wording only, no proposition codes or
    exception text. Rejected items were refused atomically per
    candidate through the existing standing-decision semantics;
    unactionable items produced no records; failed items changed
    nothing for that file.
    """

    rejected = data.get("rejected") or []
    unactionable = data.get("unactionable") or []
    failed = data.get("failed") or []

    if len(rejected) == 1:
        lead = "Rejected 1 optimisation."
    elif rejected:
        lead = f"Rejected {len(rejected)} optimisations."
    else:
        lead = "Nothing was rejected."

    rejected_rows = [
        f"""
<tr>
  <td>{media_link(entry["media_id"], entry["file_name"])}</td>
  <td class="muted">Removed from active recommendations.
  The decision is kept in history.</td>
</tr>"""
        for entry in rejected
    ]

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Rejection recorded</h2>
    <span class="badge current">{len(rejected)} rejected</span>
  </div>
  <p>{esc(lead)}</p>
  {f'<div class="table-wrap"><table class="data-table"><thead><tr><th>File</th><th>Result</th></tr></thead><tbody>{"".join(rejected_rows)}</tbody></table></div>'
      if rejected_rows else empty_state(
          "Nothing rejected",
          "No selected recommendation was rejected.",
      )}
  <p>
    <a class="btn small ghost" href="/">Go to dashboard</a>
    <a class="btn small ghost" href="/opportunities">Back to recommendations</a>
  </p>
</section>
"""

    if unactionable:
        unactionable_rows = [
            f"""
<tr>
  <td>{media_link(entry["media_id"], entry["file_name"])}</td>
  <td class="muted">{esc(entry.get("reason") or "Already handled.")}</td>
</tr>"""
            for entry in unactionable
        ]

        content += f"""
<section class="card">
  <div class="card-head"><h2>Already handled</h2></div>
  <p class="muted">
    These selections had nothing currently active; no refusal
    was recorded for them.
  </p>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr><th>File</th><th>Reason</th></tr></thead>
    <tbody>{''.join(unactionable_rows)}</tbody>
  </table>
  </div>
</section>
"""

    if failed:
        failed_rows = [
            f"""
<tr>
  <td>{media_link(entry["media_id"], entry["file_name"])}</td>
  <td class="muted">Could not be rejected; nothing was changed
  for this file.</td>
</tr>"""
            for entry in failed
        ]

        content += f"""
<section class="card">
  <div class="card-head"><h2>Not rejected</h2></div>
  <p class="muted">
    These selections could not be processed. Nothing was
    changed for them; the remaining selections above were
    still processed.
  </p>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr><th>File</th><th>Result</th></tr></thead>
    <tbody>{''.join(failed_rows)}</tbody>
  </table>
  </div>
</section>
"""

    return layout("Rejection recorded", "opportunities", content, refreshed_at=data.get("refreshed_at"))


def render_recommendation_detail(data):
    record = data["record"]
    events = data["events"]
    lineage = data.get("lineage")
    job = data.get("execution")

    fact_items = [
        (
            "Recommendation",
            badge(record["state_label"], record["state_badge"]),
        ),
        ("Media", media_link(record["media_id"], f'media {record["media_id"]}')),
        ("Produced by run", run_link(record["analysis_run_id"], f"Run #{record['analysis_run_id']}")),
        ("Observation", esc(record["file_observation_id"])),
        ("Opportunity", badge(record["opportunity"], "opportunity")),
        ("Score", f'{record["opportunity_score"]:.2f}'),
        ("Confidence", record["confidence_percent"]),
        ("Estimated savings", record["saving_percent"]),
        ("Estimated saved", record["estimated_saved_size"]),
        ("Risk", esc(record["risk"])),
        ("Created", esc(record["created_at"])),
        ("Last transition", esc(record["updated_at"])),
    ]

    if lineage is not None:
        fact_items.append(
            (
                "Current media state",
                badge(lineage["status_label"], lineage["status_badge"])
                + f' <span class="muted">{esc(lineage["reason"])}</span>',
            )
        )
        fact_items.append(
            ("Analysis required now", "Yes" if lineage["analysis_required"] else "No")
        )

    if record["intelligence_identity"]:
        fact_items.append(
            (
                "Intelligence identity",
                f'<code>{esc(_short_digest(record["intelligence_identity"]))}</code>',
            )
        )

    if job is not None:
        fact_items.append(
            (
                "Execution",
                link(
                    f"/executions/{job['id']}",
                    f"Job #{job['id']}",
                )
                + " "
                + badge(job["state_label"], job["state_badge"]),
            )
        )

    event_rows = [
        [
            esc(event["event_type"]),
            badge(event["new_state_label"], event["new_state_badge"]),
            esc(event["actor"]),
            link(
                f"/executions/{event['execution_job_id']}",
                f"Job #{event['execution_job_id']}",
            )
            if event["execution_job_id"]
            else "-",
            esc(event["detail"] or ""),
            event["created_at"],
        ]
        for event in events
    ]

    priority_items = []

    if record["priority_score"] is not None:
        priority_items.append(("Priority at acceptance", f'{record["priority_score"]:.4f}'))

    if record["rank_at_presentation"] is not None:
        priority_items.append(("Rank at acceptance", f'#{record["rank_at_presentation"]}'))

    for key, value in (record["components"] or {}).items():
        priority_items.append((key.replace("_", " "), esc(value)))

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Recommendation #{record['id']}</h2>
    <a class="btn small" href="/media/{record["media_id"]}">Media detail</a>
  </div>
  <p class="muted">
    This is the durable recommendation produced by its analysis run.
    It is historical evidence: newer analyses never rewrite it.
  </p>
  {facts(fact_items)}
</section>
<section class="card">
  <div class="card-head"><h2>Rationale as produced</h2></div>
  <ul>
    {''.join(f"<li>{esc(line)}</li>" for line in record["rationale"])
        or "<li>No rationale recorded</li>"}
  </ul>
  <h3 class="section-title">Contributing rules</h3>
  <p>{esc(", ".join(record["contributing_rules"])) or "None recorded"}</p>
  {facts(priority_items) if priority_items else ""}
</section>
<section class="card">
  <div class="card-head"><h2>Lifecycle events</h2></div>
  {table(
      ["Event", "State", "Actor", "Execution", "Detail", "Recorded"],
      event_rows,
      empty_title="No events",
      empty_message="No lifecycle events recorded.",
  )}
</section>
"""

    return layout("Recommendation", "opportunities", content, refreshed_at=data.get("refreshed_at"))


def render_executions(data):
    groups = data["groups"]

    unexpected = data["unexpected_states"]

    state_filter = data.get("state_filter")

    filter_bar = """
<form method="get" action="/executions" class="selection-bar">
  <label for="state">Outcome filter</label>
  <select id="state" name="state" class="path-input">
    <option value="">all outcomes</option>
    <option value="pending">group: awaiting action</option>
    <option value="active">group: in progress</option>
    <option value="completed">group: completed</option>
    <option value="attention">group: needs attention</option>
    <option value="succeeded">state: succeeded</option>
    <option value="rolled_back">state: rolled back</option>
    <option value="failed_execution">state: FFmpeg failed</option>
    <option value="failed_verification">state: verification failed</option>
    <option value="failed_replacement">state: replacement failed</option>
    <option value="interrupted">state: interrupted</option>
    <option value="recovered">state: recovered</option>
  </select>
  <button type="submit" class="btn small">Apply filter</button>
  <a class="btn small ghost" href="/executions">Clear</a>
</form>
"""

    if data["total_count"] == 0:
        content = (
            empty_state(
                "The optimisation queue is empty",
                "Approve a current recommendation to create an "
                "execution job. Execution never happens without "
                "explicit approval.",
            )
            + _queue_start_bar()
            + filter_bar
        )
        return layout("Queue", "executions", content)

    sections = []

    for group in groups:
        if not group["executions"]:
            continue

        rows = [
            _queue_row(job) for job in group["executions"]
        ]

        sections.append(
            f"""
<section class="card">
  <div class="card-head">
    <h2>{esc(group["title"])}</h2>
    <span class="muted">{len(group["executions"])} job(s)</span>
  </div>
  <p class="muted">{esc(group["description"])}</p>
  {_queue_table(rows)}
</section>
"""
        )

    if unexpected:
        rows = [_queue_row(job) for job in unexpected]

        sections.append(
            f"""
<section class="card">
  <div class="card-head"><h2>Other states</h2></div>
  <p class="muted">
    Jobs whose state has no queue section are listed here rather
    than hidden.
  </p>
  {_queue_table(rows)}
</section>
"""
        )

    if state_filter and not sections:

        sections.append(
            empty_state(
                "No jobs match this outcome filter",
                f'No recorded execution is currently in '
                f'"{esc(state_filter)}". Filters never create rows; '
                f'clear the filter to see the full history.',
            )
        )

    content = filter_bar + "".join(sections)

    return layout("Queue", "executions", content)


def _queue_start_bar():
    """
    The explicit user action that starts the background execution
    queue. Starting the queue never invents work: it executes exactly
    the approved/planned jobs already recorded.
    """

    return """
<section class="card">
  <div class="card-head"><h2>Run the optimisation queue</h2></div>
  <p class="muted">
    Starts the background queue. One approved optimisation executes
    at a time; eligible unfinished jobs are recovered first. Failures
    are terminal and truthful, and later jobs continue. Nothing
    executes without explicit approval.
  </p>
  <form method="post" action="/executions/start-queue">
    <button class="btn" type="submit">Start queue</button>
  </form>
</section>
"""


def _queue_row(job):
    return f"""
<tr>
  <td>{link(f"/executions/{job['id']}", f"#{job['id']}")}</td>
  <td>{media_link(job["media_id"], f'media {job["media_id"]}')}</td>
  <td>{badge(job["state_label"], job["state_badge"])}</td>
  <td>{esc(job["opportunity"] or "-")}</td>
  <td>
    {
        link(
            f"/recommendations/{job['recommendation_id']}",
            f"Rec #{job['recommendation_id']}",
        )
        if job["recommendation_id"]
        else "-"
    }
  </td>
</tr>
"""


def _queue_table(rows):
    return f"""
<div class="table-wrap">
<table class="data-table">
  <thead><tr>
    <th>Job</th><th>Media</th><th>State</th><th>Opportunity</th>
    <th>Recommendation</th>
  </tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>
</div>
"""


def render_queue_started():
    """
    Honest confirmation that the queue worker was started. The worker
    runs in the background; the queue page reflects progress.
    """

    content = f"""
<section class="card">
  <div class="card-head"><h2>Optimisation queue started</h2></div>
  <p class="muted">
    The background queue is running. One approved optimisation
    executes at a time; eligible unfinished jobs are recovered first.
    Each job is executed exactly once, through the verified safety
    lifecycle, and its outcome is recorded in the queue below.
  </p>
  <p><a class="btn small ghost" href="/executions">Back to the queue</a></p>
</section>
"""
    return layout(
        "Queue",
        "executions",
        content,
    )


def render_quick_find(data):
    """
    Quick Find page: select ONE media file, analyse it through the
    existing pipeline, and show its recommendation. Quick Find is not
    a second intelligence system.
    """

    operations = data.get("operations") or []

    operations_html = ""

    if operations:
        rows = []
        for operation in operations:
            rows.append(
                f"<li><strong>{esc(operation['operation'])}</strong> "
                f"v{esc(operation['semantic_version'])} · "
                f"{esc(operation['description'])}</li>"
            )
        operations_html = (
            '<details class="disclosure">'
            "<summary>Executable operations</summary>"
            f"<ul>{''.join(rows)}</ul>"
            "</details>"
        )

    content = f"""
<section class="card">
  <div class="card-head"><h2>Quick Find</h2></div>
  <p class="muted">
    Analyse one media file and show what NAMOA recommends. The file
    is analysed through the normal pipeline and its recommendation
    comes from the normal recommendation authority. Approval and
    execution use the same explicit boundaries as the queue.
  </p>
  {_form_error_panel(data)}
  <form method="post" action="/quick-find" class="org-form">
    <label for="quick-find-path">Media file path</label>
    <div class="search-row">
      <input
        id="quick-find-path"
        type="text"
        name="path"
        placeholder="/path/to/media.mkv"
        value="{esc((data.get("input") or {}).get("path") or "")}"
        required
      />
      <button type="button" class="btn small ghost js-browse-toggle"
              data-browser="quick-find" aria-expanded="false"
              aria-controls="folder-browser-quick-find">
        Browse
      </button>
    </div>
    {folder_browser_block("quick-find-path", "quick-find", show_toggle=False, show_files=True)}
    <div class="info-panel">
      <p>
        Browse to the folder holding the file, then choose
        the file from the file list: Select fills the
        media file path for you, so nothing needs typing.
        Analysis runs through the normal pipeline.
      </p>
    </div>
    <div class="actions-row">
      <button type="submit" class="btn">Analyse</button>
    </div>
  </form>
  <div class="operations-block">
  {operations_html}
  </div>
</section>
"""
    return layout(
        "Quick Find",
        "quick-find",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def render_quick_find_result(data):
    """
    Quick Find result: the authoritative current-valid recommendation
    for the analysed lineage, or an honest absence.
    """

    candidate = data.get("candidate")

    path = data.get("path") or "-"

    lineage_name = data.get("lineage_name")

    if candidate is None:

        content = f"""
<section class="card">
  <div class="card-head"><h2>Quick Find result</h2></div>
  {facts([
      ("File", esc(path)),
      ("Analysed", "Yes" if data.get("analysis_reported") else "No"),
  ])}
  <p class="muted">
    No current recommendation was produced for
    this file. This is an honest result: either the file is already
    efficient, the analysis did not establish a worthwhile
    opportunity, or the recommendation is stale.
  </p>
  <p>
    <a class="btn small ghost" href="/quick-find">Find another file</a>
  </p>
  <form method="post" action="/organisation/whatif/file"
        class="inline-form">
    <input type="hidden" name="media_id"
           value="{esc(data.get("media_id") or "")}">
    <button class="btn small ghost" type="submit">
      Preview this file in What-If
    </button>
    <span class="muted">
      Read-only organisation preview. Nothing is changed.
    </span>
  </form>
</section>
"""
    else:

        media_id = candidate["media_id"]

        change_summary = candidate.get("change_summary") or {}

        content = f"""
<section class="card">
  <div class="card-head"><h2>Quick Find result</h2></div>
  {facts([
      ("File", esc(path)),
      ("Lineage", link(f"/media/{media_id}", f"media {media_id}")),
      ("Recommended change", esc(change_summary.get("one_liner") or "Not recorded")),
      ("Confidence", esc(candidate.get("confidence_percent") or "-")),
      ("Risk", esc(candidate.get("risk") or "-")),
  ])}
  <p class="muted">
    Approve to create an execution job. Approval never starts
    execution; the job is queued and runs only when you start it.
  </p>
  <form method="post" action="/opportunities/{media_id}/approve">
    <button class="btn" type="submit">Approve optimisation</button>
  </form>
  <div class="actions-row">
    <button type="button" class="btn small btn-danger js-reject-single"
            data-media-id="{media_id}"
            data-name="{esc(candidate.get("file_name") or path)}">Reject</button>
    <a class="btn small btn-preview" href="/preview/new?origin=analysis&amp;ref={media_id}">Preview</a>
  </div>
  <p><a class="btn small ghost" href="/opportunities/{media_id}">Full details</a></p>
  <p><a class="btn small ghost" href="/quick-find">Find another file</a></p>
  <form method="post" action="/organisation/whatif/file"
        class="inline-form">
    <input type="hidden" name="media_id" value="{media_id}">
    <button class="btn small ghost" type="submit">
      Preview this file in What-If
    </button>
    <span class="muted">
      Read-only organisation preview. Nothing is changed.
    </span>
  </form>
</section>
"""

    return layout(
        "Quick Find",
        "quick-find",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def render_execution_detail(data):
    job = data["execution"]

    label, kind = (
        job["state_label"],
        job["state_badge"],
    )

    actions = []

    if job["state"] in ("approved", "planned"):
        actions.append(f"""
  <form method="post" action="/executions/{job["id"]}/run">
    <button class="btn small" type="submit">Run execution</button>
  </form>""")

    if job["state"] == "succeeded":
        actions.append(f"""
  <form method="post" action="/executions/{job["id"]}/rollback">
    <button class="btn small" type="submit">Roll back to original</button>
  </form>""")

    if job["state"] == "succeeded" and job.get("delete_original_requested"):
        actions.append(f"""
  <form method="post" action="/executions/{job["id"]}/delete-original">
    <button class="btn small" type="submit">Delete original file</button>
  </form>""")

    action_html = "".join(actions) or "<p>No actions for this state.</p>"

    fact_items = [
        ("Job", f'#{job["id"]}'),
        ("State", badge(label, kind)),
        ("Media", media_link(job["media_id"], f'media {job["media_id"]}')),
        ("Opportunity", esc(job["opportunity"] or "-")),
        ("Source", esc(job["source_path"])),
        ("Approved by", esc(job["approved_by"])),
        ("Operation", esc(job["operation"] or "-")),
        ("Source observation", esc(job["source_observation_id"] or "-")),
        ("Result observation", esc(job["result_observation_id"] or "-")),
        ("Output sha256", esc(job["output_sha256"] or "-")),
        ("Backup of original", esc(job["backup_path"] or "-")),
        ("Delete original requested", "Yes" if job.get("delete_original_requested") else "No"),
    ]

    if job.get("deletion_state") is not None:
        fact_items.append(
            ("Deletion state", esc(job["deletion_state"]))
        )

    if job.get("analysis_run_id") is not None:
        fact_items.append(
            (
                "Originating analysis run",
                run_link(
                    job["analysis_run_id"],
                    f"Run #{job['analysis_run_id']}",
                ),
            )
        )

    if job.get("recommendation_id") is not None:
        fact_items.append(
            (
                "Accepted recommendation",
                link(
                    f"/recommendations/{job['recommendation_id']}",
                    f"Rec #{job['recommendation_id']}",
                ),
            )
        )

    policy_html = ""

    if job.get("policy_decision_allowed") is False:
        reasons = "".join(
            f"<li>{esc(reason)}</li>"
            for reason in job.get("policy_reasons") or []
        )
        policy_html = f"""
<section class="card">
  <div class="card-head"><h2>Policy decision</h2></div>
  <p class="muted">
    The policy boundary refused this execution; the refusal is
    recorded on the job and nothing was executed.
  </p>
  <ul>{reasons or "<li>No reasons recorded</li>"}</ul>
</section>
"""

    before_after_html = ""

    before_after = data.get("before_after")

    if before_after is not None:

        def _observation_block(side_label, observation):

            if observation is None:

                return (
                    f'<div><h3>{esc(side_label)}</h3>'
                    "<p class=\"muted\">Not available for this "
                    "execution.</p></div>"
                )

            return f"""
<div>
  <h3>{esc(side_label)}: Observation #{observation['id']}</h3>
  {facts([
      ("Path", esc(observation["file_path"])),
      ("Size", esc(observation["size"])),
      ("Observed at", esc(observation["observed_at"])),
      ("Identity match", esc(observation["identity_match_method"])),
  ])}
</div>
"""

        history_link_html = link(
            f"/media/{job['media_id']}/history",
            "Full lineage history",
        )

        before_after_html = f"""
<details class="disclosure">
  <summary>Before and after this execution</summary>
  <p class="muted">
    Both sides are persisted filesystem observations of this
    lineage, resolved through the lineage's authoritative
    observation history. The "after" side exists only when the
    execution authority recorded a result observation.
  </p>
  {_observation_block("Before (producing run's observation)", before_after.get("before"))}
  {_observation_block("After (recorded result observation)", before_after.get("after"))}
  <p>{history_link_html}</p>
</details>
"""

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Execution #{job["id"]}</h2>
    {badge(label, kind)}
  </div>
  {facts(fact_items)}
  {"<p class='muted'>" + esc(job["error"]) + "</p>" if job["error"] else ""}
  {action_html}
  {before_after_html}
</section>
{_transformation_card(job)}
{_savings_card(job)}
{policy_html}
"""

    return layout(
        "Executions",
        "opportunities",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def _transformation_card(job):
    """
    The requested transformation (what the user approved) as a
    presentation card. Distinct from the recommendation and the plan.
    """

    transformation = job.get("requested_transformation")

    if not transformation:
        return ""

    propositions = transformation.get("propositions") or []

    prop_rows = [
        [
            esc(p.get("proposition") or "-"),
            esc(p.get("current_state") or "-"),
            esc(p.get("target_state") or "-"),
        ]
        for p in propositions
    ]

    params_items = []

    for key, value in (transformation.get("parameters") or {}).items():
        params_items.append((key.replace("_", " "), esc(value)))

    return f"""
<section class="card">
  <div class="card-head"><h2>Requested transformation</h2></div>
  <p class="muted">
    What you approved. It is recorded independently of the
    recommendation that caused it and of the execution plan generated
    from it, and it is never silently changed.
  </p>
  {facts([
      ("Operation", badge(esc(transformation.get("operation") or "-"), "opportunity")),
      ("Source", esc(transformation.get("source") or "-")),
      ("Preserve resolution", "Yes" if transformation.get("preserve_resolution") else "No"),
      ("Preserve HDR", "Yes" if transformation.get("preserve_hdr") else "No"),
      ("Audio handling", esc(transformation.get("audio_handling") or "-")),
  ])}
  {table(
      ["Proposition", "Current state", "Target state"],
      prop_rows,
      empty_title="No propositions",
      empty_message="No proposition detail recorded.",
  )}
  {facts(params_items) if params_items else ""}
</section>
"""


def _savings_card(job):
    """
    Predicted vs measured savings. Prediction is never presented as a
    measured result; compatibility operations never claim a storage
    saving.
    """

    predicted = job.get("predicted")

    measured = job.get("measured")

    if not predicted and not measured:
        return ""

    sections = ""

    if predicted:
        compat = predicted.get("compatibility_only")

        if compat:
            predicted_line = (
                "Compatibility operation: no storage saving is "
                "claimed."
            )
        elif predicted.get("predicted_saved_bytes") is None:
            predicted_line = (
                "No defensible prediction for this transformation."
            )
        else:
            predicted_line = (
                f'Estimated saving <strong>'
                f'{esc(predicted["predicted_saved_size"])}'
                f'</strong> '
                f'({esc(predicted["predicted_saving_text"])}) '
                f'before execution (estimate, not measured).'
            )

        sections += f"""
<div>
  <h3>Predicted</h3>
  <p class="muted">{predicted_line}</p>
  {facts([
      ("Basis", esc(predicted.get("basis") or "-")),
      ("Confidence", esc(predicted.get("confidence") if predicted.get("confidence") is not None else "-")),
  ])}
</div>
"""

    if measured:
        saved = measured.get("measured_saved_bytes")

        if saved is not None and saved > 0:
            measured_line = (
                f'Measured saving <strong>'
                f'{esc(measured["measured_saved_size"])}'
                f'</strong> '
                f'({esc(measured["measured_saving_text"])}) '
                f'from the actual result observation.'
            )
        elif saved is not None:
            measured_line = (
                "Measured result is not smaller than the source; "
                "no storage saving was achieved."
            )
        else:
            measured_line = "Measured result not recorded."

        sections += f"""
<div>
  <h3>Measured</h3>
  <p class="muted">{measured_line}</p>
  {facts([
      ("Source size", esc(measured.get("source_size_bytes") if measured.get("source_size_bytes") is not None else "-")),
      ("Result size", esc(measured.get("result_size_bytes") if measured.get("result_size_bytes") is not None else "-")),
      ("Result observation", esc(measured.get("result_observation_id") if measured.get("result_observation_id") is not None else "-")),
  ])}
</div>
"""

    return f"""
<section class="card">
  <div class="card-head"><h2>Predicted vs measured savings</h2></div>
  <p class="muted">
    Predicted values are expectations recorded before execution.
    Measured values come from the actual source and result
    observations after successful verified replacement. A prediction
    is never presented as a measured result.
  </p>
  {sections}
</section>
"""


# ---------------------------------------------------------
# Sprint 13 library organisation
#
# Presentation only: these templates format page data assembled
# by handlers over the organisation application boundary. They
# contain no rule logic, no identity logic, and no persistence
# access, and they never imply filesystem effects.
# ---------------------------------------------------------


def _organisation_decision_run_card(decision_run):
    root_bits = []

    for entry in decision_run["library_roots"] or []:
        if isinstance(entry, dict):
            path = entry.get("path") or ""
            alias = entry.get("alias") or ""
            root_bits.append(
                f"{path} {{{alias}}}" if alias else path
            )
        else:
            root_bits.append(str(entry))

    root_text = ", ".join(root_bits) or "none configured"
    if decision_run is None:
        return ""

    return f"""
<section class="card">
  <div class="card-head"><h2>Technical details</h2></div>
  <p class="muted">
    How NAMOA reached the decisions above. The snapshot is the exact
    provenance of this check's suggestions.
  </p>
  <details class="disclosure tech-panel">
    <summary>Intelligence version and policy snapshot</summary>
    {facts([
        ("Identity digest", esc(decision_run["identity_digest_short"] or "Not recorded")),
        ("Git revision", esc(decision_run["git_revision"])),
        ("Lineages considered", esc(decision_run["lineages_considered"])),
        ("Proposals created", esc(decision_run["proposals_created"])),
        ("Hash coverage", f'{decision_run["hash_coverage_hashed"]}/{decision_run["hash_coverage_total"]} lineages with recorded content hashes'),
        ("Library roots", esc(root_text)),
        ("Created", esc(decision_run["created_at"])),
    ])}
    <details class="disclosure tech-panel">
      <summary>Rule component versions</summary>
      <ul>{''.join(f'<li>{esc(name)}: {esc(version)}</li>' for name, version in sorted(decision_run["rule_versions"].items())) or '<li>No rules recorded</li>'}</ul>
    </details>
    <details class="disclosure tech-panel">
      <summary>Policy values</summary>
      <pre>{esc(json_format(decision_run["policy_values"]))}</pre>
    </details>
  </details>
</section>
"""


def json_format(value):
    """Compact deterministic JSON rendering for snapshot display."""

    import json as _json

    return _json.dumps(value, indent=2, sort_keys=True)


def render_organisation(data):
    decision_run = data.get("decision_run")
    proposals = data.get("proposals") or []

    executions_link = """
<section class="card">
  <div class="card-head"><h2>Organisation workspace</h2></div>
  <p class="muted">
    Configure, design, test, preview, approve, execute,
    then verify. Each step below opens its own page;
    nothing here moves or renames files by itself.
  </p>
  <div class="step-grid">
    <a class="step-card" href="/organisation/integrations">
      <h3><span class="step-num">1</span>Configure</h3>
      <p>Provider settings: Jellyfin, Radarr, Sonarr.</p>
    </a>
    <a class="step-card" href="/organisation/profiles">
      <h3><span class="step-num">2</span>Design and rules</h3>
      <p>Profiles, folder structure, categories, tag rules.</p>
    </a>
    <a class="step-card" href="/organisation/whatif">
      <h3><span class="step-num">3</span>Test</h3>
      <p>What-If previews and directory sampler. Read-only.</p>
    </a>
    <a class="step-card" href="/organisation/preflight">
      <h3><span class="step-num">4</span>Preflight</h3>
      <p>Read-only checks over the setup you are about to use.</p>
    </a>
    <a class="step-card" href="/organisation/reconcile">
      <h3><span class="step-num">5</span>Preview and approve</h3>
      <p>Scope preview, review, then explicit acceptance.</p>
    </a>
    <a class="step-card" href="/organisation/executions">
      <h3><span class="step-num">6</span>Execute and verify</h3>
      <p>Organisation executions with verification state.</p>
    </a>
    <a class="step-card" href="/organisation/scope-executions">
      <h3><span class="step-num">7</span>History and recovery</h3>
      <p>Previous runs, failures, and state-gated recovery.</p>
    </a>
  </div>
</section>
"""

    generate_form = """
<form method="post" action="/organisation/generate" class="inline-form">
  <button class="btn small" type="submit">Check for improvements</button>
</form>
<p class="muted">
  The check is read-only over your files: it derives evidence from
  persisted observations and records durable suggestions. It never
  moves, renames, creates, or deletes anything on disk.
</p>
"""

    proposed_rows = []

    for proposal in proposals:
        if proposal["state"] != "proposed":
            continue

        destination = proposal.get("proposed_destination")

        proposed_rows.append(
            f"""
<tr>
  <td class="select-cell">
    <input type="checkbox" class="select-item" name="selected"
           value="{proposal["id"]}"
           aria-label="Select organisation proposal {proposal["id"]}">
  </td>
  <td>{media_link(proposal["media_id"], f'media {proposal["media_id"]}')}</td>
  <td>{badge(proposal["intent_label"], proposal["intent_badge"])}</td>
  <td>{esc(destination or proposal.get("proposed_name") or "")}</td>
  <td>{proposal["confidence_percent"]}</td>
  <td>{esc(proposal["risk"])}</td>
  <td>{link(f"/organisation/proposals/{proposal['id']}", "details")}</td>
</tr>"""
        )

    decided_rows = []

    for proposal in proposals:
        if proposal["state"] == "proposed":
            continue

        decided_rows.append(
            f"""
<tr>
  <td>{media_link(proposal["media_id"], f'media {proposal["media_id"]}')}</td>
  <td>{badge(proposal["intent_label"], proposal["intent_badge"])}</td>
  <td>{badge(proposal["state_label"], proposal["state_badge"])}</td>
  <td>{esc(proposal.get("proposed_destination") or proposal.get("proposed_name") or "")}</td>
  <td>{link(f"/organisation/proposals/{proposal['id']}", "details")}</td>
</tr>"""
        )

    if decision_run is None:
        verdict_html = f"""
<section class="card">
  <div class="card-head"><h2>Organisation improvements</h2></div>
  <p class="verdict">Your library looks organised.</p>
  <p class="muted">
    NAMOA hasn't checked for organisation improvements yet. Run a
    check to look for things worth moving, renaming, or grouping.
    This is the recommendations flow: one optional starting
    point alongside the workspace steps above.
  </p>
  {generate_form}
</section>
"""
    elif not proposed_rows:
        verdict_html = f"""
<section class="card">
  <div class="card-head"><h2>Organisation improvements</h2></div>
  <p class="verdict">Your library looks organised.</p>
  <p class="muted">
    NAMOA didn't find any organisation changes worth recommending.
    This is a normal result, not an error.
  </p>
  {generate_form}
</section>
"""
    else:
        verdict_html = f"""
<section class="card">
  <div class="card-head"><h2>Organisation improvements</h2></div>
  <p class="verdict">
    NAMOA found {len(proposed_rows)} suggested improvement(s).
  </p>
  <p class="muted">
    Review the suggestions below. Accepting records your approval as
    durable intent only: NAMOA never moves or renames a file in this
    step. These recommendations are one starting point; the
    workspace steps above cover the full workflow.
  </p>
  {generate_form}
</section>
"""

    selection_html = ""

    if proposed_rows:
        selection_html = f"""
<section class="card">
  <div class="card-head"><h2>Proposed improvements ({len(proposed_rows)})</h2></div>
  <form method="post" action="/organisation/accept-selected" id="selection-form">
    <div class="selection-bar">
      <label class="select-all-label">
        <input type="checkbox" id="select-all">
        Select all
      </label>
      <button type="button" class="btn small" id="clear-selection">Clear selection</button>
      <span class="muted" id="selection-count"></span>
      <button type="submit" class="btn small">Review selected…</button>
    </div>
    <div class="table-wrap">
    <table class="data-table">
      <thead><tr>
        <th>Select</th><th>Media</th><th>Suggested action</th><th>Proposal</th>
        <th>Confidence</th><th>Risk</th><th></th>
      </tr></thead>
      <tbody>{''.join(proposed_rows)}</tbody>
    </table>
    </div>
  </form>
  <p class="muted">
    Reviewing leads to an explicit confirmation step. Acceptance
    records approved intent only: NAMOA does not move or rename any
    file in this step.
  </p>
</section>
"""

    decided_html = ""

    if decided_rows:
        decided_html = f"""
<section class="card">
  <div class="card-head"><h2>Recent decisions ({len(decided_rows)})</h2></div>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr>
      <th>Media</th><th>Suggested action</th><th>State</th><th>Proposal</th><th></th>
    </tr></thead>
    <tbody>{''.join(decided_rows)}</tbody>
  </table>
  </div>
</section>
"""

    content = verdict_html + executions_link + selection_html + decided_html

    if decision_run is not None:
        content += _organisation_decision_run_card(decision_run)

    return layout(
        "Organisation",
        "organisation",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def render_proposal_detail(data):
    proposal = data["proposal"]
    events = data.get("events") or []
    decision_run = data.get("decision_run")
    media = data.get("media")

    evidence = proposal.get("evidence") or {}

    fact_items = [
        ("Proposal", badge(proposal["state_label"], proposal["state_badge"])),
        ("Intent", badge(proposal["intent_label"], proposal["intent_badge"])),
        ("Decision run", f'Decision run #{proposal["decision_run_id"]}'),
        ("Media", media_link(proposal["media_id"], f'media {proposal["media_id"]}')),
    ]

    if media is not None:
        fact_items.append(("Current path", esc(media["file_path"])))

    if proposal.get("related_media_id"):
        fact_items.append(
            (
                "Related media",
                media_link(
                    proposal["related_media_id"],
                    f'media {proposal["related_media_id"]}',
                ),
            )
        )

    if proposal.get("proposed_destination"):
        fact_items.append(("Proposed destination", esc(proposal["proposed_destination"])))

    if proposal.get("proposed_name"):
        fact_items.append(("Proposed name", esc(proposal["proposed_name"])))

    fact_items.extend(
        [
            ("Confidence", proposal["confidence_percent"]),
            ("Risk", esc(proposal["risk"])),
            ("Intelligence digest", esc((proposal["intelligence_identity"] or "")[:16] or "Not recorded")),
            ("Produced", esc(proposal["created_at"])),
        ]
    )

    duplicate_note = ""

    if proposal["intent"] == "flag_duplicate":
        duplicate_note = """
<p class="muted">
  This is a DUPLICATE CANDIDATE backed by exact content-hash
  equality between two current observations. It is NOT identity
  equivalence: NAMOA has not merged, rewritten, or equated the two
  media identities, and no file has been touched.
</p>
"""

    execution_note = """
<p class="muted">
  Accepting records approved intent only. No file is moved, renamed,
  or changed in this step.
</p>
"""

    execute_action = ""

    if proposal["state"] == "accepted" and proposal["intent"] in (
        "move_destination",
        "rename",
    ):
        execute_action = f"""
  <form method="post" action="/organisation/proposals/{proposal["id"]}/execute"
        class="inline-form">
    <button class="btn small btn-warn" type="submit">
      Execute approved change (move/rename this file)
    </button>
    <span class="muted">
      Runs the safe, verified organisation move. Nothing moves
      without your explicit action here.
    </span>
  </form>
"""

    events_html = ""

    if events:
        event_rows = "".join(
            f"""
<tr>
  <td>{badge(event["new_state_label"], event["new_state_badge"])}</td>
  <td>{esc(event["actor"])}</td>
  <td>{esc(event["detail"] or "")}</td>
  <td>{esc(event["created_at"])}</td>
</tr>"""
            for event in events
        )

        events_html = f"""
<section class="card">
  <div class="card-head"><h2>Lifecycle events</h2></div>
  <p class="muted">Append-only ledger; entries are never edited or removed.</p>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr><th>Event</th><th>Actor</th><th>Detail</th><th>When</th></tr></thead>
    <tbody>{event_rows}</tbody>
  </table>
  </div>
</section>
"""

    run_html = ""

    if decision_run is not None:
        run_html = _organisation_decision_run_card(decision_run)

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Organisation improvement #{proposal["id"]}</h2>
    {badge(proposal["state_label"], proposal["state_badge"])}
  </div>
  <p class="verdict">{esc(proposal["intent_label"])}</p>
  {duplicate_note}
  {execution_note}
  {execute_action}
  <details class="disclosure">
    <summary>Why this improvement? (rationale)</summary>
    <ul>{''.join(f'<li>{esc(line)}</li>' for line in proposal["rationale"]) or '<li>No rationale recorded</li>'}</ul>
  </details>
  <details class="disclosure">
    <summary>Evidence cited</summary>
    <pre>{esc(json_format(evidence))}</pre>
  </details>
  <details class="disclosure">
    <summary>Technical details</summary>
    {facts(fact_items)}
  </details>
</section>
{run_html}
{events_html}
"""

    return layout(
        f"Organisation proposal #{proposal['id']}",
        "organisation",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def render_organisation_accept_confirmation(data):
    items = data["items"]
    acceptable_ids = data["acceptable_ids"]

    rows = []

    for item in items:
        if item.get("acceptable"):
            rows.append(
                f"""
<tr>
  <td>{media_link(item["media_id"], f'media {item["media_id"]}')}</td>
  <td>{badge(item["intent_label"], item["intent_badge"])}</td>
  <td>{esc(item.get("proposed_destination") or item.get("proposed_name") or "")}</td>
  <td>{item["confidence_percent"]}</td>
  <td>{esc(item["risk"])}</td>
</tr>"""
            )
        else:
            rows.append(
                f"""
<tr>
  <td>proposal {item["proposal_id"]}</td>
  <td colspan="4" class="muted">{esc(item["reason"])}</td>
</tr>"""
            )

    if acceptable_ids:
        confirm_form = f"""
<form method="post" action="/organisation/confirm-acceptance">
  {''.join(
      f'<input type="hidden" name="selected" value="{proposal_id}">'
      for proposal_id in acceptable_ids
  )}
  <p class="muted">
    Confirming records your approval of these organisation
    proposals as durable intent. NAMOA performs NO filesystem
    operation in this step: nothing is moved, renamed, created,
    or deleted until you explicitly execute an accepted
    proposal from its proposal details page.
  </p>
  <button class="btn" type="submit">Confirm acceptance</button>
  <a class="btn small ghost" href="/organisation">Cancel</a>
</form>
"""
    else:
        confirm_form = f"""
<p class="muted">
  None of the selected proposals can currently be accepted.
  Nothing was changed.
</p>
<p><a class="btn small ghost" href="/organisation">Back to organisation</a></p>
"""

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Confirm organisation acceptance</h2>
    <span class="badge stale">Confirmation required</span>
  </div>
  <p class="muted">
    You are about to accept {len(acceptable_ids)} of
    {len(items)} selected proposal(s). Facts come from the
    authoritative current proposals.
  </p>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr>
      <th>Media</th><th>Intent</th><th>Proposal</th>
      <th>Confidence</th><th>Risk</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  </div>
  {confirm_form}
</section>
"""

    return layout(
        "Confirm organisation acceptance",
        "organisation",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def render_organisation_acceptance_report(data):
    accepted = data["accepted"]
    refused = data["refused"]

    accepted_rows = [
        f"""
<tr>
  <td>{link(f"/organisation/proposals/{entry['proposal_id']}", f'Proposal #{entry["proposal_id"]}')}</td>
  <td>{media_link(entry["media_id"], f'media {entry["media_id"]}')}</td>
  <td>{badge(organisation_intent_label(entry["intent"])[0], organisation_intent_label(entry["intent"])[1])}</td>
  <td>{badge("Accepted intent", "current")} <span class="muted">(no filesystem effect)</span></td>
</tr>"""
        for entry in accepted
    ]

    refused_rows = []

    for entry in refused:
        refused_rows.append(
            f"""
<tr>
  <td>proposal {entry["proposal_id"]}</td>
  <td class="muted">{esc(entry["reason"])}</td>
</tr>"""
        )

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Acceptance recorded</h2>
    <span class="badge current">{len(accepted)} accepted</span>
  </div>
  {f'<div class="table-wrap"><table class="data-table"><thead><tr><th>Proposal</th><th>Media</th><th>Intent</th><th>Result</th></tr></thead><tbody>{"".join(accepted_rows)}</tbody></table></div>'
      if accepted_rows else empty_state(
          "Nothing was accepted",
          "No selected proposal could be accepted.",
      )}
  <div class="info-panel">
    <p><strong>Next steps:</strong></p>
    <ol class="workflow-steps">
      <li>Open each accepted proposal above to review its
      exact source, destination and safety checks.</li>
      <li>Execute runs the approved move through the
      existing execution authority with verification.
      Nothing runs without this explicit step.</li>
      <li>Follow progress under Organisation then
      Executions; history and recovery live under
      History.</li>
    </ol>
  </div>
  <p class="muted">
    Acceptance is a durable record of approved intent attached to
    the proposal's lifecycle ledger. No filesystem operation was
    performed yet: execution is the separate explicit step above.
  </p>
  <p>
    <a class="btn small ghost" href="/organisation">Back to organisation</a>
    <a class="btn small" href="/organisation/executions">View executions</a>
  </p>
</section>
"""

    if refused_rows:
        content += f"""
<section class="card">
  <div class="card-head"><h2>Not accepted</h2></div>
  <p class="muted">
    These selections were refused by the organisation lifecycle;
    nothing was changed for them.
  </p>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr><th>Selection</th><th>Reason</th></tr></thead>
    <tbody>{''.join(refused_rows)}</tbody>
  </table>
  </div>
</section>
"""

    return layout(
        "Organisation acceptance recorded",
        "organisation",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def render_organisation_executions(data):
    """
    The organisation execution queue: every recorded organisation
    execution grouped by state. Presentation only; the lifecycle is
    owned by the organisation execution authority.
    """

    groups = data["groups"] or []

    unexpected = data.get("unexpected_states") or []

    counts = data.get("counts") or {}

    if data["total_count"] == 0:

        content = empty_state(
            "No organisation executions yet",
            "Approve an organisation proposal, then execute it from "
            "the proposal details. Execution moves a file only after "
            "explicit approval and never without verification.",
        )

        return layout(
            "Organisation executions",
            "organisation",
            content,
            refreshed_at=data.get("refreshed_at"),
        )

    sections = []

    for group in groups:

        if not group["executions"]:
            continue

        rows = [
            _organisation_execution_row(execution)
            for execution in group["executions"]
        ]

        sections.append(
            f"""
<section class="card">
  <div class="card-head">
    <h2>{esc(group["title"])}</h2>
    <span class="muted">{len(group["executions"])} execution(s)</span>
  </div>
  <p class="muted">{esc(group["description"])}</p>
  {_organisation_execution_table(rows)}
</section>
"""
        )

    if unexpected:

        rows = [
            _organisation_execution_row(execution)
            for execution in unexpected
        ]

        sections.append(
            f"""
<section class="card">
  <div class="card-head"><h2>Other states</h2></div>
  <p class="muted">
    Executions whose state has no queue section are listed here
    rather than hidden.
  </p>
  {_organisation_execution_table(rows)}
</section>
"""
        )

    content = "".join(sections)

    return layout(
        "Organisation executions",
        "organisation",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def _organisation_execution_row(execution):
    return f"""
<tr>
  <td>{link(f"/organisation/executions/{execution['id']}", f"#{execution['id']}")}</td>
  <td>{media_link(execution["media_id"], f'media {execution["media_id"]}')}</td>
  <td>{badge(execution["state_label"], execution["state_badge"])}</td>
  <td>{badge(execution["intent_label"], execution["intent_badge"])}</td>
  <td>{esc(execution["source_path"])}</td>
  <td>{esc(execution["destination_path"] or "-")}</td>
</tr>
"""


def _organisation_execution_table(rows):
    return f"""
<div class="table-wrap">
<table class="data-table">
  <thead><tr>
    <th>Execution</th><th>Media</th><th>State</th><th>Intent</th>
    <th>Source</th><th>Destination</th>
  </tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>
</div>
"""


def render_organisation_execution_detail(data):
    """
    One organisation execution with its lifecycle events, the
    execution-authorised identity continuity, and the producing
    proposal context.
    """

    execution = data["execution"]

    events = data.get("events") or []

    continuity = data.get("continuity") or []

    proposal = data.get("proposal")

    actions = []

    if execution["state"] in (
        "failed",
        "interrupted",
        "recovery_required",
    ):
        actions.append(f"""
  <form method="post" action="/organisation/executions/{execution["id"]}/recover">
    <button class="btn small" type="submit">Recover against filesystem reality</button>
  </form>""")

    action_html = "".join(actions) or "<p>No actions for this state.</p>"

    fact_items = [
        ("Execution", f'#{execution["id"]}'),
        ("State", badge(execution["state_label"], execution["state_badge"])),
        ("Intent", badge(execution["intent_label"], execution["intent_badge"])),
        ("Media", media_link(execution["media_id"], f'media {execution["media_id"]}')),
        ("Source", esc(execution["source_path"])),
        ("Source observation", esc(execution["source_observation_id"] or "-")),
        ("Destination", esc(execution["destination_path"] or "-")),
        ("Result observation", esc(execution["result_observation_id"] or "-")),
        ("Continuity", esc(execution["continuity_id"] or "-")),
        ("Actor", esc(execution["actor"])),
        ("Created", esc(execution["created_at"])),
        ("Last transition", esc(execution["updated_at"])),
    ]

    if proposal is not None:
        fact_items.append(
            (
                "Proposal",
                link(
                    f"/organisation/proposals/{proposal['id']}",
                    f"Proposal #{proposal['id']}",
                ),
            )
        )

    fact_items.append(
        (
            "Verification",
            esc(
                "verified"
                if execution.get("result_observation_id")
                else "not yet verified"
            ),
        )
    )

    progress_html = ""

    if execution["state"] in ("pending", "running"):
        progress_html = """
<p class="muted">
  This execution is in progress. Status reflects the
  persisted execution state and its events below.
  <a class="btn small ghost" href="">Refresh status</a>
</p>"""

    error_html = (
        f'<p class="muted">{esc(execution["error"])}</p>'
        if execution.get("error")
        else ""
    )

    events_html = ""

    if events:
        event_rows = "".join(
            f"""
<tr>
  <td>{badge(event["new_state_label"], event["new_state_badge"])}</td>
  <td>{esc(event["actor"])}</td>
  <td>{esc(event["detail"] or "")}</td>
  <td>{esc(event["created_at"])}</td>
</tr>"""
            for event in events
        )

        events_html = f"""
<section class="card">
  <div class="card-head"><h2>Lifecycle events</h2></div>
  <p class="muted">Append-only ledger; entries are never edited or removed.</p>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr><th>Event</th><th>Actor</th><th>Detail</th><th>When</th></tr></thead>
    <tbody>{event_rows}</tbody>
  </table>
  </div>
</section>
"""

    continuity_html = ""

    if continuity:
        continuity_rows = "".join(
            f"""
<tr>
  <td>#{entry["id"]}</td>
  <td>{esc(entry["source_observation_id"])}</td>
  <td>{esc(entry["result_observation_id"])}</td>
  <td>{esc(entry["authority"])}</td>
  <td>{esc(entry["created_at"])}</td>
</tr>"""
            for entry in continuity
        )

        continuity_html = f"""
<section class="card">
  <div class="card-head"><h2>Execution-authorised identity continuity</h2></div>
  <p class="muted">
    The resulting filesystem observation keeps the SAME media
    identity; the original observation remains immutable history.
    This continuity is established only by this authorised execution,
    never by normal scanning or duplicate detection.
  </p>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr><th>Continuity</th><th>Source observation</th>
      <th>Result observation</th><th>Authority</th><th>When</th></tr></thead>
    <tbody>{continuity_rows}</tbody>
  </table>
  </div>
</section>
"""

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Organisation execution #{execution["id"]}</h2>
    {badge(execution["state_label"], execution["state_badge"])}
  </div>
  {progress_html}
  {error_html}
  {facts(fact_items)}
  {action_html}
</section>
{events_html}
{continuity_html}
"""

    return layout(
        f"Organisation execution #{execution['id']}",
        "organisation",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


# ---------------------------------------------------------
# Sprint 15 integrations settings, profiles, What-If,
# reconciliation, preflight and scope views
# ---------------------------------------------------------


def folder_browser_block(
    target_id, uid, *, append=False, show_toggle=True,
    show_files=False
):
    """
    Reusable read-only folder browser wired by the generic
    JS below. Browse shows current location, folders, Up,
    Select this folder and Close; selection fills (or, for
    multi-value fields, appends a line to) the target
    input without requiring /api/fs/browse knowledge.
    One server endpoint serves all instances; no second
    filesystem service is introduced. Sections whose rows
    already carry their own Browse buttons pass
    show_toggle=False so each row has exactly one clear
    Browse action retargeting this shared browser. With
    show_files=True a second list offers the video/media
    files inside the current folder for file pickers
    such as Quick Find.
    """

    mode = "append" if append else "set"
    files = "1" if show_files else ""

    file_block = ""
    if show_files:
        file_block = (
            '\n  <p class="muted folder-files-label">'
            "Files in this folder</p>\n"
            f'  <ul class="file-list" id="file-list-{uid}">'
            "</ul>"
        )

    toggle = (
        f"""
<div class="browser-row">
  <button type="button" class="btn small ghost js-browse-toggle"
          data-browser="{uid}" aria-expanded="false"
          aria-controls="folder-browser-{uid}">
    Browse...
  </button>
</div>
"""
        if show_toggle
        else ""
    )

    return f"""
{toggle}
<div class="folder-browser" id="folder-browser-{uid}" hidden
     data-target="{target_id}" data-mode="{mode}"
     data-files="{files}">
  <div class="folder-browser-head">
    <span class="folder-current"
          id="folder-current-{uid}">/</span>
    <button type="button" class="btn small ghost js-folder-up"
            data-browser="{uid}">Up one level</button>
  </div>
  <ul class="folder-list" id="folder-list-{uid}"></ul>
  {file_block}
  <div class="folder-browser-foot">
    <span class="folder-error" id="folder-error-{uid}"
          role="status"></span>
    <button type="button" class="btn small js-folder-select"
            data-browser="{uid}">Use this folder</button>
    <button type="button" class="btn small ghost js-folder-close"
            data-browser="{uid}">Close</button>
  </div>
</div>
"""


def _form_error_panel(data):
    """
    In-context error panel for the current form. Returns
    an empty string when the data carries no form error,
    so pages render unchanged on success.
    """

    form_error = data.get("form_error") or {}

    if not form_error:
        return ""

    return f"""
<div class="error-panel" role="alert">
  <h3>{esc(form_error.get("title") or "Something needs attention")}</h3>
  <p>{esc(form_error.get("message") or "")}</p>
  <p class="muted">{esc(form_error.get("guidance") or "")}</p>
</div>
"""


def _profile_options(profiles, selected=None):
    options = [
        '<option value="">Default profile</option>'
    ]

    for profile in profiles or []:
        current = (
            ' selected'
            if selected is not None
            and str(profile.get("id")) == str(selected)
            else ''
        )

        options.append(
            f'<option value="{profile.get("id")}"{current}>'
            f'{esc(profile.get("name"))}'
            f'</option>'
        )

    return "".join(options)


def _provider_mapping_section(provider, data):
    """
    Explicit provider-root to local-root mappings for one
    provider card. Deterministic, reviewable association
    across container/host namespaces; rendered from the
    same provider view as everything else on the card.
    """

    name = provider.get("provider")
    mappings = provider.get("path_mappings") or []

    saved = data.get("mapping_saved") or {}
    removed = data.get("mapping_removed") or {}
    mapping_input = data.get("mapping_input") or {}

    feedback = ""

    if saved.get("provider") == name and saved.get(
        "provider_root"
    ):
        feedback += f"""
<div class="success-panel" role="status">
  <h3>Path mapping saved</h3>
  <p>{esc(saved.get("provider_root"))} maps onto
  {esc(saved.get("local_root"))} for {esc(name)}.</p>
</div>
"""

    if removed and removed.get("provider") == name:
        if removed.get("removed"):
            feedback += """
<div class="success-panel" role="status">
  <h3>Path mapping removed</h3>
  <p>The mapping no longer applies to future syncs.</p>
</div>
"""
        else:
            feedback += """
<div class="error-panel" role="alert">
  <h3>Path mapping not removed</h3>
  <p>The mapping was already gone.</p>
</div>
"""

    if mappings:
        rows = []

        for mapping in mappings:
            rows.append(f"""
<tr>
  <td>{esc(mapping.get("provider_root"))}</td>
  <td>{esc(mapping.get("local_root"))}</td>
  <td>
    <form method="post"
          action="/organisation/integrations/mappings/remove"
          class="inline-form">
      <input type="hidden" name="provider"
             value="{esc(name)}">
      <input type="hidden" name="mapping_id"
             value="{esc(mapping.get("id"))}">
      <button class="btn small ghost" type="submit">
        Remove
      </button>
    </form>
  </td>
</tr>""")

        table = f"""
<div class="table-wrap">
<table class="data-table">
  <thead><tr>
    <th>Provider root</th><th>Local root</th><th></th>
  </tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>
</div>
"""
    else:
        table = (
            '<p class="muted">No path mappings yet. '
            "Without a mapping, provider paths that live "
            "under a different root than local files stay "
            "unmatched rather than guessed.</p>"
        )

    if mapping_input.get("provider") in (name, ""):
        prefill_provider_root = mapping_input.get(
            "provider_root", ""
        )
        prefill_local_root = mapping_input.get(
            "local_root", ""
        )
    else:
        prefill_provider_root = ""
        prefill_local_root = ""

    local_input_id = f"mapping-local-root-{esc(name)}"

    return f"""
<h3>Library path mappings</h3>
{feedback}
{table}
<form method="post"
      action="/organisation/integrations/mappings"
      class="org-form">
  <input type="hidden" name="provider" value="{esc(name)}">
  <label>Provider root
    <input type="text" name="provider_root"
           value="{esc(prefill_provider_root)}"
           placeholder="/Movies">
  </label>
  <label>Local root
    <input type="text" name="local_root"
           id="{local_input_id}"
           value="{esc(prefill_local_root)}"
           placeholder="/mnt/media/Movies">
  </label>
  {folder_browser_block(local_input_id, f"mapping-{esc(name)}")}
  <div class="actions-row">
    <button class="btn small" type="submit">
      Save mapping
    </button>
  </div>
</form>
<p class="field-hint">
  A provider root may map onto several local roots (one
  row per drive). A provider path counts as matched only
  when the mapped candidates identify exactly one local
  file; several hits stay needs-review. Jellyfin uses
  the same container roots (for example /Movies, /TV),
  so it takes the same mappings.
</p>
"""


def _jellyfin_user_section(provider, data):
    """Explicit Jellyfin library-user picker (jellyfin only)."""

    if provider.get("provider") != "jellyfin":
        return ""

    current = provider.get("jellyfin_user_id") or ""
    browser = data.get("jellyfin_users") or {}
    users = browser.get("users") or []
    browser_error = browser.get("error")
    saved = data.get("user_saved") or {}

    feedback = ""

    if saved.get("provider") == "jellyfin":
        feedback += """
<div class="success-panel" role="status">
  <h3>Library user saved</h3>
  <p>Future Jellyfin syncs read libraries as that user.</p>
</div>
"""

    if browser_error:
        feedback += f"""
<div class="error-panel" role="alert">
  <h3>Could not load Jellyfin users</h3>
  <p>{esc(browser_error)}</p>
  <p class="muted">Check the base URL and API key, save,
  then try again.</p>
</div>
"""

    picker = ""

    if users and not browser_error:
        options = []

        for user in users:
            options.append(
                f'<option value="{esc(user.get("id"))}">'
                f'{esc(user.get("name") or user.get("id"))}'
                "</option>"
            )

        picker = f"""
<form method="post"
      action="/organisation/integrations/jellyfin/user"
      class="org-form">
  <label>Jellyfin user
    <select name="jellyfin_user_id">
      {''.join(options)}
    </select>
  </label>
  <div class="actions-row">
    <button class="btn small" type="submit">
      Save library user
    </button>
  </div>
</form>
"""

    current_line = (
        f'<p>Current library user: '
        f'<code>{esc(current)}</code></p>'
        if current
        else '<p class="muted">No library user set. '
        "A bare API key carries no user context "
        "(/Users/Me answers 400), so set one before "
        "syncing a multi-user server.</p>"
    )

    return f"""
<h3>Jellyfin library user</h3>
{feedback}
{current_line}
<form method="post"
      action="/organisation/integrations/jellyfin/users"
      class="inline-form">
  <div class="actions-row">
    <button class="btn small ghost" type="submit">
      Load users
    </button>
    <span class="muted">
      Read-only lookup of the server user list.
    </span>
  </div>
</form>
{picker}
"""


def _provider_tags_section(provider, data):
    """
    Live provider tag inspection (Radarr/Sonarr). Tag ids
    resolve to labels through the live tag map; Jellyfin
    tags are inline strings, so no lookup is offered.
    """

    name = provider.get("provider")

    if name not in ("radarr", "sonarr"):
        return ""

    browser = data.get("tag_labels") or {}
    feedback = ""

    inspected = ""

    if browser.get("provider") == name:
        if browser.get("error"):
            feedback += f"""
<div class="error-panel" role="alert">
  <h3>Could not load provider tags</h3>
  <p>{esc(browser.get("error"))}</p>
  <p class="muted">Check the base URL and API key, save,
  then try again.</p>
</div>
"""
        else:
            labels = browser.get("labels") or []

            if labels:
                items = "".join(
                    f"<li><code>{esc(item[0])}</code> "
                    f"{esc(item[1])}</li>"
                    for item in labels
                )
                inspected = f"<ul>{items}</ul>"
            else:
                inspected = (
                    '<p class="muted">No tags defined on '
                    "this provider.</p>"
                )

    return f"""
<h3>Provider tags</h3>
{feedback}
<form method="post"
      action="/organisation/integrations/{esc(name)}/tags"
      class="inline-form">
  <div class="actions-row">
    <button class="btn small ghost" type="submit">
      Load provider tags
    </button>
    <span class="muted">
      Read-only. Use the labels in profile tag mappings.
    </span>
  </div>
</form>
{inspected}
"""


def render_organisation_integrations(data):
    providers = data.get("providers") or []

    updated_name = (data.get("updated") or {}).get("provider")
    tested = data.get("result") or {}
    tested_name = tested.get("provider")
    removed_name = (data.get("removed") or {}).get("provider")
    sync_started = data.get("sync_started") or {}
    sync_started_name = sync_started.get("provider")
    sync_denied = data.get("sync_denied") or {}

    def _sync_summary_line(summary):
        if not summary:
            return (
                '<span class="muted">Last sync: never</span>'
            )

        state = summary.get("state") or "unknown"
        finished = summary.get("finished_at") or "in progress"

        return (
            f'<span class="muted">Last sync: '
            f'{esc(str(finished))} · {esc(state)} · '
            f'{esc(summary.get("inspected", 0))} inspected, '
            f'{esc(summary.get("matched", 0))} matched, '
            f'{esc(summary.get("updated", 0))} updated, '
            f'{esc(summary.get("unchanged", 0))} unchanged, '
            f'{esc(summary.get("unmatched", 0))} unmatched, '
            f'{esc(summary.get("needs_review", 0))} need '
            f'review, '
            f'{esc(summary.get("error_count", 0))} errors'
            f'</span>'
        )

    def _sync_last_table(providers):
        rows = []

        for provider in providers:
            summary = provider.get("last_sync") or {}

            rows.append(f"""
<tr>
  <td>{esc(provider.get("provider"))}</td>
  <td>{esc(str(summary.get("finished_at") or "-"))}</td>
  <td>{esc(summary.get("state") or "never")}</td>
  <td>{esc(summary.get("inspected", 0))}</td>
  <td>{esc(summary.get("matched", 0))}</td>
  <td>{esc(summary.get("updated", 0))}</td>
  <td>{esc(summary.get("unchanged", 0))}</td>
  <td>{esc(summary.get("unmatched", 0))}</td>
  <td>{esc(summary.get("needs_review", 0))}</td>
  <td>{esc(summary.get("error_count", 0))}</td>
</tr>""")

        return f"""
<div class="table-wrap">
<table class="data-table" id="sync-last-table">
  <thead><tr>
    <th>Provider</th><th>Last sync</th><th>State</th>
    <th>Inspected</th><th>Matched</th><th>Updated</th>
    <th>Unchanged</th><th>Unmatched</th>
    <th>Review</th><th>Errors</th>
  </tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>
</div>
<div class="info-panel">
  <p>
    Unmatched items are not errors: they are provider
    records with no reliable NAMOA counterpart, often
    because provider paths live under a different mount
    or root than local files. Items matching more than
    one local file are held for review and never
    guessed. Matched items feed What-If, association,
    classification and planning automatically.
  </p>
</div>
"""

    sections = []

    for provider in providers:
        name = provider.get("provider")

        checked = (
            " checked" if provider.get("enabled") else ""
        )

        enabled_badge = (
            badge("Enabled", "current")
            if provider.get("enabled")
            else badge("Disabled", "unknown")
        )

        storage_mode = provider.get("storage_mode")
        credential_source = (
            provider.get("credential_source") or "unknown"
        )

        if storage_mode == "secure-os":
            storage_text = "Secure OS credential storage"
        elif storage_mode == "local-app":
            storage_text = (
                "Local application storage "
                "(private app directory, not an OS vault)"
            )
        elif storage_mode == "environment":
            storage_text = (
                "Environment override "
                "(advanced deployment option)"
            )
        else:
            storage_text = f"Source: {storage_mode or credential_source}"

        if provider.get("credential_present"):
            credential_badge = (
                f'<span class="badge current">credential stored</span> '
                f'<span class="muted">{esc(storage_text)}</span>'
            )
        else:
            credential_badge = (
                '<span class="badge stale">no credential</span> '
                '<span class="muted">enter a key below or set '
                'the environment variable</span>'
            )

        inline_result = ""

        if tested_name == name:
            if tested.get("ok"):
                inline_result = f"""
<div class="success-panel" role="status">
  <h3>{esc(name)}: connected successfully</h3>
  <p>{esc(tested.get("version") or "The provider answered.")}</p>
</div>
"""
            else:
                inline_result = f"""
<div class="error-panel" role="alert">
  <h3>{esc(name)}: connection failed</h3>
  <p>{esc(tested.get("error") or "unknown error")}</p>
  <p>Check the base URL and API key, save, then
  test again.</p>
</div>
"""
        elif updated_name == name:
            inline_result = f"""
<div class="success-panel" role="status">
  <h3>Settings saved</h3>
  <p>Configuration for {esc(name)} is stored.</p>
</div>
"""
        elif removed_name == name:
            inline_result = f"""
<div class="success-panel" role="status">
  <h3>Stored credential removed</h3>
  <p>The saved key for {esc(name)} is deleted.
  Configuration stays.</p>
</div>
"""
        elif sync_started_name == name or sync_started_name == "all":
            inline_result = f"""
<div class="info-panel" role="status">
  <h3>Metadata sync running</h3>
  <p>Progress appears in the Metadata sync section
  below. You can keep working; the final summary is
  kept when the sync finishes.</p>
</div>
"""

        if (
            sync_denied.get("provider") in (name, "all")
            and sync_denied.get("message")
        ):
            inline_result += f"""
<div class="error-panel" role="alert">
  <h3>{esc(sync_denied.get("title") or "Sync not started")}</h3>
  <p>{esc(sync_denied.get("message"))}</p>
</div>
"""

        is_open = (
            " open"
            if name
            in (
                updated_name,
                tested_name,
                removed_name,
                sync_started_name,
                sync_denied.get("provider"),
            )
            else ""
        )

        field_id = f"api-key-{esc(name)}"

        sections.append(f"""
<details class="provider"{is_open}>
  <summary>{esc(name)}
    <span class="provider-badges">
      {enabled_badge} {credential_badge}
    </span>
  </summary>
  <div class="provider-body">
  {inline_result}
  <p>{_sync_summary_line(provider.get("last_sync"))}</p>
  <form method="post" action="/organisation/integrations/save"
        class="org-form">
    <input type="hidden" name="provider" value="{esc(name)}">
    <label>
      <input type="checkbox" name="enabled" value="on"{checked}>
      Enabled
    </label>
    <label>Base URL
      <input type="text" name="base_url"
             value="{esc(provider.get("base_url") or "")}"
             placeholder="https://example:8096">
    </label>
    <p class="field-hint">
      Enter the full address including http:// or https://.
      A missing scheme is saved as http:// automatically.
    </p>
    <label>API key (leave blank to keep the stored value)
      <span class="input-with-toggle">
        <input type="password" name="api_key" value=""
               id="{field_id}" autocomplete="new-password">
        <button type="button" class="btn small ghost js-reveal"
                data-target="{field_id}" aria-pressed="false">Show</button>
      </span>
    </label>
    <p class="field-hint">
      Masked input. Show reveals only what you type here;
      a saved key is shown as stored, never rendered back.
    </p>
    <div class="actions-row">
      <button class="btn small" type="submit">Save settings</button>
      <button class="btn small ghost" type="submit"
              formaction="/organisation/integrations/{esc(name)}/test">
        Test connection
      </button>
    </div>
  </form>
  <form method="post"
        action="/organisation/integrations/{esc(name)}/sync"
        class="inline-form">
    <div class="actions-row">
      <button class="btn small ghost" type="submit">
        Sync metadata
      </button>
      <span class="muted">
        Explicit background run over this provider only.
      </span>
    </div>
  </form>
  {_provider_mapping_section(provider, data)}
  {_jellyfin_user_section(provider, data)}
  {_provider_tags_section(provider, data)}
  <form method="post"
        action="/organisation/integrations/{esc(name)}/remove-credential"
        class="destructive-block">
    <button class="btn small btn-danger" type="submit">
      Remove stored credential
    </button>
    <span class="muted">
      Destructive: deletes the saved key. Configuration
      stays; disabling is separate.
    </span>
  </form>
  <p class="muted">
    Credential values are never displayed. Saving without an
    API key keeps the stored value unchanged.
  </p>
  </div>
</details>
""")

    content = f"""
<section class="card">
  <div class="card-head"><h2>Provider integrations</h2></div>
  <p class="muted">Configure read-only metadata providers. Nothing syncs without your explicit action. Open a provider to configure it.</p>
  {_form_error_panel(data)}
</section>
<section class="card" id="metadata-sync">
  <div class="card-head">
    <h2>Metadata sync</h2>
    <form method="post"
          action="/organisation/integrations/sync-all"
          class="inline-form">
      <button class="btn small" type="submit">
        Sync all providers
      </button>
    </form>
  </div>
  <div class="info-panel">
    <p>
      Sync reads each enabled provider library and stores
      fresh metadata observations for files NAMOA already
      knows. It never moves, renames, or deletes files.
      Large libraries sync in the background; progress
      appears below and the final summary is kept.
    </p>
  </div>
  <div id="sync-live"
       data-status-url="/api/organisation/integrations/sync-status"
       data-running="{'1' if sync_started_name else ''}">
  </div>
  {_sync_last_table(providers)}
</section>
{''.join(sections)}
"""

    return layout(
        "Organisation integrations",
        "organisation",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def _profile_page_head(*, breadcrumb, title, subtitle, back_href="", back_label=""):
    crumbs = " &gt; ".join(
        esc(part) for part in (breadcrumb or [])
    )
    back = (
        f'<p><a class="btn small ghost" href="{back_href}">'
        f"{esc(back_label)}</a></p>"
        if back_href
        else ""
    )
    return f"""
<div class="profile-page-head">
  <p class="breadcrumb">{crumbs}</p>
  <h2>{esc(title)}</h2>
  <p class="muted">{esc(subtitle)}</p>
  {back}
</div>
"""


def _profile_progress_state(entered):
    data = entered or {}

    name = str(data.get("name") or "").strip()

    sources = [
        row if isinstance(row, str) else str(
            (row or {}).get("path") or ""
        )
        for row in (data.get("source_rows") or [])
    ]
    sources = [path.strip() for path in sources if path.strip()]
    sources_ok = any(path.startswith("/") for path in sources)

    dests = []
    for row in (data.get("root_rows") or []):
        if isinstance(row, dict):
            path = str(row.get("path") or "").strip()
        else:
            path = str(row or "").strip()
        if path:
            dests.append(path)
    dests_ok = any(path.startswith("/") for path in dests)

    cats = [
        row for row in (data.get("cat_rows") or [])
        if isinstance(row, dict)
        and str(row.get("name") or "").strip()
        and str(row.get("folder") or "").strip()
    ]
    cats_ok = len(cats) > 0

    movie = str(data.get("movie_template") or "").strip()
    tv = str(data.get("tv_template") or "").strip()
    folders_ok = bool(movie and tv and "{root" in movie and "{root" in tv)

    policy = data.get("filename_policy") or {}
    mode = policy.get("mode", "keep") if isinstance(policy, dict) else "keep"
    naming_ok = mode in ("keep", "clean", "extended", "template")

    return [
        ("name", "Profile name", bool(name)),
        ("sources", "Library locations", bool(sources_ok)),
        ("destinations", "Destinations", bool(dests_ok)),
        ("categories", "Categories and rules", bool(cats_ok)),
        ("folders", "Folder templates", bool(folders_ok)),
        ("naming", "Filename policy", bool(naming_ok)),
    ]


def _profile_progress_panel(entered):
    items = _profile_progress_state(entered)
    done = sum(1 for _, _, ok in items if ok)
    total = len(items)
    rows = "".join(
        f'<li data-progress-item="{key}" class="{"done" if ok else "todo"}">'
        f'<span aria-hidden="true">{"✓" if ok else "○"}</span> '
        f"{esc(label)}</li>"
        for key, label, ok in items
    )
    return f"""
<div class="card progress-card" id="profile-progress" role="status" aria-label="Profile setup progress">
  <div class="card-head">

    <h2>Profile setup progress</h2>
  </div>
  <p class="muted">Updates as you edit. Derived from the same fields that decide whether the profile can be saved.</p>
  <ul class="progress-list">{rows}</ul>
  <p class="progress-count" data-progress-count>{done} of {total} complete</p>
</div>
"""


def _root_row_html(index, row):
    """One Library Locations row: path, tag, Browse, Remove."""

    row_id = "root-first" if index == 0 else f"root-{index}"
    hint = (
        "{root}" if index == 0 else "{root" + str(index + 1) + "}"
    )

    return f"""
<div class="repeat-row" data-repeat="root">
  <label>Root path
    <input type="text" name="root" value="{esc(row.get("path") or "")}"
           id="{row_id}"
           placeholder="/media/library">
  </label>
  <label>Root tag
    <input type="text" name="root_alias"
           class="js-root-alias"
           value="{esc(row.get("alias") or "")}"
           placeholder="{hint}">
  </label>
  <button type="button" class="btn small ghost js-row-browse"
          data-browser="profile-roots"
          data-input="{row_id}">
    Browse
  </button>
  <button type="button" class="btn small ghost js-row-remove"
          aria-label="Remove this root">Remove</button>
</div>"""


def _profile_editor_form(
    entered,
    *,
    action,
    name_field_html,
    submit_label,
    summary_html="",
    error_sections=(),
    include_save=True,
):
    """
    The full profile editor: sources, destinations with
    stable root tags, folder structure, file naming,
    categories, rating/collection/tag policy,
    naming/platform/collision. Shared by the create
    form and the saved-profile edit form so both edit
    exactly the same fields through the same single
    save path. No second profile system. Sections
    named in error_sections render highlighted so the
    operator sees where to fix input.
    """

    error_keys = set(error_sections or [])

    raw_root_values = entered.get("root_rows") or [""]

    def _value(key, default=""):
        return esc(entered.get(key, default))

    def _selected(key, option):
        current = entered.get(key, "")

        if not current and option in ("posix", "review"):
            return " selected"

        return (
            " selected" if current == option else ""
        )

    raw_root_values = entered.get("root_rows") or [""]

    root_values = [
        value
        if isinstance(value, dict)
        else {"path": value, "alias": ""}
        for value in raw_root_values
    ]

    raw_source_values = entered.get("source_rows") or [""]

    source_values = [
        value
        if isinstance(value, str)
        else str(value.get("path") or "")
        for value in raw_source_values
    ]

    source_rows_html = "".join(
        f"""
<div class="repeat-row" data-repeat="source">
  <label>Source path
    <input type="text" name="source" value="{esc(value)}"
           id="{"source-first" if index == 0 else f"source-{index}"}"
           placeholder="/mnt/usb/Incoming">
  </label>
  <button type="button" class="btn small ghost js-row-browse"
          data-browser="profile-sources"
          data-input="{"source-first" if index == 0 else f"source-{index}"}">
    Browse
  </button>
  <button type="button" class="btn small ghost js-row-remove"
          aria-label="Remove this source">Remove</button>
</div>"""
        for index, value in enumerate(source_values)
    )

    root_tokens = entered.get("root_tokens") or ["{root}"]

    root_rows_html = "".join(
        _root_row_html(index, row)
        for index, row in enumerate(root_values)
    )

    root_token_items = "".join(
        f"<li><code>{esc(token)}</code></li>"
        for token in root_tokens
    )

    root_help_html = f"""
<div class="info-panel">
  <p>
    Library roots can point to different destinations.
    Each root has a template tag so you can choose the
    destination explicitly. Use the appropriate root
    tag in Movie, TV or Category patterns.
  </p>
  <ul>{root_token_items}</ul>
  <p class="muted">
    Each library root has its own template token. Use
    that token in a pattern to choose which root
    receives the resulting structure: for example a
    Movie pattern starting with <code>{{root}}</code>
    stays on the first root while a TV pattern
    starting with a second tag lands on the second
    root.
  </p>
</div>
"""

    cat_values = entered.get("cat_rows") or [
        {"name": "", "folder": ""}
    ]

    cat_rows_html = "".join(
        f"""
<div class="repeat-row" data-repeat="cat">
  <label>Category
    <input type="text" name="cat_name"
           value="{esc(row.get("name") or "")}"
           placeholder="Kids">
  </label>
  <label>Folder
    <input type="text" name="cat_folder"
           value="{esc(row.get("folder") or "")}"
           placeholder="Movies-KIDS">
  </label>
  <button type="button" class="btn small ghost js-row-remove"
          aria-label="Remove this category">Remove</button>
</div>"""
        for row in cat_values
    )

    map_values = entered.get("map_rows") or [
        {
            "provider": "",
            "labels": "",
            "category": "",
            "priority": "100",
            "override": "",
        }
    ]

    def _map_provider_options(current):
        options = []

        for value, label in (
            ("", "Any provider"),
            ("jellyfin", "Jellyfin"),
            ("radarr", "Radarr"),
            ("sonarr", "Sonarr"),
        ):
            selected = (
                " selected"
                if (current or "") == value else ""
            )

            options.append(
                f'<option value="{value}"{selected}>'
                f"{label}</option>"
            )

        return "".join(options)

    map_rows_html = "".join(
        f"""
<div class="repeat-row" data-repeat="map">
  <label>Provider
    <select name="map_provider">
      {_map_provider_options(row.get("provider"))}
    </select>
  </label>
  <label>Tags (comma-separated)
    <input type="text" name="map_labels"
           value="{esc(row.get("labels") or "")}"
           placeholder="Kids, Anime">
  </label>
  <label>Target category
    <input type="text" name="map_category"
           value="{esc(row.get("category") or "")}"
           placeholder="Kids Anime">
  </label>
  <label>Priority
    <input type="text" name="map_priority"
           value="{esc(row.get("priority") or "100")}"
           inputmode="numeric">
  </label>
  <label>Override rating/collection policy
    <select name="map_override">
      <option value=""{" selected" if not row.get("override") else ""}>No (default)</option>
      <option value="yes"{" selected" if row.get("override") else ""}>Yes, outrank rating/collection</option>
    </select>
  </label>
  <button type="button" class="btn small ghost js-row-remove"
          aria-label="Remove this mapping">Remove</button>
</div>"""
        for row in map_values
    )

    rule_values = entered.get("rule_rows") or [
        {
            "id": "",
            "media_kind": "any",
            "certification": "",
            "collection": "",
            "genres": "",
            "tags": "",
            "provider": "",
            "category": "",
            "fallback": "",
        }
    ]

    def _rule_kind_options(current):
        options = []

        for value, label in (
            ("movie", "Movie"),
            ("tv", "TV"),
            ("any", "Any kind"),
        ):
            selected = (
                " selected"
                if (current or "any") == value else ""
            )

            options.append(
                f'<option value="{value}"{selected}>'
                f"{label}</option>"
            )

        return "".join(options)

    cat_names = [
        str(row.get("name") or "")
        for row in (
            entered.get("cat_rows") or [{"name": "", "folder": ""}]
        )
        if isinstance(row, dict)
    ]

    def _rule_target_options(current):
        options = []

        for name in cat_names:
            if not name:
                continue

            selected = (
                " selected"
                if (current or "") == name else ""
            )

            options.append(
                f'<option value="{esc(name)}"{selected}>'
                f"{esc(name)}</option>"
            )

        if current and current not in cat_names:
            options.append(
                f'<option value="{esc(current)}" selected>'
                f"{esc(current)} (removed)</option>"
            )

        return "".join(options)

    rule_rows_html = "".join(
        f"""
<div class="repeat-row rule-row" data-repeat="rule">
  <span class="rule-order" aria-hidden="true"></span>
  <input type="hidden" name="rule_id"
         value="{esc(row.get("id") or "")}">
  <input type="hidden" name="rule_fallback"
         value="{esc(row.get("fallback") or "")}">
  <label>Media type
    <select name="rule_kind" class="js-rule-kind">
      {_rule_kind_options(row.get("media_kind"))}
    </select>
  </label>
  <label>Rating
    <input type="text" name="rule_cert"
           value="{esc(row.get("certification") or "")}"
           placeholder="Any rating">
  </label>
  <label>Collection
    <input type="text" name="rule_collection"
           value="{esc(row.get("collection") or "")}"
           placeholder="Any collection">
  </label>
  <label>Genres
    <input type="text" name="rule_genres"
           value="{esc(row.get("genres") or "")}"
           placeholder="Any genre">
  </label>
  <label>Tags
    <input type="text" name="rule_tags"
           value="{esc(row.get("tags") or "")}"
           placeholder="Any tags">
  </label>
  <label>Target category
    <select name="rule_category" class="js-rule-target">
      {_rule_target_options(row.get("category"))}
    </select>
  </label>
  <span class="rule-controls">
    <button type="button" class="btn small ghost js-row-up"
            aria-label="Move this rule up">Up</button>
    <button type="button" class="btn small ghost js-row-down"
            aria-label="Move this rule down">Down</button>
    <button type="button" class="btn small ghost js-row-remove"
            aria-label="Remove this rule">Remove</button>
  </span>
</div>"""
        for row in rule_values
        if isinstance(row, dict)
    )

    sig_values = entered.get("sig_rows") or [
        {
            "category": "",
            "genres": "",
            "collections": "",
            "networks": "",
            "provider_flags": "",
        }
    ]

    sig_rows_html = "".join(
        f"""
<div class="repeat-row" data-repeat="sig">
  <label>Category
    <input type="text" name="sig_category"
           value="{esc(row.get("category") or "")}"
           placeholder="Kids">
  </label>
  <label>Genres
    <input type="text" name="sig_genres"
           value="{esc(row.get("genres") or "")}"
           placeholder="Animation, Family">
  </label>
  <label>Collections
    <input type="text" name="sig_collections"
           value="{esc(row.get("collections") or "")}"
           placeholder="Kids Collection">
  </label>
  <label>Networks / studios
    <input type="text" name="sig_networks"
           value="{esc(row.get("networks") or "")}"
           placeholder="Cartoon Network">
  </label>
  <label>Provider flags
    <input type="text" name="sig_provider_flags"
           value="{esc(row.get("provider_flags") or "")}"
           placeholder="kids">
  </label>
  <button type="button" class="btn small ghost js-row-remove"
          aria-label="Remove these signals">Remove</button>
</div>"""
        for row in sig_values
        if isinstance(row, dict)
    )

    cert_values = entered.get("cert_rows") or [
        {"certification": "", "media_kind": "any",
         "category": ""}
    ]

    def _cert_kind_options(current):
        options = []

        for value, label in (
            ("movie", "Movie"),
            ("tv", "TV"),
            ("any", "Any kind"),
        ):
            selected = (
                " selected"
                if (current or "any") == value else ""
            )

            options.append(
                f'<option value="{value}"{selected}>'
                f"{label}</option>"
            )

        return "".join(options)

    cert_rows_html = "".join(
        f"""
<div class="repeat-row" data-repeat="cert">
  <label>Rating / certification
    <input type="text" name="cert_cert"
           value="{esc(row.get("certification") or "")}"
           placeholder="G">
  </label>
  <label>Applies to
    <select name="cert_kind">
      {_cert_kind_options(row.get("media_kind"))}
    </select>
  </label>
  <label>Target category
    <input type="text" name="cert_category"
           value="{esc(row.get("category") or "")}"
           placeholder="Movies Kids">
  </label>
  <button type="button" class="btn small ghost js-row-remove"
          aria-label="Remove this rating rule">Remove</button>
</div>"""
        for row in cert_values
        if isinstance(row, dict)
    )

    coll_values = entered.get("coll_rows") or [
        {"collection": "", "category": ""}
    ]

    coll_rows_html = "".join(
        f"""
<div class="repeat-row" data-repeat="coll">
  <label>Collection
    <input type="text" name="coll_collection"
           value="{esc(row.get("collection") or "")}"
           placeholder="Kids Classics">
  </label>
  <label>Target category
    <input type="text" name="coll_category"
           value="{esc(row.get("category") or "")}"
           placeholder="Movies Kids">
  </label>
  <button type="button" class="btn small ghost js-row-remove"
          aria-label="Remove this collection rule">Remove</button>
</div>"""
        for row in coll_values
        if isinstance(row, dict)
    )

    def _cls(key):
        return (
            " section-error" if key in error_keys else ""
        )

    profile_cls = _cls("profile")
    sources_cls = _cls("sources")
    destinations_cls = _cls("destinations")
    structure_cls = _cls("structure")
    naming_file_cls = _cls("naming-file")
    categories_cls = _cls("categories")
    rules_cls = _cls("rules")
    ratings_cls = _cls("ratings")
    collections_cls = _cls("collections")
    tags_cls = _cls("tags")
    advanced_cls = _cls("advanced")

    save_grid_html = ""
    if include_save:
        save_grid_html = f"""
    <div class="profile-actions">
      <button class="btn small" type="submit">{submit_label}</button>
    </div>
    """

    form_inner = f"""
    <div class="form-section section-card{profile_cls}">
      <div class="section-head">
        <div>
          <h3>Profile details</h3>
          <p class="muted section-sub">What profile am I configuring. Names stay unique and support normal punctuation.</p>
        </div>
      </div>
      {name_field_html}
      <input type="hidden" name="origin_preset"
             value="{esc(entered.get("origin_preset") or "")}">
      <div class="form-grid">
        <div>
          <label>Platform
            <select name="platform">
              <option value="posix"{_selected("platform", "posix")}>posix</option>
              <option value="windows"{_selected("platform", "windows")}>windows</option>
            </select>
          </label>
        </div>
        <div>
          <label>Naming separator
            <input type="text" name="naming_separator"
                   value="{_value("naming_separator", " ")}">
          </label>
        </div>
        <div>
          <label>Collision policy
            <select name="collision_policy">
              <option value="review"{_selected("collision_policy", "review")}>review: ask before overwriting</option>
              <option value="suffix"{_selected("collision_policy", "suffix")}>suffix: keep both with a suffix</option>
            </select>
          </label>
        </div>
      </div>
      <div class="info-panel">
        <p>
          Platform selects which filesystem rules proposed
          paths are validated against. Match it to the
          machine holding the library: posix for Linux or
          macOS, windows for Windows shares. Naming
          separator joins multi-part names when rendering
          destinations; a space is the usual choice.
          Collision policy decides review versus automatic
          suffixing when a destination already exists.
        </p>
      </div>
    </div>
    <div class="form-section section-card{sources_cls}">
      <div class="section-head">
        <div>
          <h3>1. Library Sources</h3>
          <p class="muted section-sub">Where NAMOA looks. <span data-count-sources></span></p>
        </div>
      </div>
      <div class="info-panel">
        <p>
          <strong>Source</strong>
          <span class="muted">Where NAMOA is allowed to look for
          files.</span>
        </p>
      </div>
      <div id="source-rows">
        {source_rows_html}
      </div>
      <div class="actions-row">
        <button type="button" class="btn small ghost"
                id="source-add">Add source</button>
      </div>
      {folder_browser_block("source-first", "profile-sources", append=False, show_toggle=False)}
    </div>
    <div class="form-section section-card{destinations_cls}">
      <div class="section-head">
        <div>
          <h3>2. Organisation Destinations</h3>
          <p class="muted section-sub">Where NAMOA puts things. <span data-count-dests></span></p>
        </div>
      </div>
      <div class="info-panel">
        <p>
          <strong>Destination</strong>
          <span class="muted">Where organised content will
          live.</span>
        </p>
      </div>
      <p class="field-hint">
        Absolute paths to your library roots. Browse to
        pick a folder instead of typing it. Each root
        keeps its own template tag (first root
        <code>{{root}}</code>, then
        <code>{{root2}}</code>,
        <code>{{root3}}</code>, and so on) unless you
        edit it; removing or reordering roots never
        renumbers the tags that remain.
      </p>
      {root_help_html}
      <div id="root-rows">
        {root_rows_html}
      </div>
      <div class="actions-row">
        <button type="button" class="btn small ghost"
                id="root-add">Add root</button>
        <button type="button" class="btn small ghost"
                id="root-tags-generate">Generate Library Root Tags</button>
      </div>
      {folder_browser_block("root-first", "profile-roots", append=False, show_toggle=False)}
    </div>
    <div class="form-section section-card{categories_cls}">
      <div class="section-head">
        <div>
          <h3>3. Categories and Metadata</h3>
          <p class="muted section-sub">How NAMOA classifies. <span data-count-cats></span> <span data-count-rules></span></p>
        </div>
      </div>
      <div class="info-panel">
        <p>
          <strong>Category</strong>
          <span class="muted">Which logical organisation group a file
          belongs to.</span>
        </p>
        <p>
          <strong>Folder</strong>
          <span class="muted">The actual destination directory used for
          that category.</span>
        </p>
        <p class="muted">
          Categories describe which organisation
          group a file belongs to. The folder is
          the actual destination directory used
          for that category.
        </p>
      </div>
      <h4>Category folders</h4>
      <p class="field-hint">
        Which folder each category lives in, for
        example Movies Kids uses the Movies-KIDS
        folder.
      </p>
      <div id="cat-rows">
        {cat_rows_html}
      </div>
      <div class="actions-row">
        <button type="button" class="btn small ghost"
                id="cat-add">Add category</button>
      </div>
      <h4>Organisation Rules</h4>
      <div class="info-panel">
        <p>
          Rules decide which category applies.
          Choose from the categories configured
          above. Rules are checked from top to
          bottom. The first matching rule
          determines the destination. The final
          Movie and TV rules provide the normal
          destination when nothing more specific
          matches.
        </p>
        <p class="muted">
          Each row matches only when every
          condition holds. Blank Rating,
          Collection, Genre, or Tags means Any:
          tags are optional, and a rule without
          tags is valid.
        </p>
      </div>
      <div id="rule-rows" class="rule-block{rules_cls}">
        {rule_rows_html}
      </div>
      <div class="actions-row">
        <button type="button" class="btn small ghost"
                id="rule-add">Add rule</button>
      </div>
    </div>
    <div class="form-section section-card{structure_cls}">
      <div class="section-head">
        <div>
          <h3>4. Folder Structure</h3>
          <p class="muted section-sub">How folders are structured inside the destination.</p>
        </div>
      </div>
      <div class="info-panel">
        <p>
          <strong>Template</strong>
          <span class="muted">How files are structured within the
          selected destination.</span>
        </p>
      </div>
      <div class="info-panel">
        <p>
          Each pattern is rendered with the file metadata
          to decide the resulting folder structure.
          <code>{{root}}</code> is always one of your
          library roots above. Other placeholders name
          metadata fields; unknown placeholders fail
          closed to review instead of guessing.
        </p>
        <p>
          Movie: <code>{{root}}/{{Title}} ({{Year}})/</code>
          turns Example Movie (2024) into
          <code>Movies/Example Movie (2024)/</code>.
        </p>
        <p>
          TV: <code>{{root}}/{{Series}}/Season
          {{Season}}/</code> turns Example Show season
          01 into <code>TV/Example Show/Season
          01/</code>.
        </p>
        <p>
          Category: <code>{{root}}/{{Category}}/
          {{TitleOrSeries}}/</code> nests the title or
          series structure under its category folder.
        </p>
        <p>
          With several library roots, write the token of
          the root that should receive the structure:
          Movie <code>{{root}}/{{Title}}
          ({{Year}})/</code>, TV
          <code>{{root2}}/{{Series}}/Season
          {{Season}}/</code>, Category
          <code>{{root3}}/{{Category}}/
          {{TitleOrSeries}}/</code>. Only tags listed
          beside Library locations above are valid.
        </p>
      </div>
      <label>Movie template pattern
        <input type="text" name="movie_template"
               value="{_value("movie_template")}">
      </label>
      <label>TV template pattern
        <input type="text" name="tv_template"
               value="{_value("tv_template")}">
      </label>
      <label>Category template pattern
        <input type="text" name="category_template"
               value="{_value("category_template")}">
      </label>
    </div>
    <div class="form-section section-card{naming_file_cls}">
      <div class="section-head">
        <div>
          <h3>5. Filename Policy</h3>
          <p class="muted section-sub">How filenames are handled. Extensions are always preserved.</p>
        </div>
      </div>
      <div class="radio-stack">
        <p>
          <label>
            <input type="radio" name="filename_mode"
                   value="keep"{" checked" if (entered.get("filename_policy") or {}).get("mode", "keep") == "keep" else ""}>
            <strong>Keep existing filenames</strong>
          </label>
          <span class="muted">Keep the existing filename and only organise the file into the correct folder.</span>
        </p>
        <p>
          <label>
            <input type="radio" name="filename_mode"
                   value="clean"{" checked" if (entered.get("filename_policy") or {}).get("mode") == "clean" else ""}>
            <strong>Use clean media names</strong>
          </label>
          <span class="muted">Rename the file using the recognised movie or TV information.</span>
        </p>
        <p>
          <label>
            <input type="radio" name="filename_mode"
                   value="extended"{" checked" if (entered.get("filename_policy") or {}).get("mode") == "extended" else ""}>
            <strong>Use clean media names + extended naming</strong>
          </label>
          <span class="muted">Keep the clean media name and optionally append technical or release information that NAMOA can identify.</span>
        </p>
        <p class="muted">
          Example:
          <code>the.little.mermaid.1989.720p.web.h264-jff.mkv</code>
          stays byte-identical under Keep, becomes
          <code>The Little Mermaid (1989).mkv</code>
          under Clean, and TV seasons render as
          <code>Bluey - S01E02 - The Beach.mkv</code>.
          Without reliable metadata NAMOA keeps the
          existing filename instead of inventing a
          poor one. The container extension
          (<code>.mkv</code>) is always preserved.
        </p>
      </div>
      <div id="filename-extended-block">
        <p>
          <strong>Base:</strong> the canonical base
          name above (for the sample below:
          <code>{esc((entered.get("filename_example") or {}).get("base") or "")}</code>).
          Only this block expands the extended mode;
          the other modes ignore it.
        </p>
        <label>Extended naming (tokens and literal text)
          <input type="text" name="filename_extended"
                 id="filename-extended"
                 value="{esc((entered.get("filename_policy") or {}).get("pattern") or "")}"
                 placeholder="{{file[quality]}}.WEB-DL.{{file[codec]}}-HAX0R">
        </label>
        <label>Separator between base name and extended suffix
          <input type="text" name="filename_separator"
                 value="{esc((entered.get("filename_policy") or {}).get("separator") or " ")}"
                 placeholder=" ">
        </label>
        <div class="token-picker">
          <p class="muted">Insert a token
          (only tokens NAMOA can resolve are
          shown; <code>WEB-DL</code> and
          <code>-HAX0R</code> stay literal text):</p>
          <p><strong>Media:</strong>
            <button type="button" class="btn small ghost js-token" data-token="{{media[title]}}">Title</button>
            <button type="button" class="btn small ghost js-token" data-token="{{media[year]}}">Year</button>
            <button type="button" class="btn small ghost js-token" data-token="{{media[series]}}">Series</button>
            <button type="button" class="btn small ghost js-token" data-token="{{media[season]}}">Season</button>
            <button type="button" class="btn small ghost js-token" data-token="{{media[episode]}}">Episode</button>
            <button type="button" class="btn small ghost js-token" data-token="{{media[episode_title]}}">Episode Title</button>
          </p>
          <p><strong>File / Technical:</strong>
            <button type="button" class="btn small ghost js-token" data-token="{{file[quality]}}">Quality</button>
            <button type="button" class="btn small ghost js-token" data-token="{{file[resolution]}}">Resolution</button>
            <button type="button" class="btn small ghost js-token" data-token="{{file[bitrate]}}">Bitrate</button>
            <button type="button" class="btn small ghost js-token" data-token="{{file[codec]}}">Codec</button>
            <button type="button" class="btn small ghost js-token" data-token="{{file[audio]}}">Audio</button>
            <button type="button" class="btn small ghost js-token" data-token="{{file[source]}}">Source</button>
            <button type="button" class="btn small ghost js-token" data-token="{{file[hdr]}}">HDR</button>
            <button type="button" class="btn small ghost js-token" data-token="{{file[edition]}}">Edition</button>
          </p>
        </div>
        <div class="info-panel">
          <p><strong>Live example</strong> (sample
          source
          <code>{esc((entered.get("filename_example") or {}).get("source") or "")}</code>):</p>
          <p>Result:
          <code>{esc((entered.get("filename_example") or {}).get("result") or "")}</code></p>
          <p class="muted">Missing values are
          omitted, never invented
          {esc(", ".join("unavailable: " + t for t in ((entered.get("filename_example") or {}).get("missing") or [])) or "")}
          {esc((entered.get("filename_example") or {}).get("error") or "")}</p>
        </div>
        {('<div class="info-panel"><p><strong>Legacy custom pattern preserved:</strong> this profile uses an older custom filename template, kept verbatim below. Pick a mode above to replace it.</p><label>Legacy pattern<input type="text" name="filename_legacy_pattern" value="' + esc((entered.get("filename_policy") or {}).get("legacy_pattern") or "") + '"></label></div>') if (entered.get("filename_policy") or {}).get("mode") == "template" else ""}
      </div>
    </div>
    <details class="disclosure advanced-card">
      <summary>6. Advanced Options</summary>
      <p class="muted section-sub">Secondary policy. Safe to leave alone. Presets already work without changes here.</p>
      <div class="info-panel">
        <p>
          These lists extend the Organisation Rules
          above: they are checked after the explicit
          rules and before the fallback rules.
          The normal editor needs none of this.
          Presets already work.
        </p>
      </div>
    <div class="form-section{ratings_cls}">
      <h4>Rating / certification rules</h4>
      <div class="info-panel">
        <p>
          <strong>Rating rule</strong>
          <span class="muted">Which certification selects a
          category. Rating rows apply after the
          Organisation Rules above.</span>
        </p>
      </div>
      <p class="field-hint">
        Certification policy: Movie + G goes to Movies
        Kids, TV + G goes to Series Kids. Other ratings
        follow the rows below.
      </p>
      <div id="cert-rows">
        {cert_rows_html}
      </div>
      <div class="actions-row">
        <button type="button" class="btn small ghost"
                id="cert-add">Add rating rule</button>
      </div>
    </div>
    <div class="form-section{collections_cls}">
      <h4>Collection rules</h4>
      <div class="info-panel">
        <p>
          <strong>Collection rule</strong>
          <span class="muted">Which provider collection selects
          a category. Collection rows apply after the
          Organisation Rules above.</span>
        </p>
      </div>
      <div id="coll-rows">
        {coll_rows_html}
      </div>
      <div class="actions-row">
        <button type="button" class="btn small ghost"
                id="coll-add">Add collection rule</button>
      </div>
    </div>
    <div class="form-section{tags_cls}">
      <h4>Tag mappings</h4>
      <div class="info-panel">
        <p>
          <strong>Tag rule</strong>
          <span class="muted">Which provider metadata can select
          a more specific category.</span>
        </p>
      </div>
      <p class="field-hint">
        Provider tags decide the category: Anime goes to
        Anime, Kids + Anime goes to Kids Anime. The most
        specific matching rule wins first, then lower
        priority numbers, then rule ID. Rating and
        collection policy outrank ordinary tag rules;
        set "Override rating/collection policy" to Yes
        only for a deliberate Advanced rule that must
        win (for example Horror outranking a G rating).
      </p>
      <div id="map-rows">
        {map_rows_html}
      </div>
      <div class="actions-row">
        <button type="button" class="btn small ghost"
                id="map-add">Add mapping</button>
      </div>
      <details class="disclosure tech-panel">
        <summary>Advanced: raw JSON mappings</summary>
        <div class="info-panel">
          <p>
            Normal editing uses the structured rows
            above. Advanced JSON exists for bulk edits:
            it holds a list merged with the rows, using
            the same supported schema.
          </p>
          <p>
            Each entry needs an id, a labels list, a
            target category and a priority number.
            Provider scope is optional: omit it, or
            name jellyfin, radarr or sonarr to limit
            the mapping to one provider. Labels combine
            with AND semantics, so ["Kids", "Anime"]
            only matches files tagged with both. The
            most specific match wins first, then lower
            priority numbers, then mapping id; exact
            ties stay reviewable instead of guessing.
          </p>
          <p>
            Example:
            <code>[{{"id": "kids-anime", "labels":
            ["Kids", "Anime"], "category": "Kids Anime",
            "priority": 10}}]</code>
          </p>
        </div>
        <label>Tag mappings JSON (merged with the rows above)
          <textarea name="tag_mappings" rows="3"
                    placeholder='[{{"id": "m1", "labels": ["kids"], "category": "Kids", "priority": 10}}]'>{_value("tag_mappings")}</textarea>
        </label>
      </details>
    </div>
      <details class="disclosure tech-panel">
        <summary>Advanced: intelligent classification signals</summary>
        <div class="info-panel">
          <p>
            Deterministic metadata signals per category:
            a file joins a category when configured
            signals match its provider metadata. These
            guide classification; they never move files
            by themselves.
          </p>
        </div>
        <div id="sig-rows">
          {sig_rows_html}
        </div>
        <div class="actions-row">
          <button type="button" class="btn small ghost"
                  id="sig-add">Add signals</button>
        </div>
      </details>
      <details class="disclosure tech-panel">
        <summary>Advanced: provider priority</summary>
        <div class="info-panel">
          <p>
            When providers disagree about the same
            field (for example the title), the earlier
            provider wins and the other values stay as
            evidence. Tags always merge across
            providers. Default order:
            <code>radarr, sonarr, jellyfin</code>.
            Leave blank for the default.
          </p>
        </div>
        <label>Provider priority (comma-separated)
          <input type="text" name="provider_priority"
                 value="{esc(entered.get("provider_priority") or "")}"
                 placeholder="radarr, sonarr, jellyfin">
        </label>
      </details>
    </details>
    {save_grid_html}
        """

    return f"""
  <form method="post" action="{action}"
        class="org-form" id="profile-edit-form">
{form_inner}  </form>
"""
def _profile_summary_html(entered) -> str:
    """
    Concise pre-save summary (sources, destinations,
    movie/TV organisation, categories, tag rules) so
    the operator understands what they are saving
    without reading raw JSON. Pure presentation over
    the entered form state.
    """

    entered = entered or {}

    sources = [
        row if isinstance(row, str) else str(
            (row or {}).get("path") or ""
        )
        for row in (entered.get("source_rows") or [])
    ]
    sources = [path for path in sources if path]

    dests = []

    for row in (entered.get("root_rows") or []):
        if isinstance(row, dict):
            path = str(row.get("path") or "")
            alias = str(row.get("alias") or "")
        else:
            path, alias = str(row or ""), ""

        if path:
            dests.append(
                f"{path} {{{alias}}}" if alias else path
            )

    categories = []

    for row in (entered.get("cat_rows") or []):
        if not isinstance(row, dict):
            continue

        name = str(row.get("name") or "")
        folder = str(row.get("folder") or "")

        if name or folder:
            categories.append(f"{name} → {folder}")

    mappings = []

    for row in (entered.get("map_rows") or []):
        if not isinstance(row, dict):
            continue

        labels = str(row.get("labels") or "")
        category = str(row.get("category") or "")

        if labels or category:
            mappings.append(f"{labels} → {category}")

    rules = []

    for row in (entered.get("rule_rows") or []):
        if not isinstance(row, dict):
            continue

        bits = [
            {"movie": "Movie", "tv": "TV"}.get(
                str(row.get("media_kind") or "any").strip().casefold(),
                "Any kind",
            )
        ]

        for key in (
            "certification", "collection", "genres", "tags",
        ):
            value = str(row.get(key) or "").strip()

            if value:
                bits.append(value)

        category = str(row.get("category") or "").strip()

        if bits or category:
            text = " + ".join(bits)

            if category:
                text += f" → {category}"

            if str(row.get("fallback") or "").strip():
                text += " (fallback)"

            rules.append(text)

    certs = []

    for row in (entered.get("cert_rows") or []):
        if not isinstance(row, dict):
            continue

        cert = str(row.get("certification") or "")
        kind = str(row.get("media_kind") or "any")
        category = str(row.get("category") or "")

        if cert or category:
            certs.append(f"{cert}/{kind} → {category}")

    colls = []

    for row in (entered.get("coll_rows") or []):
        if not isinstance(row, dict):
            continue

        collection = str(row.get("collection") or "")
        category = str(row.get("category") or "")

        if collection or category:
            colls.append(f"{collection} → {category}")

    filename_entered = entered.get("filename_policy") or {}
    filename_mode = (
        filename_entered.get("mode")
        if isinstance(filename_entered, dict)
        else "keep"
    )
    filename_bits = {
        "keep": "Keep existing filenames",
        "clean": "Clean media names",
        "extended": (
            "Clean media names + extended naming: "
            f"{filename_entered.get('pattern') or '(no pattern)'}"
        ),
        "template": (
            "Custom pattern: "
            f"{filename_entered.get('pattern') or ''}"
        ),
    }

    return f"""
<div class="card save-summary" id="profile-summary">
  <div class="card-head">

    <h2>Saving will store</h2>
  </div>
  <p class="muted">Live summary of the current form.</p>
  <ul class="summary-list">
    <li><strong>Sources:</strong> <span data-summary-sources>{esc(f"{len(sources)} configured" if sources else "None configured yet")}</span></li>
    <li><strong>Destinations:</strong> <span data-summary-dests>{esc(f"{len(dests)} configured" if dests else "None configured yet")}</span></li>
    <li><strong>Categories/rules:</strong> <span data-summary-cats>{esc(f"{len(categories)} categories, {len(rules)} rules" if categories or rules else "None configured yet")}</span></li>
    <li><strong>Folder templates:</strong> <span data-summary-folders>{esc("Movie and TV configured" if entered.get("movie_template") and entered.get("tv_template") else "None configured yet")}</span></li>
    <li><strong>Filename policy:</strong> <span data-summary-naming>{esc(filename_bits.get(filename_mode, filename_bits["keep"]))}</span></li>
    <li><strong>Advanced options:</strong> <span data-summary-advanced>Using default settings</span></li>
  </ul>
</div>
"""


def _completion_panel(completion):
    if not completion:
        return ""

    items = "".join(
        f"""
<li>
  {"✓" if section["complete"] else "⚠"}
  {esc(section["label"])}
</li>"""
        for section in completion.get("sections", [])
    )

    if completion.get("complete"):
        return f"""
<div class="success-panel" role="status">
  <h3>Profile is ready to save.</h3>
  <ul class="checklist">{items}</ul>
  <p>Enter your library sources and organisation
  destinations above, then save to create the
  profile.</p>
</div>
"""

    needed = "".join(
        f"<li>{esc(label)}</li>"
        for label in completion.get("incomplete", [])
    )

    return f"""
<div class="warning-panel" role="status">
  <h3>Profile setup needs a little more information</h3>
  <ul class="checklist">{items}</ul>
  <p>You only need to complete:</p>
  <ul>{needed}</ul>
  <p>Once those are complete, the profile is ready
  to test.</p>
</div>
"""


def render_organisation_profiles(data):
    profiles = data.get("profiles") or []
    builtins = data.get("builtins") or {}
    errors = data.get("errors") or []
    saved = data.get("saved")
    entered = data.get("input") or {}

    notice = ""

    if data.get("deleted"):
        deleted = data["deleted"]
        notice = f"""
<div class="success-panel" role="status">
  <h3>Profile deleted</h3>
  <p>
    Removed {esc(deleted.get("name"))}.
  </p>
</div>
"""
    elif saved:
        notice = f"""
<div class="success-panel" role="status" id="profile-save-success"
     tabindex="-1">
  <h3>Profile saved successfully.</h3>
  <p>
    Profile saved: {esc(saved.get("name"))}.
  </p>
</div>
"""
    elif data.get("cloned_from"):
        notice = f"""
<div class="info-panel" role="status">
  <p>
    Cloned from {esc(data.get("cloned_from"))}: review
    the configuration below, give the profile its
    own name, add your library locations, then
    choose Save profile.
  </p>
</div>
"""

    rows = "".join(
        f"""
<tr>
  <td>{link(f"/organisation/profiles/{profile['id']}", profile.get("name"))}</td>
  <td>{esc((profile.get("digest") or "")[:16])}</td>
  <td>{esc(profile.get("created_at"))}</td>
</tr>"""
        for profile in profiles
    )

    builtin_rows = "".join(
        f"""
<tr>
  <td>{esc(name)}</td>
  <td>{esc(template.get("kind"))}</td>
  <td><code>{esc(template.get("pattern"))}</code></td>
</tr>"""
        for name, template in builtins.items()
    )

    def _value(key, default=""):
        return esc(entered.get(key, default))

    def _selected(key, option):
        current = entered.get(key, "")

        if not current and option in ("posix", "review"):
            return " selected"

        return (
            " selected" if current == option else ""
        )

    if errors:
        error_items = "".join(
            f"<li>{esc(item)}</li>" for item in errors
        )

        error_panel = f"""
<div class="error-panel" role="alert" id="profile-form-error"
     tabindex="-1">
  <h3>Profile was not saved.</h3>
  <ul>{error_items}</ul>
  <p>Fix the fields below and save again. Your
  input is preserved.</p>
</div>
"""
    else:
        error_panel = ""



    def _preset_cards(presets, loaded_name):
        cards = []

        for preset in presets or []:
            active = (
                loaded_name
                and preset.get("name") == loaded_name
            )

            cards.append(f"""
<div class="preset-card{" preset-active" if active else ""}">
  <h3>{esc(preset.get("name"))}</h3>
  <p class="muted">{esc(preset.get("description"))}</p>
  <form method="post"
        action="/organisation/profiles/preset"
        class="inline-form">
    <input type="hidden" name="preset"
           value="{esc(preset.get("key"))}">
    <button class="btn small{" ghost" if active else ""}"
            type="submit">
      {"Loaded" if active else "Use this preset"}
    </button>
  </form>
</div>""")

        return "".join(cards)

    builtin_movie = ""
    builtin_tv = ""
    builtin_cat = ""

    for _name, _tpl in (builtins or {}).items():
        _kind = (_tpl or {}).get("kind")
        _pat = (_tpl or {}).get("pattern") or ""
        if _kind == "movie" and not builtin_movie:
            builtin_movie = _pat
        elif _kind == "tv" and not builtin_tv:
            builtin_tv = _pat
        elif _kind == "category" and not builtin_cat:
            builtin_cat = _pat

    content = f"""
{_profile_page_head(breadcrumb=["Organisation", "Profiles", "Create"], title="Create Organisation Profile", subtitle="Configure how this library should be organised. Pick a preset, adjust the steps below, then save.")}
<section class="card">
  <div class="card-head"><h2>Organisation profiles</h2></div>
  {notice or '<p class="muted">One saved profile per library layout. Saving stores the current configuration under its unique name.</p>'}
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr>
      <th>Name</th><th>Digest</th><th>Created</th>
    </tr></thead>
    <tbody>{rows or '<tr><td colspan="3" class="muted">No saved profiles yet.</td></tr>'}</tbody>
  </table>
  </div>
</section>
<section class="card">
  <div class="card-head"><h2>Start from a preset</h2></div>
  <div class="info-panel">
    <p>
      Pick a starting point close to your library. The
      preset fills the editor below; you add your own
      library locations, choose a unique profile name,
      adjust anything, then save as a new profile.
      Presets themselves are never
      changed.
    </p>
  </div>
  <div class="preset-grid">
    {_preset_cards(data.get("presets"), data.get("preset_loaded"))}
  </div>
</section>
<section class="card">
  <div class="card-head"><h2>Built-in templates</h2></div>
  <p class="muted">Built-in patterns populate real configuration you can customise below. Use built-in defaults restores the three patterns into the Folder Structure step.</p>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr><th>Name</th><th>Kind</th><th>Pattern</th></tr></thead>
    <tbody>{builtin_rows}</tbody>
  </table>
  </div>
  <p><button type="button" class="btn small ghost" id="builtin-apply" data-movie="{esc(builtin_movie)}" data-tv="{esc(builtin_tv)}" data-cat="{esc(builtin_cat)}">Use built-in defaults</button></p>
</section>
<section class="card">
  <div class="card-head"><h2>Create a profile</h2></div>
  <div class="setup-pair">
  {_profile_progress_panel(entered)}
  {_profile_summary_html(entered)}
  </div>
  <p class="muted">
    A profile describes how your library should be
    organised. Give it a unique name and save: the
    stored configuration is updated under that name
    whenever you save changes.
  </p>
  {error_panel if errors else ""}
  {_profile_editor_form(
        entered,
        action="/organisation/profiles/save",
        summary_html=_profile_summary_html(entered),
        error_sections=data.get("error_sections") or [],
        name_field_html=f"""
      <label>Name (unique)
        <input type="text" name="name" value="{_value("name")}"
               placeholder="My library">
      </label>
""",
        submit_label="Save profile",
    )}
</section>
"""

    return layout(
        "Organisation profiles",
        "organisation",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def render_organisation_profile_detail(data):
    profile = data["profile"]
    payload = profile.get("payload") or {}
    problems = data.get("problems") or []
    previews = data.get("previews") or []

    roots = payload.get("roots") or []
    templates = payload.get("templates") or {}
    mappings = payload.get("tag_mappings") or []
    naming = payload.get("naming") or {}
    categories = payload.get("categories") or {}

    root_rows = (data.get("root_rows") or {}).get("rows", [])

    roots_html = "".join(
        f"<li><code>{esc(row.get('path'))}</code> "
        f"<span class=\"muted\">&#8594;</span> "
        f"<code>{{{esc(row.get('alias'))}}}</code></li>"
        for row in root_rows
        if isinstance(row, dict) and row.get("path")
    ) or "<li>No roots configured</li>"

    source_list = payload.get("sources") or []

    dest_paths = [
        row.get("path", "").strip()
        for row in root_rows
        if isinstance(row, dict) and row.get("path", "").strip()
    ]

    sources_html = "".join(
        f"<li><code>{esc(item if isinstance(item, str) else item.get('path', ''))}</code></li>"
        for item in source_list
        if (item if isinstance(item, str) else item.get("path"))
    ) or "<li>No sources configured</li>"

    category_rows = "".join(
        f"""
<tr>
  <td>{esc(name)}</td>
  <td><code>{esc(folder)}</code></td>
  <td>{ "<br>".join(
            esc(f"{path.rstrip('/')}/{folder}")
            for path in dest_paths
        ) or '<span class="muted">(none)</span>' }</td>
</tr>"""
        for name, folder in categories.items()
    )

    template_rows = "".join(
        f"""
<tr>
  <td>{esc(name)}</td>
  <td>{esc(template.get("kind"))}</td>
  <td><code>{esc(template.get("pattern"))}</code></td>
</tr>"""
        for name, template in templates.items()
    )

    mapping_rows = "".join(
        f"""
<tr>
  <td>{esc(mapping.get("id"))}</td>
  <td>{esc(mapping.get("provider") or "any")}</td>
  <td>{esc(mapping.get("priority", 100))}</td>
  <td>{esc(", ".join(mapping.get("labels") or []))}</td>
  <td>{esc(mapping.get("category"))}</td>
</tr>"""
        for mapping in mappings
        if isinstance(mapping, dict)
    )

    def _rule_description(row):
        if not isinstance(row, dict):
            return ""

        parts = [
            {"movie": "Movie", "tv": "TV"}.get(
                str(row.get("media_kind") or "any").strip().casefold(),
                "Any kind",
            )
        ]

        cert = str(row.get("certification") or "").strip().upper()

        if cert:
            parts.append(cert)

        collection = row.get("collection")

        if isinstance(collection, str) and collection.strip():
            parts.append(f"collection '{collection.strip()}'")

        for field in ("genres", "tags"):
            for label in row.get(field) or []:
                if isinstance(label, str) and label.strip():
                    parts.append(label.strip())

        text = f"{' + '.join(parts)} → {row.get('category') or '?'}"

        if row.get("fallback"):
            text += " (fallback)"

        return text

    org_rules = [
        rule
        for rule in (payload.get("organisation_rules") or [])
        if isinstance(rule, dict)
    ]

    org_rule_rows = "".join(
        f"""
<tr>
  <td>{esc(rule.get("id"))}</td>
  <td>{esc(_rule_description(rule))}</td>
</tr>"""
        for rule in org_rules
    )

    intelligent = payload.get("intelligent_rules") or {}

    signal_rows = "".join(
        f"""
<tr>
  <td>{esc(category)}</td>
  <td>{esc(", ".join((signals or {}).get("genres") or []))}</td>
  <td>{esc(", ".join((signals or {}).get("collections") or []))}</td>
  <td>{esc(", ".join((signals or {}).get("networks") or []))}</td>
  <td>{esc(", ".join((signals or {}).get("provider_flags") or []))}</td>
</tr>"""
        for category, signals in sorted(intelligent.items())
        if isinstance(signals, dict)
    )

    preview_rows = "".join(
        f"""
<tr>
  <td>{esc(item.get("name"))}</td>
  <td><code>{esc(item.get("pattern"))}</code></td>
  <td><code>{esc(item.get("destination") or item.get("error") or "")}</code></td>
</tr>"""
        for item in previews
    )

    problems_html = ""

    if problems:
        problems_html = (
            "<ul>"
            + "".join(
                f"<li>{esc(item)}</li>" for item in problems
            )
            + "</ul>"
        )
    else:
        problems_html = (
            '<p class="muted">No validation problems.</p>'
        )

    edit = data.get("edit") or {}
    edit_input = edit.get("input") or {}
    edit_completion = edit.get("completion") or {}
    edit_errors = edit.get("errors") or data.get("errors") or []
    edit_saved = edit.get("saved") or data.get("saved")

    notice = ""

    if edit_saved:
        notice = f"""
<div class="success-panel" role="status" id="profile-save-success"
     tabindex="-1">
  <h3>Profile saved successfully.</h3>
  <p>
    Saved {esc(edit_saved.get("name"))} with the
    configuration below.
  </p>
</div>
"""

    error_notice = ""

    if edit_errors:
        error_notice = f"""
<div class="error-panel" role="alert" id="profile-form-error"
     tabindex="-1">
  <h3>Profile was not saved.</h3>
  <ul>{''.join(f'<li>{esc(item)}</li>' for item in edit_errors)}</ul>
  <p>Fix the fields below and save again. Your
  input is preserved.</p>
</div>
"""

    autofill = data.get("autofill") or {}
    autofill_html = ""

    if autofill.get("message"):
        autofill_html = f"""
<div class="info-panel" role="status">
  <p>{esc(autofill.get("message"))}</p>
</div>
"""

    delete_html = ""

    if data.get("delete_confirm"):
        delete_html = f"""
<div class="error-panel" role="alert">
  <h3>Delete this profile?</h3>
  <p>
    This permanently removes
    {esc(profile.get("name"))}. Built-in presets are
    never affected. This cannot be undone.
  </p>
  <form method="post"
        action="/organisation/profiles/{esc(profile.get('id'))}/delete"
        class="inline-form">
    <input type="hidden" name="confirm" value="yes">
    <button class="btn small btn-danger" type="submit">
      Yes, delete this profile
    </button>
    <a class="btn small ghost"
       href="/organisation/profiles/{esc(profile.get('id'))}">
      Cancel
    </a>
  </form>
</div>
"""
    else:
        delete_html = f"""
<form method="post"
      action="/organisation/profiles/{esc(profile.get('id'))}/delete"
      class="inline-form">
  <button class="btn small btn-danger" type="submit">
    Delete profile
  </button>
</form>
"""

    origin = payload.get("origin") or {}

    def _detail_pattern(key, selected):
        template = templates.get(selected or "") or {}

        if isinstance(template, dict) and template.get(
            "pattern"
        ):
            return template.get("pattern") or ""

        kinds = {
            "movie": "movie",
            "tv": "tv",
            "category": "category",
        }

        for name in sorted(templates):
            candidate = templates.get(name) or {}

            if (
                isinstance(candidate, dict)
                and candidate.get("kind") == kinds.get(key)
                and candidate.get("pattern")
            ):
                return candidate.get("pattern")

        return ""

    cert_rules = payload.get("certification_rules") or []
    coll_rules = payload.get("collection_rules") or []
    filename_policy = payload.get("filename_policy") or {}

    def _filename_label():
        mode = (
            filename_policy.get("mode")
            if isinstance(filename_policy, dict)
            else "keep"
        )

        if mode == "clean":
            return "Clean media names"
        if mode == "extended":
            return (
                "Clean media names + extended naming: "
                f"{filename_policy.get('pattern') or '(no pattern)'}"
            )
        if mode == "template":
            return (
                "Custom pattern: "
                f"{filename_policy.get('pattern') or ''}"
            )

        return "Keep existing filenames"

    summary_rows = [
        ("Sources", esc(", ".join(
            item if isinstance(item, str) else str(
                item.get("path") or ""
            )
            for item in (payload.get("sources") or [])
        ) or "(none)")),
        ("Destinations", esc(", ".join(
            f"{row.get('path')} {{{row.get('alias')}}}"
            for row in root_rows
            if isinstance(row, dict) and row.get("path")
        ) or "(none)")),
        ("Movie organisation", esc(
            _detail_pattern(
                "movie", payload.get("movie_template")
            )
        )),
        ("TV organisation", esc(
            _detail_pattern(
                "tv", payload.get("tv_template")
            )
        )),
        ("Category organisation", esc(
            _detail_pattern(
                "category",
                payload.get("category_template"),
            )
        )),
        ("Categories", esc(", ".join(
            f"{name} → {folder}"
            for name, folder in categories.items()
        ) or "(none)")),
        ("File naming", esc(_filename_label())),
        ("Rating rules", esc(", ".join(
            f"{rule.get('certification')}/"
            f"{rule.get('media_kind')} → "
            f"{rule.get('category')}"
            for rule in cert_rules
            if isinstance(rule, dict)
        ) or "(none)")),
        ("Collection rules", esc(", ".join(
            f"{rule.get('collection')} → "
            f"{rule.get('category')}"
            for rule in coll_rules
            if isinstance(rule, dict)
        ) or "(none)")),
        ("Tag rules", esc(", ".join(
            f"{'+'.join(mapping.get('labels') or [])} → "
            f"{mapping.get('category')}"
            for mapping in mappings
            if isinstance(mapping, dict)
        ) or "(none)")),
        ("Organisation Rules", esc(
            f"{len(org_rules)} ordered rules"
            + (
                " (incl. fallbacks)"
                if any(
                    rule.get("fallback") for rule in org_rules
                )
                else ""
            )
            if org_rules
            else "(none)"
        )),
    ]

    if isinstance(origin, dict) and origin.get("preset"):
        summary_rows.append(
            (
                "Started from",
                esc(
                    f"built-in preset "
                    f"'{origin.get('preset')}' (this saved "
                    f"profile is user-owned and editable)"
                ),
            )
        )

    content = f"""
{_profile_page_head(breadcrumb=["Organisation", "Profiles", "Edit Profile"], title="Edit Organisation Profile", subtitle="Update this profile configuration, organisation rules and filename policy.", back_href="/organisation/profiles", back_label="Back to Profiles")}
<section class="card">
  <div class="card-head">

    <h2>Profile: {esc(profile.get("name"))}</h2>
  </div>
  {notice}
  <div class="info-panel">
    <p>
      One editable profile: change anything below
      (including the name) and choose Save Changes
      once. Saving updates this same profile; no new
      profile is created.
    </p>
  </div>
  {facts(summary_rows)}
  <form method="post"
        action="/organisation/profiles/{esc(profile.get('id'))}/clone"
        class="inline-form">
    <button class="btn small" type="submit">
      Clone as new profile
    </button>
    <span class="muted">
      Opens the create editor with this configuration
      under a suggested derived name you can still
      edit. Nothing is stored until you save.
    </span>
  </form>
  <details class="disclosure">
    <summary>Validation</summary>
    {problems_html}
  </details>
  <details class="disclosure">
    <summary>Full payload</summary>
    <pre>{esc(json_format(payload))}</pre>
  </details>
</section>
<section class="card">
  <div class="card-head"><h2>Library sources</h2></div>
  <ul>{sources_html}</ul>
  <p class="muted">
    Where NAMOA is allowed to look for files. A source
    is not automatically a destination; use sources as
    What-If and preview scopes.
  </p>
</section>
<section class="card">
  <div class="card-head"><h2>Library roots</h2></div>
  <ul>{roots_html}</ul>
  <p class="muted">
    Use <a href="/api/fs/browse">/fs/browse</a> to explore
    the filesystem when choosing roots.
  </p>
</section>
<section class="card">
  <div class="card-head"><h2>Templates</h2></div>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr><th>Name</th><th>Kind</th><th>Pattern</th></tr></thead>
    <tbody>{template_rows}</tbody>
  </table>
  </div>
</section>
<section class="card">
  <div class="card-head"><h2>Intelligent classification signals</h2></div>
  <p class="muted">
    Deterministic metadata signals per category: a file
    joins a category when at least two configured signals
    match its provider metadata (or a configured
    collection names it directly). These signals guide
    classification; they never move files by themselves.
  </p>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr>
      <th>Category</th><th>Genres</th><th>Collections</th>
      <th>Networks / studios</th><th>Provider flags</th>
    </tr></thead>
    <tbody>{signal_rows or '<tr><td colspan="5" class="muted">No intelligent signals configured.</td></tr>'}</tbody>
  </table>
  </div>
  <p class="muted">
    Signals are edited together with everything else in
    the Edit section below: one Save Changes covers the
    whole profile.
  </p>
</section>
<section class="card">
  <div class="card-head"><h2>Organisation Rules</h2></div>
  <p class="muted">
    Ordered policy: the first matching rule wins,
    top to bottom. Fallback rules at the end cover
    ordinary Movies and TV.
  </p>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr><th>Id</th><th>Rule</th></tr></thead>
    <tbody>{org_rule_rows or '<tr><td colspan="2" class="muted">No organisation rules configured.</td></tr>'}</tbody>
  </table>
  </div>
  <p class="muted">
    Rules are edited together with everything else
    in the Edit section below: one Save Changes covers
    the whole profile.
  </p>
</section>
<section class="card">
  <div class="card-head"><h2>Tag mappings</h2></div>
  <p class="muted">
    Explicit provider-tag policy, applied after
    the Organisation Rules below and intelligent
    classification. Precedence: the most
    specific matching rule wins first, then lower
    priority numbers, then mapping id (Kids + Anime
    beats Kids alone). Conflicting mappings stay
    reviewable and never move files silently.
  </p>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr>
      <th>Id</th><th>Provider</th><th>Priority</th>
      <th>Labels</th><th>Category</th>
    </tr></thead>
    <tbody>{mapping_rows or '<tr><td colspan="5" class="muted">No tag mappings.</td></tr>'}</tbody>
  </table>
  </div>
  <p class="muted">
    Mappings are edited together with everything else
    in the Edit section below: one Save Changes covers
    the whole profile.
  </p>
  <details class="disclosure">
    <summary>Advanced: raw JSON</summary>
    <p class="muted">
      The profile editor accepts the full mapping
      list as JSON for bulk edits.
    </p>
  </details>
</section>
<section class="card">
  <div class="card-head"><h2>Category folders</h2></div>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr><th>Category</th><th>Folder</th><th>Resolved locations</th></tr></thead>
    <tbody>{category_rows or '<tr><td colspan="3" class="muted">No category folders configured.</td></tr>'}</tbody>
  </table>
  </div>
  <p class="muted">
    Friendly category names on the left, actual
    filesystem locations on the right (one per
    configured destination).
  </p>
  <p class="muted">
    Categories are edited together with everything
    else in the Edit section below: one Save Changes
    covers the whole profile.
  </p>
</section>
<section class="card">
  <div class="card-head"><h2>Live structural preview</h2></div>
  <p class="muted">
    Built-in templates rendered over sample values
    (Title: Example Movie, Year: 2024, Series: Example
    Show, Season: 01).
  </p>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr>
      <th>Template</th><th>Pattern</th><th>Preview</th>
    </tr></thead>
    <tbody>{preview_rows}</tbody>
  </table>
  </div>
</section>
<section class="card">
  <div class="card-head"><h2>Edit this profile</h2></div>
  <div class="info-panel">
    <p>
      Change anything below (sources, destinations,
      templates, categories, tag rules, naming),
      then choose Save Changes once. Saving updates
      this same profile.
    </p>
  </div>
  <div class="setup-pair">
  {_profile_progress_panel(edit_input)}
  {_profile_summary_html(edit_input)}
  </div>
  {error_notice}
  <form method="post"
        action="/organisation/profiles/{esc(profile.get('id'))}/autofill-tags"
        class="inline-form">
    <button class="btn small ghost" type="submit">
      Autofill Recommended Tags
    </button>
    <span class="muted">
      Suggests tag rules from real observed provider
      tags. Suggestions appear below for review; the
      standard preset already works without them.
    </span>
  </form>
  {autofill_html}
  {_profile_editor_form(
        edit_input,
        action=f"/organisation/profiles/{esc(profile.get('id'))}/save",
        error_sections=edit.get("error_sections") or [],
        name_field_html=f"""
      <label>Name (unique)
        <input type="text" name="name"
               value="{esc(edit_input.get("name") or profile.get("name"))}"
               placeholder="My library">
      </label>
      <p class="field-hint">
        Renaming keeps this same profile; the old
        name is freed. Names must stay unique.
      </p>
""",
        submit_label="Save Changes",
        summary_html="",
        include_save=False,
    )}
</section>
<div class="profile-actions">
  <button class="btn small" form="profile-edit-form" type="submit">
    Save profile
  </button>
  {delete_html}
</div>
"""

    return layout(
        f"Organisation profile {profile.get('id')}",
        "organisation",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def render_organisation_whatif(data):
    profiles = data.get("profiles") or []
    entered = data.get("input") or {}

    def _field(key, default=""):
        value = entered.get(key, default)
        return esc(value if value is not None else default)

    def _selected_profile():
        try:
            return int(entered.get("profile_id"))
        except (TypeError, ValueError):
            return None

    def _checked(key, value, default=False):
        current = entered.get(key, None)

        if current in (None, ""):
            return " checked" if default else ""

        return (
            " checked"
            if str(current) == str(value)
            else ""
        )

    content = f"""
<section class="card">
  <div class="card-head"><h2>What-If planning</h2></div>
  <p class="muted">
    Read-only previews over the shared planning semantics.
    Nothing is persisted and no file is touched.
  </p>
</section>
<section class="card">
  <div class="card-head"><h2>Single file What-If</h2></div>
  {_form_error_panel(data)}
  <form method="post" action="/organisation/whatif/file"
        class="org-form">
    <div class="info-panel">
      <p><strong>Input mode</strong></p>
      <p class="muted">Choose one. The other input stays inactive.</p>
      <p>
        <label><input type="radio" name="input_mode"
               value="media"{_checked("input_mode", "media", True)}>
          Media ID</label><br>
        <label><input type="radio" name="input_mode"
               value="file"{_checked("input_mode", "file")}>
          File path</label>
      </p>
    </div>
    <div class="input-card" id="whatif-media-card">
      <span class="input-card-label">Media ID</span>
      <label>
      <input type="text" name="media_id" placeholder="123"
             id="whatif-media-id"
             value="{_field("media_id")}" inputmode="numeric">
      </label>
    </div>
    <p class="field-hint">
      The Media ID shown for each item on the
      <a href="/media">Media</a> page, or open any item
      there and choose Preview in What-If. You can also
      analyse a file first with
      <a href="/quick-find">Quick Find</a>.
    </p>
    <div class="input-card" id="whatif-file-card">
    <label>Or file path (including files NAMOA has never seen)
      <span class="input-row">
      <input type="text" name="file_path"
             id="whatif-file-path"
             placeholder="/mnt/usb/Movies/Aladdin.1992.mkv"
             value="{_field("file_path")}">
      <button type="button" class="btn small ghost js-browse-open"
              data-browser="whatif-file" id="whatif-browse">
        Browse
      </button>
      </span>
    </label>
    <p class="field-hint">
      Browse to any video file, even on a newly
      attached drive. NAMOA analyses it through the
      normal pipeline without saving anything, then
      previews exactly what it would do.
    </p>
    {folder_browser_block("whatif-file-path", "whatif-file", show_toggle=False, show_files=True)}
    </div>
    <label>Profile
      <select name="profile_id">
        {_profile_options(profiles, selected=_selected_profile())}
      </select>
    </label>
    <label>Metadata scope
      <select name="metadata_scope">
        <option value="cached">cached</option>
        <option value="live">live</option>
      </select>
    </label>
    <div class="info-panel">
      <p><strong>Run mode</strong></p>
      <p class="muted">The intent of this preview,
      shown on the result.</p>
      <div class="radio-stack">
      <p>
        <label><input type="radio" name="run_mode"
               value="profile"{_checked("run_mode", "profile", True)}>
          Profile default</label><br>
        <span class="muted">Use the saved profile filename policy.</span>
      </p>
      <p>
        <label><input type="radio" name="run_mode"
               value="folders"{_checked("run_mode", "folders")}>
          Keep existing filenames</label><br>
        <span class="muted">Keep the existing filename and only organise
        the file into the correct folder.</span>
      </p>
      <p>
        <label><input type="radio" name="run_mode"
               value="clean"{_checked("run_mode", "clean")}>
          Use clean media names</label><br>
        <span class="muted">Rename the file using the recognised movie
        or TV information.</span>
      </p>
      <p>
        <label><input type="radio" name="run_mode"
               value="extended"{_checked("run_mode", "extended")}>
          Use clean media names + extended naming</label><br>
        <span class="muted">Keep the clean media name and optionally
        append technical or release information.</span>
      </p>
      <div id="whatif-extended-block">
        <label>Extended pattern
          <input type="text" name="filename_pattern"
                 placeholder="{{file[quality]}}.WEB-DL.{{file[codec]}}-HAX0R">
        </label>
        <label>Separator
          <input type="text" name="filename_separator"
                 value=" ">
        </label>
        <p class="muted">Media tokens: Title, Year, Series, Season,
        Episode, Episode Title. File tokens: Quality, Resolution,
        Bitrate, Codec, Audio, Source, HDR, Edition. Literal text
        is preserved.</p>
      </div>
      <p>
        <label><input type="radio" name="run_mode"
               value="template"{_checked("run_mode", "template")}>
          Template</label><br>
        <span class="muted">Render a custom filename template, or the
        profile stored custom template.</span>
      </p>
      <div id="whatif-template-block">
        <label>Custom template pattern
          <input type="text" name="filename_template_pattern"
                 placeholder="{{Series}} - S{{Season}}E{{Episode}}">
        </label>
      </div>
      </div>
      <div class="capability-box">
        <p>
          <label><input type="checkbox" name="identify"
                 value="yes">
            Identify with providers</label>
        </p>
        <p class="muted">
          File paths NAMOA has never seen: read-only
          provider lookup, then plan.
        </p>
      </div>
    </div>
    <button class="btn small" type="submit">Preview file plan</button>
  </form>
</section>
<section class="card">
  <div class="card-head"><h2>Directory sampler What-If</h2></div>
  <form method="post" action="/organisation/whatif/sample"
        class="org-form" id="sampler-form">
    <label>Directory
      <input type="text" name="directory" id="whatif-directory"
             placeholder="/media/library"
             value="{_field("directory")}">
    </label>
    {folder_browser_block("whatif-directory", "whatif-sampler")}
    <p class="field-hint">
      Browse to navigate directories, select the folder,
      then run the sample. Up to 10 files are previewed.
    </p>
    <div class="form-grid">
      <div>
        <label>Limit (1-10)
          <input type="text" name="limit" value="{_field("limit", "10")}"
                 inputmode="numeric">
        </label>
      </div>
      <div>
        <label>Seed (blank for a fresh random seed)
          <input type="text" name="seed" placeholder=""
                 value="{_field("seed")}" inputmode="numeric">
        </label>
      </div>
    </div>
    <label>Profile
      <select name="profile_id">
        {_profile_options(profiles, selected=_selected_profile())}
      </select>
    </label>
    <button class="btn small" type="submit" id="sampler-submit">Sample directory</button>
    <div class="sampler-loading" id="sampler-loading" hidden>
      <p><strong>Loading samples...</strong></p>
      <div class="spinner" role="status" aria-label="Sampling in progress"></div>
      <p class="muted" id="sampler-status">
        Checking the directory for supported video
        files. Please be patient.
      </p>
      <p class="muted" id="sampler-humour"></p>
    </div>
  </form>
</section>
"""

    return layout(
        "Organisation What-If",
        "organisation",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def _metadata_evidence_card(plan, metadata_scope=""):
    """
    Human-readable metadata and decision-chain view for
    one file plan. Raw JSON stays available under the
    technical disclosure on the calling page; this card
    is the normal presentation. Provenance (observation
    ids, fingerprint) is kept, secondary.
    """

    summary = plan.get("metadata_summary") or {}
    association = plan.get("association") or {}
    mutation = plan.get("mutation") or {}

    tags_by_provider = summary.get("_tags_by_provider") or {}

    if isinstance(tags_by_provider, dict):
        tag_bits = [
            f"{provider}: {', '.join(tags)}"
            for provider, tags in sorted(tags_by_provider.items())
            if tags
        ]
    else:
        tag_bits = []

    provider_ids = summary.get("provider_ids") or association.get("provider_ids") or {}

    if isinstance(provider_ids, dict):
        id_bits = [
            f"{scope}: {value}"
            for scope, value in sorted(provider_ids.items())
            if value
        ]
    else:
        id_bits = []

    def _list(value):
        if not value:
            return "-"
        if isinstance(value, list):
            return esc(", ".join(str(item) for item in value))
        return esc(value)

    evidence_items = [
        ("Provider", esc(association.get("provider") or "-")),
        ("Title", esc(summary.get("title") or "-")),
        ("Year", esc(summary.get("year") or "-")),
        (
            "Genres",
            _list(summary.get("genres")),
        ),
        (
            "Tags",
            esc("; ".join(tag_bits) or "-"),
        ),
        (
            "Collections",
            _list(summary.get("collections")),
        ),
        (
            "Rating / certification",
            esc(
                summary.get("certification")
                or summary.get("rating")
                or "-"
            ),
        ),
        (
            "Provider IDs",
            esc("; ".join(id_bits) or "-"),
        ),
        (
            "Association",
            esc(
                f'{association.get("strength") or "none"}'
                f' ({association.get("basis") or "no basis"})'
                if association else "none"
            ),
        ),
    ]

    freshness = plan.get("review_state") or "unknown"

    if freshness == "stale":
        fresh_badge = badge("stale", "stale")
    elif freshness in ("needs_review", "conflict", "collision"):
        fresh_badge = badge(freshness, "stale")
    elif freshness in ("ready", "already_correct"):
        fresh_badge = badge(freshness, "current")
    else:
        fresh_badge = badge(freshness, "unknown")

    fingerprint = (plan.get("metadata_cited") or {}).get("fingerprint")

    freshness_items = [
        ("Freshness", fresh_badge),
        (
            "Metadata fingerprint",
            esc(
                str(fingerprint)[:16] + "..."
                if fingerprint else "none cited"
            ),
        ),
        (
            "Provider overlap review",
            esc(
                "required"
                if plan.get("provider_review") else "none"
            ),
        ),
        ("Metadata scope", esc(metadata_scope or "-")),
    ]

    rules = plan.get("rules_applied") or []
    mappings = plan.get("mappings_applied") or []

    priority = (
        plan.get("provider_priority")
        or summary.get("_provider_priority")
        or []
    )

    sources = summary.get("_sources") or {}

    selected_bits = []

    for field in (
        "title",
        "year",
        "season_number",
        "episode_number",
        "studio",
        "certification",
    ):
        if summary.get(field) is None:
            continue

        selected_bits.append(
            f"{field}: {summary.get(field)} "
            f"({sources.get(field, 'filename')})"
        )

    disagreements = summary.get("_disagreements") or {}

    alternate_bits = []

    for field in sorted(disagreements):
        options = ", ".join(
            f"{entry.get('provider')}: {entry.get('value')}"
            for entry in disagreements[field]
        )

        if options:
            alternate_bits.append(f"{field}: {options}")

    resolution_items = [
        (
            "Metadata sources",
            esc(
                ", ".join(
                    sorted(
                        {
                            key
                            for key in list(
                                tags_by_provider
                            )
                            + list(sources.values())
                            if key
                        }
                    )
                )
                or "-"
            ),
        ),
        (
            "Provider priority",
            esc(
                " > ".join(priority)
                if priority
                else "-"
            ),
        ),
        (
            "Selected values",
            esc("; ".join(selected_bits) or "-"),
        ),
        (
            "Additional evidence",
            esc("; ".join(alternate_bits) or "-"),
        ),
        (
            "Tags",
            esc(
                "combined from reliable sources; "
                + ("; ".join(tag_bits) or "none")
            ),
        ),
        (
            "Category",
            esc(
                f'{plan.get("category") or "none"}'
            ),
        ),
    ]

    chain = [
        f'Observed metadata: {esc(summary.get("title") or "filename evidence only")}',
        f'Association: {esc(association.get("strength") or "none")} via {esc(association.get("basis") or "no basis")}',
        f'Classification: {esc(plan.get("classification") or "unclassified")}',
        f'Matched rule: {esc("; ".join(mappings) or "; ".join(rules) or "none")}',
        f'Expected destination: {esc(plan.get("expected_destination") or "none")}',
        (
            f'Proposed action: {esc(mutation.get("strategy") or "none")} '
            f'({esc(mutation.get("operation_count", 0))} operation(s))'
        ),
    ]

    return f"""
<section class="card">
  <div class="card-head">
    <h2>Metadata evidence</h2>
    {fresh_badge}
  </div>
  {facts(evidence_items)}
  <h3>Freshness</h3>
  {facts(freshness_items)}
  <h3>Metadata resolution</h3>
  {facts(resolution_items)}
  <h3>Decision chain</h3>
  <ol class="decision-chain">
    {''.join(f'<li>{step}</li>' for step in chain)}
  </ol>
</section>
"""


def _dirname(path) -> str:
    """Parent directory of a path, Never raises."""

    import os as _os

    try:
        return _os.path.dirname(str(path or ""))
    except (OSError, ValueError):
        return ""


def _whatif_human_type(plan) -> str:
    """User-facing media type without planner vocabulary."""

    classification = plan.get("classification") or ""
    category = plan.get("category") or ""

    text = category or classification

    lowered = str(text).lower()

    if lowered in ("movies", "movie"):
        return "Movie"

    if lowered in ("tv", "series", "episode"):
        return "TV"

    if lowered.startswith("metadata:"):
        inner = text.split(":", 1)[1].strip()
        return inner or "File"

    if not text or lowered == "unclassified":
        return "File"

    return str(text)


def _whatif_state(plan):
    """
    Distinct user-facing result state derived from the
    plan. Returns (key, title, headline). Never collapses
    distinct outcomes into one generic message.
    """

    review_state = plan.get("review_state") or ""
    destination = plan.get("expected_destination")

    if review_state == "already_correct":
        return (
            "already_organised",
            "Already organised",
            "The current location already matches the "
            "destination defined by this profile. No "
            "filesystem change is required.",
        )

    if review_state == "ready" and destination:
        return (
            "change_proposed",
            "Organisation change proposed",
            "NAMOA proposes exactly one filesystem change, "
            "described below. Nothing has been changed yet.",
        )

    if review_state == "collision":
        return (
            "blocked",
            "Blocked: destination occupied",
            "NAMOA will not overwrite the existing "
            "destination. No filesystem change will be "
            "made until this is resolved.",
        )

    if review_state == "stale":
        return (
            "blocked",
            "Blocked: information is out of date",
            "The file changed since NAMOA last looked at "
            "it. Re-scan and preview again; no filesystem "
            "change will be made on stale information.",
        )

    if review_state in ("conflict", "needs-review"):
        return (
            "review_required",
            "Review required",
            "NAMOA found a possible organisation, but "
            "cannot safely act automatically. No "
            "filesystem change will be made until this "
            "is resolved.",
        )

    if not destination:
        classification = plan.get("classification")
        category = plan.get("category")

        if classification or category:
            return (
                "no_rule",
                "No rule applies",
                "The file was understood, but this profile "
                "does not define an organisation change "
                "for it. No filesystem change is required.",
            )

        return (
            "review_required",
            "Review required",
            "NAMOA could not gather enough evidence to "
            "propose a safe organisation. No filesystem "
            "change will be made until this is resolved.",
        )

    return (
        "review_required",
        "Review required",
        "NAMOA could not confirm this plan is safe to "
        "run automatically. No filesystem change will "
        "be made until this is resolved.",
    )


def _whatif_safety(plan):
    """
    User-facing readiness checklist derived from real
    plan fields. Returns [(ok, label)].
    """

    mutation = plan.get("mutation") or {}
    association = plan.get("association") or {}
    cited = plan.get("metadata_cited") or {}
    review_state = plan.get("review_state") or ""
    strategy = mutation.get("strategy") or ""
    confidence = plan.get("confidence") or 0

    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = 0.0

    strength = association.get("strength") or ""
    cited_ids = cited.get("observation_ids") or []

    if strength in (
        "exact_path",
        "cross_provider_id",
        "single_id_title",
    ):
        metadata_check = (
            True,
            f"metadata association reliable ({strength})",
        )
    elif cited_ids or strength:
        metadata_check = (
            False,
            "metadata association needs review "
            f"({strength or 'weak'})",
        )
    else:
        metadata_check = (
            True,
            "no provider metadata required for this decision",
        )

    return [
        (
            bool(plan.get("current_path")),
            "file identified",
        ),
        (
            bool(plan.get("classification"))
            and confidence_value >= 0.5,
            "classification sufficiently confident "
            f"({confidence_value:.0%})",
        ),
        metadata_check,
        (
            bool(plan.get("expected_destination"))
            and bool(plan.get("destination_root")),
            "destination valid",
        ),
        (
            bool(plan.get("template"))
            or bool(plan.get("expected_destination")),
            "template valid",
        ),
        (
            review_state != "collision",
            "no collision",
        ),
        (
            strategy
            in (
                "move file",
                "rename file",
                "copy, verify, then remove original",
                "already correct",
                "requires review",
                "collision",
            ),
            "operation supported",
        ),
        (
            review_state != "stale",
            "currentness checks pass",
        ),
    ]


def _whatif_operation(plan):
    """
    Honest operation naming: RENAME, MOVE,
    COPY → VERIFY → DELETE SOURCE, or an explicit
    no-operation/blocked statement. Returns
    (label, explanation).
    """

    mutation = plan.get("mutation") or {}
    strategy = mutation.get("strategy") or ""
    review_state = plan.get("review_state") or ""

    if review_state == "already_correct":
        return (
            "NO OPERATION REQUIRED",
            "No filesystem change is required.",
        )

    if strategy == "rename file":
        return (
            "RENAME",
            "Only the filename changes within the same "
            "directory.",
        )

    if strategy == "move file":
        return (
            "MOVE",
            "The file moves to a different directory on "
            "the same filesystem using the existing safe "
            "move authority.",
        )

    if strategy == "copy, verify, then remove original":
        return (
            "COPY → VERIFY → DELETE SOURCE",
            "Source and destination are on different "
            "filesystems, so a bare rename cannot work. "
            "NAMOA will copy the file, verify the "
            "destination, and only then remove the "
            "original. The source is never deleted "
            "before successful verification.",
        )

    if review_state == "collision":
        return (
            "BLOCKED: WILL NOT OVERWRITE",
            "NAMOA will not overwrite the existing "
            "destination.",
        )

    return (
        "NO OPERATION",
        "NAMOA will not perform this operation until "
        "the review condition is resolved.",
    )


def _whatif_execution_note(state_key) -> str:
    """What WOULD happen on execution. What-If never runs it."""

    if state_key == "change_proposed":
        return (
            "If approved, NAMOA will perform this exact "
            "operation and then verify the result."
        )

    if state_key == "already_organised":
        return "No filesystem change is required."

    if state_key == "blocked":
        return (
            "NAMOA refuses this operation; approval cannot "
            "override the blocker."
        )

    if state_key == "no_rule":
        return "There is nothing to approve for this file."

    return (
        "NAMOA will not perform this operation until the "
        "review condition is resolved."
    )


def _whatif_missing(plan):
    """
    Explicit missing links when no actionable proposal
    exists, so nobody reverse-engineers planner state.
    Returns [(missing, why_it_matters)].
    """

    missing = []
    association = plan.get("association") or {}
    cited = plan.get("metadata_cited") or {}
    review_state = plan.get("review_state") or ""

    if not association and not (cited.get("observation_ids") or []):
        missing.append(
            (
                "provider metadata association",
                "Without associated provider metadata, "
                "category rules based on tags cannot fire "
                "and only filename evidence is available.",
            )
        )

    if (plan.get("classification") or plan.get("category")) and (
        not plan.get("expected_destination")
    ):
        missing.append(
            (
                f"destination for {plan.get('category') or plan.get('classification')}",
                "The profile does not map this category "
                "to a destination root, so no target path "
                "can be built.",
            )
        )

    if not plan.get("expected_destination") and not plan.get(
        "template"
    ):
        missing.append(
            (
                "valid template",
                "Without a template naming the folder and "
                "file structure, no exact path can be "
                "proposed.",
            )
        )

    if review_state == "collision":
        missing.append(
            (
                "clear destination",
                "The destination already contains a "
                "different file; NAMOA never overwrites.",
            )
        )

    return missing


def _whatif_naming_card(plan, data):
    """
    Filename preview (§27): current file, identified
    media, effective filename policy (profile or run
    override), and the resulting filename. Pure
    presentation over plan fields.
    """

    import os as _os

    current = plan.get("current_path") or ""
    current_name = _os.path.basename(current)
    expected = plan.get("expected_destination") or ""
    result_name = _os.path.basename(expected)

    summary = plan.get("metadata_summary") or {}
    title = summary.get("title")
    year = summary.get("year")

    if title:
        identified = str(title) + (
            f" ({year})" if year not in (None, "") else ""
        )
    else:
        identified = "local filename analysis only"

    mode = plan.get("filename_mode") or "keep"
    overridden = plan.get("filename_mode_override")

    policy_labels = {
        "keep": "Keep existing filename",
        "clean": "Use clean media name",
        "extended": "Clean media name + extended naming",
        "template": "Custom filename pattern",
    }
    policy = policy_labels.get(mode, mode)

    if overridden:
        policy += " (run choice for this preview)"
    else:
        profile_summary = data.get("profile_summary") or {}
        profile_name = profile_summary.get("name")
        profile_mode = profile_summary.get("filename_mode")

        if profile_name:
            policy = (
                f"Profile default, resolved from "
                f"{profile_name}"
                + (
                    f" ({profile_mode})"
                    if profile_mode
                    else ""
                )
            )

    unchanged = (
        current_name == result_name if result_name else False
    )

    return f"""
<section class="card">
  <div class="card-head"><h2>Filename</h2></div>
  {facts([
      ("Current file", esc(current_name or "-")),
      ("Identified media", esc(identified)),
      ("Filename policy", esc(policy)),
      ("Result", esc(result_name or "-")),
  ])}
  <p class="muted">
    {"The filename is unchanged." if unchanged else "The filename changes only because the effective policy requires it."}
  </p>
</section>
"""


def _whatif_identification_card(plan, data):
    """
    Provider-identification evidence for new/unseen
    files (§2): candidate identity, lookups run,
    and corroboration or review reason. Empty for
    lineage-based plans without identification.
    """

    identification = plan.get("identification") or (
        data.get("plan") or {}
    ).get("identification")

    if not identification:
        return ""

    candidate = identification.get("candidate") or {}
    lookups = identification.get("lookups") or {}

    lookup_bits = "; ".join(
        f"{provider}: "
        f"{(info or {}).get('count', 0)} candidate(s)"
        + (
            f" ({(info or {}).get('error')})"
            if (info or {}).get("error")
            else ""
        )
        for provider, info in sorted(lookups.items())
    )

    return f"""
<section class="card">
  <div class="card-head"><h2>Identification</h2></div>
  {facts([
      ("Candidate", esc(
          f"{candidate.get('title') or '-'}"
          + (f" ({candidate.get('year')})" if candidate.get("year") not in (None, "") else "")
          + f" [{candidate.get('kind') or 'movie'}]"
      )),
      ("Provider lookups", esc(lookup_bits or "-")),
      ("Outcome", esc(identification.get("outcome") or "-")),
  ])}
  <p class="muted">{esc(identification.get("reason") or "")}</p>
</section>
"""


def _whatif_limited_card(plan, data):
    """
    New-file states (§16): known media, new file,
    limited proposal. Ephemeral (unseen-file) plans
    show LIMITED PROPOSAL with a scan handoff, never
    a system error. Pure presentation.
    """

    import os as _os

    if not plan.get("ephemeral"):
        return """
<section class="card">
  <div class="card-head"><h2>Library state</h2></div>
  <p><span class="badge current">KNOWN MEDIA</span></p>
  <p class="muted">NAMOA already has a lineage for this file.</p>
</section>
"""

    current = plan.get("current_path") or ""
    directory = _os.path.dirname(current)

    return f"""
<section class="card">
  <div class="card-head"><h2>Library state</h2></div>
  <p>
    <span class="badge stale">NEW FILE</span>
    <span class="badge stale">LIMITED PROPOSAL</span>
  </p>
  <p>
    NAMOA can analyse this file, but it has not yet
    been incorporated into the normal library
    lineage.
  </p>
  <p class="muted">
    This file has not yet been incorporated into
    NAMOA's normal library knowledge. The current
    result uses the evidence available from this
    file and configured provider lookups. Scanning
    can provide fuller lineage, analysis, metadata,
    provider association, and classification.
  </p>
  <form method="get" action="/organisation/scan-handoff"
        class="inline-form">
    <input type="hidden" name="dir" value="{esc(directory)}">
    <button class="btn small" type="submit">
      Scan this directory with NAMOA
    </button>
  </form>
</section>
"""


def render_organisation_whatif_result(data):
    plan = data.get("plan") or {}
    mutation = plan.get("mutation") or {}
    metadata = plan.get("metadata_cited") or {}
    association = plan.get("association") or {}

    state_key, state_title, state_headline = _whatif_state(
        plan
    )
    safety = _whatif_safety(plan)
    operation_label, operation_why = _whatif_operation(plan)
    missing = _whatif_missing(plan)

    media_id = data.get("media_id")

    if media_id:
        media_line = media_link(
            media_id, f"media {media_id}"
        )
    else:
        media_line = (
            '<span class="muted">new file, not yet in the '
            "NAMOA library</span>"
        )

    safety_items = "".join(
        f"<li>{'✓' if ok else '✗'} {esc(label)}</li>"
        for ok, label in safety
    )

    missing_html = ""

    if missing and state_key in (
        "review_required",
        "blocked",
        "no_rule",
    ):
        missing_rows = "".join(
            f"<li><strong>{esc(what)}</strong><br>"
            f"{esc(why)}</li>"
            for what, why in missing
        )
        missing_html = f"""
  <h3>Missing information</h3>
  <p class="muted">
    Cannot propose an organisation yet for these
    reasons:
  </p>
  <ul>{missing_rows}</ul>
"""

    friendly_category = (
        plan.get("category") or plan.get("classification") or "-"
    )

    naming_card = _whatif_naming_card(plan, data)
    identification_card = _whatif_identification_card(
        plan, data
    )
    limited_card = _whatif_limited_card(plan, data)

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>What-If file plan</h2>
    <p>{esc(state_title)}</p>
    {badge(plan.get("review_state") or "unknown", "stale")}
  </div>
  <p>{esc(state_headline)}</p>
  <p class="muted">
    This preview changed nothing. No proposal was persisted.
  </p>
</section>
<section class="card">
  <div class="card-head"><h2>File found</h2></div>
  {facts([
      ("Media", media_line),
      ("Current path", esc(plan.get("current_path") or "")),
      ("Source", esc(_dirname(plan.get("current_path")) or "")),
  ])}
</section>
{identification_card}
{naming_card}
{limited_card}
<section class="card">
  <div class="card-head"><h2>Media understanding</h2></div>
  {facts([
      ("Type", esc(_whatif_human_type(plan))),
      ("Confidence", esc(plan.get("confidence"))),
  ])}
  <p class="muted">Why: {esc("; ".join(plan.get("reasoning") or [])[:400] or "filename evidence")}</p>
</section>
{_metadata_evidence_card(plan, data.get("metadata_scope"))}
<section class="card">
  <div class="card-head"><h2>Classification</h2></div>
  {facts([
      ("Category", esc(friendly_category)),
      ("Matched rule", esc((plan.get("matched_rule") or {}).get("description") or "baseline media-kind rule")),
      ("Matched rule detail", esc("; ".join(plan.get("mappings_applied") or []) or "; ".join(plan.get("rules_applied") or []) or "baseline media-kind rule")),
  ])}
</section>
<section class="card">
  <div class="card-head"><h2>Destination</h2></div>
  {facts([
      ("Destination", esc(friendly_category)),
      ("Destination root", esc(plan.get("destination_root") or "-")),
      ("Resolved root token", esc(plan.get("destination_token") or "-")),
  ])}
</section>
<section class="card">
  <div class="card-head"><h2>Folder structure</h2></div>
  <p><code>{esc(plan.get("template") or "-")}</code></p>
  <h3>Proposed structure</h3>
  {_structure_preview([(
      plan.get("current_path"),
      plan.get("expected_destination"),
  )], limit=1)}
  <h3>Proposed path</h3>
  <p><code>{esc(plan.get("expected_destination") or "(no destination)")}</code></p>
</section>
<section class="card">
  <div class="card-head"><h2>Safety</h2></div>
  <ul class="checklist">{safety_items}</ul>
  {missing_html}
</section>
<section class="card">
  <div class="card-head"><h2>Planned operation</h2></div>
  <p><strong>{esc(operation_label)}</strong></p>
  <p>{esc(operation_why)}</p>
  <h3>What happens on execution</h3>
  <p>{esc(_whatif_execution_note(state_key))}</p>
  <p class="muted">
    What-If itself never modifies anything.
  </p>
  <p><a class="btn small ghost" href="/organisation/whatif">Back to What-If</a></p>
</section>
<section class="card">
  <div class="card-head"><h2>Technical details</h2></div>
  <details class="disclosure">
    <summary>Rules applied</summary>
    <ul>{''.join(f'<li>{esc(rule)}</li>' for rule in plan.get("rules_applied") or []) or '<li>No rules applied</li>'}</ul>
  </details>
  <details class="disclosure">
    <summary>Tag mappings applied</summary>
    <ul>{''.join(f'<li>{esc(item)}</li>' for item in plan.get("mappings_applied") or []) or '<li>No mappings applied</li>'}</ul>
  </details>
  <details class="disclosure">
    <summary>Reasoning</summary>
    <ul>{''.join(f'<li>{esc(line)}</li>' for line in plan.get("reasoning") or []) or '<li>No reasoning recorded</li>'}</ul>
  </details>
  <details class="disclosure">
    <summary>Metadata cited (technical)</summary>
    <pre>{esc(json_format(metadata))}</pre>
  </details>
  <details class="disclosure">
    <summary>Association (technical)</summary>
    <pre>{esc(json_format(association))}</pre>
  </details>
</section>
"""

    return layout(
        "Organisation What-If result",
        "organisation",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def _structure_preview(pairs, *, limit=10):
    """
    Visual folder-tree preview derived from actual plan
    results. Each pair is (current_path,
    expected_destination); both trees group by parent
    directory and cap at `limit` entries with an honest
    overflow note. Pure formatting of caller data.
    """

    import os as _os

    current_groups = {}
    proposed_groups = {}
    shown = 0
    total = 0

    for current, expected in pairs:
        total += 1

        if shown >= limit:
            continue

        shown += 1
        current_groups.setdefault(
            _os.path.dirname(current or "") or "(unknown)",
            [],
        ).append(_os.path.basename(current or ""))

        if expected:
            proposed_groups.setdefault(
                _os.path.dirname(expected) or "(unknown)",
                [],
            ).append(_os.path.basename(expected))
        else:
            proposed_groups.setdefault(
                "(no change proposed)", []
            ).append(_os.path.basename(current or ""))

    def _tree(groups):
        blocks = []

        for folder in sorted(groups):
            files = "".join(
                f"<li>{esc(name or '(unnamed)')}</li>"
                for name in sorted(groups[folder])[:8]
            )

            blocks.append(
                f"<li><strong>{esc(folder)}</strong>"
                f"<ul>{files}</ul></li>"
            )

        return "".join(blocks) or "<li>No items.</li>"

    overflow = (
        f"<p class=\"muted\">Showing {shown} of {total} "
        f"planned items.</p>"
        if total > shown
        else ""
    )

    return f"""
<div class="structure-preview">
  <div class="structure-col">
    <h3>Current library</h3>
    <ul class="file-tree">{_tree(current_groups)}</ul>
  </div>
  <div class="structure-col">
    <h3>Proposed organisation</h3>
    <ul class="file-tree">{_tree(proposed_groups)}</ul>
  </div>
</div>
{overflow}
"""


def render_organisation_scan_handoff(data):
    directory = data.get("directory") or ""

    content = f"""
<section class="card">
  <div class="card-head"><h2>Scan this directory with NAMOA?</h2></div>
  <p><code>{esc(directory)}</code></p>
  <p>
    NAMOA will run the normal library scan for this
    directory. This can add lineage, analysis and
    provider associations. It does not move or
    rename files.
  </p>
  <form method="post" action="/organisation/scan-handoff"
        class="inline-form">
    <input type="hidden" name="dir" value="{esc(directory)}">
    <input type="hidden" name="confirm" value="yes">
    <button class="btn" type="submit">Confirm scan</button>
    <a class="btn small ghost" href="/organisation/whatif">
      Cancel
    </a>
  </form>
  <p class="muted">
    Confirming takes you to the existing scan page
    with this path already entered, and the normal
    scan starts automatically. Progress shows
    there, and you can return to What-If after.
  </p>
</section>
"""

    return layout(
        "Organisation scan handoff",
        "organisation",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def render_organisation_sampler_result(data):
    sample = data.get("sample") or {}
    rows = sample.get("rows") or []
    directory = (
        sample.get("directory") or data.get("directory") or ""
    )

    body_rows = []

    for row in rows:
        plan = row.get("plan") or {}
        path = row.get("path") or ""
        filename = path.rsplit("/", 1)[-1]
        summary = plan.get("metadata_summary") or {}
        title = summary.get("title")
        year = summary.get("year")
        identified = (
            f"{title} ({year})"
            if title and year not in (None, "")
            else (title or "Unknown")
        )

        if row.get("media_id") is None and plan:
            body_rows.append(f"""
<tr>
  <td><code class="path-wrap">{esc(filename)}</code>
    <details class="disclosure">
      <summary>Full path</summary>
      <code class="path-wrap">{esc(path)}</code>
    </details>
  </td>
  <td>{esc(_whatif_human_type(plan))}</td>
  <td>{esc(identified)}</td>
  <td>{esc(plan.get("confidence") if plan.get("confidence") is not None else "")}</td>
  <td><span class="badge stale">LIMITED PROPOSAL</span></td>
  <td class="muted">New file, planned from file evidence.</td>
</tr>""")
            continue

        if row.get("media_id") is None:
            body_rows.append(f"""
<tr>
  <td><code class="path-wrap">{esc(filename)}</code>
    <details class="disclosure">
      <summary>Full path</summary>
      <code class="path-wrap">{esc(path)}</code>
    </details>
  </td>
  <td colspan="5" class="muted">{esc(row.get("reason") or "not sampled")}</td>
</tr>""")
            continue

        reasoning = plan.get("reasoning") or []
        first_reason = reasoning[0] if reasoning else "-"
        extra = len(reasoning) - 1

        reason_cell = esc(first_reason)

        if extra > 0:
            reason_cell += f' <span class="muted">(+{extra} more)</span>'

        body_rows.append(f"""
<tr>
  <td><code class="path-wrap">{esc(filename)}</code>
    <details class="disclosure">
      <summary>Full path</summary>
      <code class="path-wrap">{esc(path)}</code>
    </details>
  </td>
  <td>{esc(_whatif_human_type(plan))}</td>
  <td>{esc(identified)}</td>
  <td>{esc(plan.get("confidence") if plan.get("confidence") is not None else "")}</td>
  <td>{esc(plan.get("review_state") or "")}</td>
  <td>{reason_cell}</td>
</tr>""")

    content = f"""
<section class="card">
  <div class="card-head"><h2>Directory sample</h2></div>
  {facts([
      ("Directory", esc(directory)),
      ("Scope", "Supported video files only"),
      ("Sample size", esc(len(rows))),
      ("Seed", esc(sample.get("seed"))),
  ])}
  <p class="muted">
    Only supported video files are considered by this
    sampler. Other file types are outside its search
    scope.
  </p>
  <h3>Proposed structure</h3>
  <p class="muted">
    Built from the actual plan results below using the
    selected profile. Detailed reasoning stays in the
    table.
  </p>
  {_structure_preview([
      (
          row.get("path"),
          (row.get("plan") or {}).get(
              "expected_destination"
          ),
      )
      for row in rows
      if (row.get("plan") or {}).get(
          "expected_destination"
      )
  ])}
  <div class="table-wrap sample-list">
  <table class="data-table">
    <thead><tr>
      <th>Filename</th><th>Media type</th>
      <th>Identification</th><th>Confidence</th>
      <th>Organisation status</th><th>Why</th>
    </tr></thead>
    <tbody>{''.join(body_rows) or '<tr><td colspan="6" class="muted">No rows sampled.</td></tr>'}</tbody>
  </table>
  </div>
  <form method="get" action="/organisation/scan-handoff"
        class="inline-form">
    <input type="hidden" name="dir" value="{esc(directory)}">
    <button class="btn small" type="submit">
      Scan this directory with NAMOA
    </button>
  </form>
  <form method="post" action="/organisation/whatif/sample">
    <input type="hidden" name="directory"
           value="{esc(data.get("directory") or "")}">
    <input type="hidden" name="limit"
           value="{esc(data.get("limit") or 10)}">
    <p class="muted">
      Test Again runs a fresh sample: leave the seed blank
      for a new random seed.
    </p>
    <button class="btn small" type="submit">Test Again</button>
  </form>
  <p><a class="btn small ghost" href="/organisation/whatif">Back to What-If</a></p>
</section>
"""

    return layout(
        "Organisation sampler result",
        "organisation",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def render_organisation_reconcile(data):
    profiles = data.get("profiles") or []
    entered = data.get("input") or {}

    scope_value = esc(entered.get("scope") or "")

    content = f"""
<section class="card">
  <div class="card-head"><h2>Library reconciliation</h2></div>
  <div class="info-panel">
    <p><strong>How this works:</strong></p>
    <ol class="workflow-steps">
      <li>Choose the scope directory and the profile.</li>
      <li>Preview performs read-only planning. It never
      modifies files.</li>
      <li>Preflight checks the selected setup.</li>
      <li>Approval records your intent for actionable
      items.</li>
      <li>Execution applies approved changes only.</li>
      <li>Verification confirms filesystem results.</li>
      <li>History and recovery remain available
      afterwards.</li>
    </ol>
  </div>
  {_form_error_panel(data)}
  <form method="post" action="/organisation/reconcile/preview"
        class="org-form">
    <label>Scope path
      <input type="text" name="scope" id="reconcile-scope"
             placeholder="/media/library" value="{scope_value}">
    </label>
    {folder_browser_block("reconcile-scope", "reconcile-scope")}
    <p class="field-hint">
      Browse to navigate directories, select the folder to
      organise, then preview. Check it first with
      preflight when unsure.
    </p>
    <label>Profile
      <select name="profile_id">
        {_profile_options(profiles)}
      </select>
    </label>
    <div class="actions-row">
      <button class="btn small" type="submit">
        Preview scope (no changes)
      </button>
      <a class="btn small ghost"
         href="/organisation/preflight">View preflight checks</a>
    </div>
  </form>
</section>
"""

    return layout(
        "Organisation reconciliation",
        "organisation",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def render_organisation_reconcile_preview(data):
    preview = data.get("preview") or {}
    file_plans = preview.get("file_plans") or []
    structural = preview.get("structural_actions") or []
    review = preview.get("review_conditions") or []

    file_rows = []

    for plan in file_plans:
        mutation = plan.get("mutation") or {}
        reasoning = plan.get("reasoning") or []
        first_reason = reasoning[0] if reasoning else "-"

        file_rows.append({
            "folder": _dirname(
                plan.get("expected_destination") or ""
            ),
            "html": f"""
<tr>
  <td>{media_link(plan.get("media_id"), f'media {plan.get("media_id")}')}</td>
  <td>{esc(plan.get("current_path") or "")}</td>
  <td>{esc(plan.get("expected_destination") or "")}</td>
  <td>{esc(plan.get("classification") or "")}</td>
  <td>{esc(mutation.get("strategy") or "")}</td>
  <td>{esc(first_reason)}</td>
  <td>{esc(plan.get("review_state") or "")}</td>
</tr>""",
        })

    # Destination-folder grouping (§19): rows headed
    # for the same folder preview as one set (a
    # series season lands together), straight from
    # the planner's own destinations. No profile
    # rules needed per show.
    buckets: dict = {}

    for row in file_rows:
        buckets.setdefault(
            row["folder"] or "(no destination)", []
        ).append(row["html"])

    grouped = []

    for folder in sorted(buckets):
        members = buckets[folder]
        grouped.append(
            f'<tr class="group-head"><td colspan="7">'
            f'<code>{esc(folder)}</code> '
            f'{badge(f"{len(members)} files", "current")}'
            f'</td></tr>'
        )
        grouped.extend(members)

    mode_labels = {
        "keep": "Organise folders only (keep filenames)",
        "clean": "Organise + clean filenames",
        "extended": "Organise + extended filenames",
        "template": "Custom filename pattern",
    }
    run_mode = mode_labels.get(
        data.get("filename_mode") or "keep",
        "Organise folders only (keep filenames)",
    )

    structural_rows = "".join(
        f"""
<tr>
  <td>{esc(item.get("action_type"))}</td>
  <td>{esc(item.get("source_path"))}</td>
  <td>{esc(item.get("destination_path"))}</td>
  <td>{esc(item.get("operation_count", 0))}</td>
</tr>"""
        for item in structural
    )

    profile_id = data.get("profile_id")

    hidden_profile = (
        f'<input type="hidden" name="profile_id" '
        f'value="{profile_id}">'
        if profile_id is not None
        else ""
    )

    content = f"""
<section class="card">
  <div class="card-head"><h2>Scope preview (not persisted)</h2></div>
  {facts([
      ("Scope", esc(data.get("scope") or "")),
      ("Strategy", esc(preview.get("strategy") or "")),
      ("Operation count", esc(preview.get("operation_count", 0))),
      ("Run mode", esc(run_mode)),
  ])}
  <details class="disclosure">
    <summary>Reasoning</summary>
    <ul>{''.join(f'<li>{esc(line)}</li>' for line in preview.get("reasoning") or []) or '<li>No reasoning recorded</li>'}</ul>
  </details>
  <details class="disclosure">
    <summary>Review conditions</summary>
    <ul>{''.join(f'<li>{esc(line)}</li>' for line in review) or '<li>No review conditions</li>'}</ul>
  </details>
</section>
<section class="card">
  <div class="card-head"><h2>How this scope is organised</h2></div>
  <p class="muted">
    Structural moves are preferred where one directory
    operation achieves the desired result instead of many
    individual file moves. The counts below show exactly
    what confirming would accept: no file is touched in
    this preview step.
  </p>
  {facts([
      ("Strategy", esc(preview.get("strategy") or "")),
      ("Total operations", esc(preview.get("operation_count", 0))),
      ("Structural actions", esc(len(structural))),
      ("File-level plans", esc(len(file_rows))),
  ])}
</section>
<section class="card">
  <div class="card-head">
    <h2>File rows ({len(file_rows)}, grouped by destination folder)</h2>
  </div>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr>
      <th>Media</th><th>Current</th><th>Expected</th>
      <th>Classification</th><th>Strategy</th><th>Why</th><th>Review</th>
    </tr></thead>
    <tbody>{''.join(grouped) or '<tr><td colspan="7" class="muted">No file plans.</td></tr>'}</tbody>
  </table>
  </div>
</section>
<section class="card">
  <div class="card-head">
    <h2>Structural actions ({len(structural)})</h2>
  </div>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr>
      <th>Type</th><th>Source</th><th>Destination</th><th>Ops</th>
    </tr></thead>
    <tbody>{structural_rows or '<tr><td colspan="4" class="muted">No structural actions.</td></tr>'}</tbody>
  </table>
  </div>
  <form method="post" action="/organisation/reconcile/confirm-acceptance">
    <input type="hidden" name="scope"
           value="{esc(data.get("scope") or "")}">
    {hidden_profile}
    <p class="muted">
      Confirming persists a fresh reconciliation run over
      this scope and accepts every actionable proposal and
      scope action from that run, with per-item results.
      Nothing is executed: acceptance records approved
      intent only.
    </p>
    <button class="btn" type="submit">
      Generate and accept all actionable items
    </button>
    <a class="btn small ghost" href="/organisation/reconcile">Cancel</a>
  </form>
</section>
"""

    return layout(
        "Organisation reconciliation preview",
        "organisation",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def render_organisation_reconcile_report(data):
    summary = data.get("summary") or {}
    acceptance = data.get("acceptance") or {}

    accepted_proposals = (
        acceptance.get("accepted_proposals") or []
    )
    refused_proposals = (
        acceptance.get("refused_proposals") or []
    )
    accepted_scopes = (
        acceptance.get("accepted_scope_actions") or []
    )
    refused_scopes = (
        acceptance.get("refused_scope_actions") or []
    )

    proposal_rows = "".join(
        f"""
<tr>
  <td>{link(f"/organisation/proposals/{entry['proposal_id']}", f'Proposal #{entry["proposal_id"]}')}</td>
  <td>{media_link(entry["media_id"], f'media {entry["media_id"]}')}</td>
  <td>{badge("Accepted intent", "current")}</td>
</tr>"""
        for entry in accepted_proposals
    )

    refused_proposal_rows = "".join(
        f"""
<tr>
  <td>proposal {entry.get("proposal_id")}</td>
  <td class="muted">{esc(entry.get("reason"))}</td>
</tr>"""
        for entry in refused_proposals
    )

    scope_rows = "".join(
        f"""
<tr>
  <td>{link(f"/organisation/scope-actions/{entry['id']}", f'Scope action #{entry["id"]}')}</td>
  <td>{esc(entry.get("action_type"))}</td>
  <td>{badge("Accepted intent", "current")}</td>
</tr>"""
        for entry in accepted_scopes
    )

    refused_scope_rows = "".join(
        f"""
<tr>
  <td>scope action {entry.get("scope_action_id")}</td>
  <td class="muted">{esc(entry.get("reason"))}</td>
</tr>"""
        for entry in refused_scopes
    )

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Reconciliation acceptance recorded</h2>
    <span class="badge current">
      {len(accepted_proposals) + len(accepted_scopes)} accepted
    </span>
  </div>
  {facts([
      ("Scope", esc(data.get("scope") or "")),
      ("Decision run", esc(summary.get("decision_run_id"))),
      ("Strategy", esc(summary.get("strategy") or "")),
      ("Proposals persisted", esc(len(summary.get("proposal_ids") or []))),
      ("Scope actions persisted", esc(len(summary.get("scope_action_ids") or []))),
      ("Run mode", esc({
          "keep": "Organise folders only (keep filenames)",
          "clean": "Organise + clean filenames",
          "extended": "Organise + extended filenames",
          "template": "Custom filename pattern",
      }.get(data.get("filename_mode") or "keep"))),
  ])}
  <p class="muted">
    Acceptance records approved intent only. No file was
    moved, renamed, created, or deleted.
  </p>
  <div class="info-panel">
    <p><strong>Next steps:</strong></p>
    <ol class="workflow-steps">
      <li>Open each accepted scope action below to review
      its exact source, destination and operation
      count.</li>
      <li>Accept any action still proposed. Accepted
      actions unlock Execute.</li>
      <li>Execute runs the approved move through the
      existing execution authority with verification.
      Nothing runs without this explicit step.</li>
      <li>Follow progress under Organisation then
      Executions; history and recovery live under
      History.</li>
    </ol>
  </div>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr><th>Proposal</th><th>Media</th><th>Result</th></tr></thead>
    <tbody>{proposal_rows or '<tr><td colspan="3" class="muted">No proposals accepted.</td></tr>'}</tbody>
  </table>
  </div>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr>
      <th>Scope action</th><th>Type</th><th>Result</th>
    </tr></thead>
    <tbody>{scope_rows or '<tr><td colspan="3" class="muted">No scope actions accepted.</td></tr>'}</tbody>
  </table>
  </div>
  <p>
    <a class="btn small ghost" href="/organisation">Back to organisation</a>
    <a class="btn small" href="/organisation/executions">View executions</a>
    <a class="btn small" href="/organisation/scope-executions">View history</a>
  </p>
</section>
"""

    if refused_proposal_rows or refused_scope_rows:
        content += f"""
<section class="card">
  <div class="card-head"><h2>Not accepted</h2></div>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr><th>Selection</th><th>Reason</th></tr></thead>
    <tbody>{refused_proposal_rows}{refused_scope_rows}</tbody>
  </table>
  </div>
</section>
"""

    return layout(
        "Organisation reconciliation recorded",
        "organisation",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def render_organisation_preflight(data):
    preflight = data.get("preflight") or {}
    checks = preflight.get("checks") or []
    profiles = data.get("profiles") or []

    rows = []

    for check in checks:
        ok = bool(check.get("ok"))
        level = str(check.get("level") or "").lower()

        if ok:
            state = badge("pass", "current")
        elif level == "warning":
            state = badge("warning", "stale")
        else:
            state = badge("blocked", "failed")

        rows.append(f"""
<tr>
  <td>{state}</td>
  <td>{esc(check.get("name"))}</td>
  <td>{esc(check.get("message") or "")}</td>
</tr>""")

    scope_value = esc(data.get("scope") or "")
    selected_profile = data.get("profile_id")

    content = f"""
<section class="card">
  <div class="card-head"><h2>Organisation preflight</h2></div>
  <div class="info-panel">
    <p>
      Advisory validation-only checks over the setup you
      are about to use: pick the profile and scope first,
      then run. Read-only; nothing is probed or changed.
      Execution-time validation remains authoritative.
    </p>
  </div>
  {_form_error_panel(data)}
  <form method="post" action="/organisation/preflight/run"
        class="org-form">
    <label>Profile
      <select name="profile_id">
        {_profile_options(profiles, selected=selected_profile)}
      </select>
    </label>
    <label>Scope path (blank uses the profile roots)
      <input type="text" name="scope" id="preflight-scope"
             value="{scope_value}" placeholder="/media/library">
    </label>
    {folder_browser_block("preflight-scope", "preflight-scope")}
    <p class="field-hint">
      Browse to choose the directory to check, or leave
      blank to check the profile roots.
    </p>
    <div class="actions-row run-row">
      <button class="btn small" type="submit">Run preflight checks</button>
    </div>
  </form>
</section>
<section class="card">
  <div class="card-head"><h2>Checks ({len(rows)})</h2></div>
  {facts([
      ("Profile", esc(str(selected_profile) if selected_profile is not None else "default")),
      ("Scope", esc(data.get("scope") or "profile roots")),
  ])}
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr><th>Check</th><th>Name</th><th>Detail</th></tr></thead>
    <tbody>{''.join(rows) or '<tr><td colspan="3" class="muted">No checks reported.</td></tr>'}</tbody>
  </table>
  </div>
  <p><a class="btn small ghost" href="/organisation/reconcile">Back to reconciliation</a></p>
</section>
"""

    return layout(
        "Organisation preflight",
        "organisation",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def render_organisation_scope_action_detail(data):
    action = data["action"]
    events = data.get("events") or []
    manifest = action.get("descendant_manifest") or []
    descendants = action.get("descendant_proposal_ids") or []

    accept_form = ""

    if action.get("state") == "proposed":
        accept_form = f"""
  <form method="post"
        action="/organisation/scope-actions/{action["id"]}/accept"
        class="inline-form">
    <button class="btn small" type="submit">
      Accept scope action (accepts covered proposals)
    </button>
    <span class="muted">
      Records approved intent only. No file is changed in
      this step.
    </span>
  </form>
"""

    execute_form = ""

    if action.get("state") == "accepted":
        execute_form = f"""
  <form method="post"
        action="/organisation/scope-actions/{action["id"]}/execute"
        class="inline-form">
    <button class="btn small btn-warn" type="submit">
      Execute approved scope action
    </button>
    <span class="muted">
      Moves the approved directory through the existing
      execution authority with verification.
    </span>
  </form>
"""

    manifest_rows = "".join(
        f"""
<tr>
  <td>{esc(item.get("media_id"))}</td>
  <td>{esc(item.get("relative_path"))}</td>
</tr>"""
        for item in manifest
        if isinstance(item, dict)
    )

    descendant_rows = "".join(
        f"""
<tr>
  <td>{link(f"/organisation/proposals/{proposal_id}", f"Proposal #{proposal_id}")}</td>
</tr>"""
        for proposal_id in descendants
    )

    event_rows = "".join(
        f"""
<tr>
  <td>{badge(event["new_state_label"], event["new_state_badge"])}</td>
  <td>{esc(event["actor"])}</td>
  <td>{esc(event["detail"] or "")}</td>
  <td>{esc(event["created_at"])}</td>
</tr>"""
        for event in events
    )

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Scope action #{action["id"]}</h2>
    {badge(action["state_label"], action["state_badge"])}
  </div>
  {facts([
      ("Action type", esc(action.get("action_type"))),
      ("Scope path", esc(action.get("scope_path") or "")),
      ("Source", esc(action.get("source_path") or "")),
      ("Destination", esc(action.get("destination_path") or "")),
      ("Strategy", esc(action.get("strategy") or "")),
      ("Operation count", esc(action.get("operation_count", 0))),
      ("Decision run", esc(action.get("decision_run_id"))),
      ("Produced", esc(action.get("created_at"))),
  ])}
  {accept_form}
  {execute_form}
  <details class="disclosure">
    <summary>Reasoning</summary>
    <ul>{''.join(f'<li>{esc(line)}</li>' for line in action.get("reasoning") or []) or '<li>No reasoning recorded</li>'}</ul>
  </details>
  <details class="disclosure">
    <summary>Review conditions</summary>
    <ul>{''.join(f'<li>{esc(line)}</li>' for line in action.get("review_conditions") or []) or '<li>No review conditions</li>'}</ul>
  </details>
</section>
<section class="card">
  <div class="card-head">
    <h2>Descendant manifest ({len(manifest)})</h2>
  </div>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr><th>Media</th><th>Relative path</th></tr></thead>
    <tbody>{manifest_rows or '<tr><td colspan="2" class="muted">No descendants recorded.</td></tr>'}</tbody>
  </table>
  </div>
</section>
<section class="card">
  <div class="card-head">
    <h2>Covered proposals ({len(descendants)})</h2>
  </div>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr><th>Proposal</th></tr></thead>
    <tbody>{descendant_rows or '<tr><td class="muted">No covered proposals.</td></tr>'}</tbody>
  </table>
  </div>
</section>
<section class="card">
  <div class="card-head"><h2>Lifecycle events</h2></div>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr>
      <th>Event</th><th>Actor</th><th>Detail</th><th>When</th>
    </tr></thead>
    <tbody>{event_rows or '<tr><td colspan="4" class="muted">No events recorded.</td></tr>'}</tbody>
  </table>
  </div>
</section>
"""

    return layout(
        f"Organisation scope action #{action['id']}",
        "organisation",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def render_organisation_scope_executions(data):
    executions = data.get("executions") or []

    rows = "".join(
        f"""
<tr>
  <td>{link(f"/organisation/scope-executions/{execution['id']}", f'#{execution["id"]}')}</td>
  <td>{link(f"/organisation/scope-actions/{execution['scope_action_id']}", f'scope action {execution["scope_action_id"]}')}</td>
  <td>{badge(execution["state_label"], execution["state_badge"])}</td>
  <td>{esc(execution["action_type"])}</td>
  <td>{esc(execution["source_path"])}</td>
  <td>{esc(execution["destination_path"] or "-")}</td>
</tr>"""
        for execution in executions
    )

    if not executions:
        content = empty_state(
            "No scope executions yet",
            "Accept a scope action, then execute it. "
            "Nothing moves without your explicit action.",
        )
    else:
        content = f"""
<section class="card">
  <div class="card-head">
    <h2>Scope executions ({data.get("total_count", 0)})</h2>
  </div>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr>
      <th>Execution</th><th>Scope action</th><th>State</th>
      <th>Type</th><th>Source</th><th>Destination</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
  </div>
</section>
"""

    return layout(
        "Organisation scope executions",
        "organisation",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


def render_organisation_scope_execution_detail(data):
    execution = data["execution"]
    events = data.get("events") or []
    continuity = data.get("continuity") or []
    action = data.get("action")

    actions = []

    if execution["state"] in (
        "failed",
        "interrupted",
        "recovery_required",
    ):
        actions.append(f"""
  <form method="post"
        action="/organisation/scope-executions/{execution["id"]}/recover">
    <button class="btn small" type="submit">
      Recover against filesystem reality
    </button>
  </form>""")

    action_html = (
        "".join(actions) or "<p>No actions for this state.</p>"
    )

    fact_items = [
        ("Execution", f'#{execution["id"]}'),
        (
            "State",
            badge(
                execution["state_label"],
                execution["state_badge"],
            ),
        ),
        ("Action type", esc(execution["action_type"])),
        ("Source", esc(execution["source_path"])),
        (
            "Destination",
            esc(execution["destination_path"] or "-"),
        ),
        ("Actor", esc(execution["actor"])),
        ("Created", esc(execution["created_at"])),
        ("Last transition", esc(execution["updated_at"])),
    ]

    if action is not None:
        fact_items.append(
            (
                "Scope action",
                link(
                    f"/organisation/scope-actions/{action['id']}",
                    f"Scope action #{action['id']}",
                ),
            )
        )

    error_html = (
        f'<p class="muted">{esc(execution["error"])}</p>'
        if execution.get("error")
        else ""
    )

    event_rows = "".join(
        f"""
<tr>
  <td>{badge(event["new_state_label"], event["new_state_badge"])}</td>
  <td>{esc(event["actor"])}</td>
  <td>{esc(event["detail"] or "")}</td>
  <td>{esc(event["created_at"])}</td>
</tr>"""
        for event in events
    )

    continuity_rows = "".join(
        f"""
<tr>
  <td>{esc(entry.get("media_id"))}</td>
  <td>{esc(entry.get("source_observation_id"))}</td>
  <td>{esc(entry.get("result_observation_id"))}</td>
  <td>{badge("Verified", "current") if entry.get("result_observation_id") else badge("Pending", "pending")}</td>
</tr>"""
        for entry in continuity
        if isinstance(entry, dict)
    )

    verified_count = sum(
        1 for entry in continuity
        if isinstance(entry, dict)
        and entry.get("result_observation_id")
    )

    progress_html = ""

    if execution["state"] in ("pending", "running"):
        progress_html = """
<p class="muted">
  This scope execution is in progress. Item status below
  reflects persisted continuity records; refresh to update.
  <a class="btn small ghost" href="">Refresh status</a>
</p>"""

    content = f"""
<section class="card">
  <div class="card-head">
    <h2>Scope execution #{execution["id"]}</h2>
    {badge(execution["state_label"], execution["state_badge"])}
  </div>
  {progress_html}
  {error_html}
  {facts(fact_items)}
  {facts([
      ("Items completed", esc(verified_count)),
      ("Items recorded", esc(len(continuity))),
  ])}
  {action_html}
</section>
<section class="card">
  <div class="card-head"><h2>Lifecycle events</h2></div>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr>
      <th>Event</th><th>Actor</th><th>Detail</th><th>When</th>
    </tr></thead>
    <tbody>{event_rows or '<tr><td colspan="4" class="muted">No events recorded.</td></tr>'}</tbody>
  </table>
  </div>
</section>
<section class="card">
  <div class="card-head"><h2>Continuity</h2></div>
  <div class="table-wrap">
  <table class="data-table">
    <thead><tr>
      <th>Media</th><th>Source observation</th>
      <th>Result observation</th><th>Item status</th>
    </tr></thead>
    <tbody>{continuity_rows or '<tr><td colspan="4" class="muted">No continuity records.</td></tr>'}</tbody>
  </table>
  </div>
</section>
"""

    return layout(
        f"Organisation scope execution #{execution['id']}",
        "organisation",
        content,
        refreshed_at=data.get("refreshed_at"),
    )


# ---------------------------------------------------------
# Phase 16 preference experience.
#
# Pure formatting over handler-assembled page data. No
# intelligence here: coverage states, rules, suggestions, and
# session progress arrive already computed from the Phase 15
# backend; these renders only label and arrange them.
# ---------------------------------------------------------

_COVERAGE_LABELS = {
    "covered": ("Covered", "current"),
    "covered-explicit": ("Covered by explicit preference", "current"),
    "partial": ("Partially covered", "pending"),
    "ambiguous": ("Needs clarification", "unknown"),
    "uncovered": ("Not yet covered", "missing"),
}

_ANSWER_BADGE_KINDS = {
    "Keep": "current",
    "Balanced": "pending",
    "Optimise": "opportunity",
    "Leave-alone": "unknown",
}

_SUGGESTION_STATUS_LABELS = {
    "proposed": ("Suggested", "pending"),
    "accepted": ("Accepted", "current"),
    "rejected": ("Rejected", "failed"),
    "superseded": ("Superseded", "abandoned"),
}

_WIZARD_ANSWERS = [
    ("Keep", "Keep as is", "Prefer to preserve this kind of media."),
    (
        "Balanced",
        "Balanced",
        "A middle ground between quality and storage.",
    ),
    (
        "Optimise",
        "Optimise",
        "Prefer efficient storage for this kind of media.",
    ),
    (
        "Leave-alone",
        "Skip this",
        "No preference; leave this kind of media out of suggestions.",
    ),
]


def _coverage_badge(state):
    label, kind = _COVERAGE_LABELS.get(
        state, (state, "unknown")
    )

    return badge(label, kind)


def _answer_badge(answer):
    if not answer:
        return badge("Needs your choice", "unknown")

    return badge(answer, _ANSWER_BADGE_KINDS.get(answer, "unknown"))


def _suggestion_status_badge(status):
    label, kind = _SUGGESTION_STATUS_LABELS.get(
        status, (status, "unknown")
    )

    return badge(label, kind)


def _dimension_label(dimension):
    return {
        "media_type": "Media type",
        "resolution": "Resolution",
        "codec": "Codec",
        "bitrate_class": "Bitrate",
        "hdr": "HDR",
        "container": "Container",
        "category": "Category",
        "audio_codec": "Audio codec",
        "collection": "Collection",
        "tag": "Tag",
        "source_label": "Source",
        "size_class": "File size",
        "audio_channels": "Audio channels",
    }.get(dimension, dimension)


def _rule_conditions_html(rule):
    items = [
        (
            _dimension_label(condition["dimension"]),
            esc(str(condition["value"])),
        )
        for condition in rule.get("conditions", [])
    ]

    return facts(items)


def _candidate_facts_html(candidate):
    items = [
        (
            _dimension_label(item["dimension"]),
            esc(str(item["value"])),
        )
        for item in candidate.get("facts", [])
    ]

    return facts(items)


def _tier_explanation(tier, differing_dimension=None):
    if tier == 0:
        return (
            "NAMOA has no preference covering this kind of media "
            "yet, so your answer here is especially useful."
        )

    if tier == 1:
        return (
            "Your earlier answers point in different directions "
            "for this kind of media, so NAMOA needs your help to "
            "resolve it."
        )

    detail = ""

    if differing_dimension:
        detail = (
            " It differs from an existing preference only in "
            f"{_dimension_label(differing_dimension)}."
        )

    return (
        "This is close to something you already answered." + detail
    )


def _intent_summary_html(intent):
    return facts(
        [
            ("Compatibility", esc(intent.get("compatibility", ""))),
            (
                "Quality ceiling",
                esc(intent.get("quality_ceiling", "")),
            ),
            ("Optimisation", esc(intent.get("optimisation", ""))),
        ]
    )


def _intent_radio_group(name, title, options, current):
    boxes = "".join(
        f"<p><label>"
        f'<input type="radio" name="{name}" value="{esc(option)}"'
        f'{" checked" if option == current else ""}>'
        f"<strong>{esc(title_for)}</strong>"
        f"</label>"
        f'<span class="muted">{esc(hint)}</span>'
        f"</p>"
        for option, title_for, hint in options
    )

    return (
        f'<fieldset class="wizard-question">'
        f"<legend>{esc(title)}"
        f'<span class="muted section-sub">Choose the option that '
        f"best describes your preference.</span>"
        f"</legend>"
        f'<div class="radio-stack">{boxes}</div>'
        f"</fieldset>"
    )


def render_preferences(data):
    """
    Preferences launch/progress screen: Wizard purpose, durable
    progress, Continue/Reset, the run action, established
    preferences, and a compact coverage summary. Deliberately not a
    media browser or a second review dashboard: Review Suggestions
    owns review organisation.
    """

    intent = data.get("intent", {})

    rules = data.get("rules", [])

    coverage_states = data.get("coverage_states", {})

    progress = data.get("progress", {})

    intent_cards = "".join(
        stat_card(label, esc(intent.get(key, "")), hint=hint)
        for label, key, hint in [
            (
                "Compatibility",
                "compatibility",
                "How widely media should remain playable.",
            ),
            (
                "Quality ceiling",
                "quality_ceiling",
                "The highest quality worth keeping.",
            ),
            (
                "Optimisation",
                "optimisation",
                "How hard to pursue storage savings.",
            ),
        ]
    )

    if rules:
        rule_cards = "".join(
            f'<div class="card"><div class="card-head">'
            f"<h3>{_answer_badge(rule.get('answer'))}</h3>"
            f"</div>"
            f"{_rule_conditions_html(rule)}"
            f'<p class="muted">Based on '
            f"{len(rule.get('source_example_ids', []))} "
            f"approved example(s).</p></div>"
            for rule in rules
        )
    else:
        rule_cards = empty_state(
            "No established preferences",
            "Nothing has been accepted yet. The wizard is the "
            "way to establish preferences.",
        )

    state_cards = "".join(
        stat_card(
            label,
            str(coverage_states.get(state, 0)),
            hint="files",
        )
        for state, (label, _kind) in _COVERAGE_LABELS.items()
    )

    if progress.get("has_progress"):
        last = (
            progress.get("last_file_name")
            or progress.get("last_media_id")
        )

        last_line = (
            f'<p class="muted">Last considered: '
            f"<strong>{esc(str(last))}</strong></p>"
            if last
            else ""
        )

        complete_line = (
            "<p class=\"muted\">Every currently eligible media "
            "item has been answered. Continuing will show the "
            "coverage state.</p>"
            if progress.get("completed")
            else ""
        )

        progress_block = f"""
<div class="card wizard-launch-progress"><div class="card-head"><h2>Wizard progress</h2></div>
<div class="stat-grid">
{stat_card("Media items considered", str(progress.get("answered", 0)))}
</div>
<p><strong>Continue where you left off.</strong></p>
{last_line}
{complete_line}
<div class="actions-row">
<form method="post" action="/preferences/wizard/start">
<input type="hidden" name="mode" value="continue">
<button class="btn btn-wizard-magic" type="submit">Continue Preferences Wizard</button>
</form>
<form method="post" action="/preferences/wizard/reset">
<button class="btn ghost" type="submit">Reset Wizard</button>
</form>
</div>
<p class="muted">Reset Wizard clears Wizard progress only. Your
accepted preferences, review history, execution history, imported
files, and file lineage are never deleted.</p>
</div>
"""
    else:
        progress_block = ""

    # "Run Preferences Wizard" is a first-run action. When durable
    # Wizard progress exists, continuation is offered by the progress
    # area instead, so the two actions never compete. Progress comes
    # from the existing authoritative durable state, never from UI
    # history.
    run_action = (
        ""
        if progress.get("has_progress")
        else (
            '<a class="btn btn-wizard-magic" '
            'href="/preferences/wizard">Run Preferences Wizard</a>'
        )
    )

    content = f"""
<div class="card"><div class="card-head"><h2>Your media preferences</h2></div>
<p>NAMOA learns these only from your explicit answers and
approvals. Nothing here is guessed, and nothing is applied
without your acceptance.</p>
<div class="actions-row">
{run_action}
<a class="btn ghost" href="/preferences/review">Review suggestions</a>
</div>
</div>

{progress_block}

<div class="card"><div class="card-head"><h2>Coverage summary</h2></div>
<div class="stat-grid">{state_cards}</div>
<p class="muted">Library files analysed: {data.get("population_total", 0)}.
Files still needing analysis: {data.get("unusable", 0)}.</p>
</div>

<div class="card"><div class="card-head"><h2>Current intent</h2></div>
<div class="stat-grid">{intent_cards}</div>
<p class="muted">{esc(data.get("intent_note", ""))}</p>
</div>

<div class="card"><div class="card-head"><h2>Established preferences</h2></div>
<p class="muted">Accepted preferences ({len(rules)} rule(s),
{esc(str(data.get("accepted_examples", 0)))} approved example(s)).
These are the only preferences NAMOA applies.</p>
{rule_cards}
</div>
"""

    return layout(
        "Preferences", "preferences", content,
        refreshed_at=data.get("refreshed_at"),
    )


def _wizard_intro_html(data):
    vocab = data.get("vocab", {})

    defaults = vocab.get("defaults", {})

    established = data.get("established", {})

    progress = data.get("progress", {})

    coverage = data.get("coverage", {})

    states = coverage.get("states", {})

    coverage_cards = "".join(
        stat_card(label, str(states.get(state, 0)), hint="files")
        for state, (label, _kind) in _COVERAGE_LABELS.items()
    )

    if progress.get("has_progress"):
        last = (
            progress.get("last_file_name")
            or progress.get("last_media_id")
        )

        last_line = (
            f'<p class="muted">Last considered: '
            f"<strong>{esc(str(last))}</strong></p>"
            if last
            else ""
        )

        progress_block = f"""
<div class="card wizard-launch-progress"><div class="card-head"><h2>Wizard progress</h2></div>
<div class="stat-grid">
{stat_card("Media items considered", str(progress.get("answered", 0)))}
{stat_card("Established rules", str(established.get("rules", 0)))}
</div>
<p><strong>Continue where you left off.</strong></p>
{last_line}
<div class="actions-row">
<form method="post" action="/preferences/wizard/start">
<input type="hidden" name="mode" value="continue">
<button class="btn btn-wizard-magic" type="submit">Continue Preferences Wizard</button>
</form>
<form method="post" action="/preferences/wizard/reset">
<button class="btn ghost" type="submit">Reset Wizard</button>
</form>
</div>
<p class="muted">Reset Wizard clears Wizard progress only. Accepted
preferences, review history, execution history, imported files,
and file lineage are never deleted.</p>
</div>
"""
        start_label = "Continue with these choices"
        start_mode = "continue"
        restart_block = """
<div class="card"><div class="card-head"><h2>Start over instead</h2></div>
<p class="muted">Begin a fresh session and answer from the
beginning. Your established preferences and your durable Wizard
progress stay untouched unless you explicitly reset them.</p>
<form method="post" action="/preferences/wizard/start">
<input type="hidden" name="mode" value="fresh">
<input type="hidden" name="compatibility" value="Broad">
<input type="hidden" name="quality_ceiling" value="1080p">
<input type="hidden" name="optimisation" value="Balanced">
<p><button class="btn ghost" type="submit">Start over</button></p>
</form>
</div>
"""
    else:
        progress_block = ""
        start_label = "Start with my library"
        start_mode = "fresh"
        restart_block = ""

    return f"""
<div class="card"><div class="card-head"><h2>Set up your media preferences</h2></div>
<p>NAMOA will show you a few examples from your own library and
ask simple questions about what you prefer. Your answers help
NAMOA understand how you would like media organised and
optimised. You stay in control: every suggestion needs your
approval, and you can review or change anything later.</p>
</div>

{progress_block}

<div class="card"><div class="card-head"><h2>First, the big picture</h2></div>
<form method="post" action="/preferences/wizard/start">
<input type="hidden" name="mode" value="{start_mode}">
{_intent_radio_group(
    "compatibility",
    "How widely should your media remain compatible?",
    [
        ("Maximum", "Preserve compatibility",
         "Preserve compatibility as much as possible."),
        ("Broad", "Balanced (default)",
         "A good balance of compatibility and efficiency."),
        ("Efficient", "Efficiency first",
         "Prioritise storage efficiency when reasonable."),
    ],
    defaults.get("compatibility", "Broad"),
)}
{_intent_radio_group(
    "quality_ceiling",
    "What is the highest quality you generally want to keep?",
    [
        ("Original", "Original",
         "Keep media at its original quality."),
        ("4K", "4K",
         "Very high picture quality. Uses more storage."),
        ("1080p", "1080p (default)",
         "High quality with a good balance of quality and storage."),
        ("720p", "720p",
         "Basic HD quality. Uses considerably less storage."),
        ("EfficiencyFirst", "Efficiency first",
         "Save as much storage as reasonably possible."),
    ],
    defaults.get("quality_ceiling", "1080p"),
)}
{_intent_radio_group(
    "optimisation",
    "How aggressively should NAMOA optimise?",
    [
        ("Conservative", "Conservative",
         "Change only when the benefit is clear and risk is low."),
        ("Balanced", "Balanced (default)",
         "Balance storage savings, quality, and compatibility."),
        ("Aggressive", "Aggressive",
         "Prioritise storage savings when acceptable."),
    ],
    defaults.get("optimisation", "Balanced"),
)}
<p class="muted">These choices apply to this guided session.
Higher quality usually means a larger file. Quality ceilings
beyond Original do not currently change optimisation behaviour;
that limitation is architectural, not a setting to adjust
here.</p>
<p><button class="btn btn-wizard-magic" type="submit">{start_label}</button></p>
</form>
</div>
{restart_block}

<div class="card"><div class="card-head"><h2>Coverage summary</h2></div>
<div class="stat-grid">{coverage_cards}</div>
<p class="muted">Library files analysed: {coverage.get("population_total", 0)}.
Files still needing analysis: {coverage.get("unusable", 0)}.</p>
</div>
"""


def _wizard_question_html(data):
    candidate = data.get("candidate") or {}

    shown = data.get("file") or {}

    progress = data.get("progress", {})

    feedback = data.get("feedback", {})

    answered = progress.get("answered", 0)

    if answered <= 0:
        progress_text = "First example"
    elif answered == 1:
        progress_text = "1 example answered"
    else:
        progress_text = f"{answered} examples answered"

    buttons = "".join(
        f'<button type="submit" '
        f'name="answer" value="{value}"><strong>{esc(title)}</strong>'
        f'<span class="choice-hint">{esc(hint)}</span></button>'
        for value, title, hint in _WIZARD_ANSWERS
    )

    size = shown.get("file_size_bytes")

    size_text = (
        format_bytes(size) if size is not None else "Unknown size"
    )

    media_facts = [("File size", f"<strong>{esc(size_text)}</strong>")]

    media_facts.extend(
        (
            _dimension_label(item["dimension"]),
            esc(str(item["value"])),
        )
        for item in candidate.get("facts", [])
    )

    return f"""
<div class="card"><div class="card-head"><h2>What do you prefer here?</h2></div>
<div class="media-identity">
<h3 class="media-filename">{esc(shown.get("file_name") or candidate.get("media_id", ""))}</h3>
<p class="muted">Media</p>
</div>
<div class="facts">{facts(media_facts)}</div>
<div class="wizard-progress">
<div>
<p><span class="status-marker status-ready status-glimmer" aria-hidden="true">●</span><strong>{esc(progress_text)}</strong></p>
<p class="muted">You can stop whenever you like.
<button class="btn small ghost stop-inline" type="submit" form="stop-now-form">Stop now</button></p>
</div>
</div>
<form id="stop-now-form" method="post" action="/preferences/wizard/finish">
<input type="hidden" name="session_id" value="{esc(data.get("session_id", ""))}">
</form>
{_candidate_facts_html(candidate)}
<p>{esc(candidate.get("reason", ""))}</p>
<p class="muted">{esc(_tier_explanation(candidate.get("tier", 0), candidate.get("differing_dimension")))}</p>
<details class="disclosure"><summary>Your current session intent</summary>
{_intent_summary_html(data.get("intent", {}))}
</details>
<div class="wizard-question">
<div class="section-head"><div>
<h3>Your answer</h3>
<p class="muted section-sub">Choose the option that best matches
your preference. The Wizard will use your answers to build your
preferences.</p>
</div></div>
<form method="post" action="/preferences/wizard/answer">
<input type="hidden" name="session_id" value="{esc(data.get("session_id", ""))}">
<input type="hidden" name="media_id" value="{esc(candidate.get("media_id", ""))}">
<div class="choice-buttons">{buttons}</div>
</form>
</div>
<div class="actions-row">
<form method="post" action="/preferences/wizard/undo">
<input type="hidden" name="session_id" value="{esc(data.get("session_id", ""))}">
<button class="btn small ghost" type="submit">Back (change last answer)</button>
</form>
<form method="post" action="/preferences/wizard/finish">
<input type="hidden" name="session_id" value="{esc(data.get("session_id", ""))}">
<button class="btn small ghost" type="submit">Finish now</button>
</form>
<form method="post" action="/preferences/wizard/cancel">
<input type="hidden" name="session_id" value="{esc(data.get("session_id", ""))}">
<button class="btn small btn-danger" type="submit">Cancel (discard answers)</button>
</form>
</div>
</div>

<div class="card"><div class="card-head"><h2>What your answers establish</h2></div>
<div class="info-panel">
<p>NAMOA turns consistent answers into exact,
deterministic rules. Nothing is guessed: a broader preference
appears only after at least three consistent answers with no
contradictions.</p>
</div>
<div class="stat-grid">
{stat_card("Answers", str(feedback.get("answered", 0)))}
{stat_card("Rules so far", str(feedback.get("rules_compiled", 0)))}
</div>
</div>
"""


def _wizard_completion_html(data, *, sufficiency):
    answers = data.get("answers", [])

    rules = data.get("rules", [])

    if answers:
        answer_rows = [
            [
                esc(entry.get("file_name") or entry.get("media_id")),
                _answer_badge(entry.get("answer")),
            ]
            for entry in answers
        ]
        answer_block = table(["Media", "Your answer"], answer_rows)
    else:
        answer_block = empty_state(
            "No answers recorded",
            "There is nothing to save yet.",
        )

    if rules:
        rule_cards = "".join(
            f'<div class="card"><div class="card-head">'
            f"<h3>{_answer_badge(rule.get('answer'))}</h3>"
            f"</div>"
            f"{_rule_conditions_html(rule)}</div>"
            for rule in rules
        )
    else:
        rule_cards = empty_state(
            "No rules established",
            "Answer at least one question to establish a rule.",
        )

    if sufficiency:
        banner = (
            "<p><strong>NAMOA has enough to work with.</strong> "
            "The library is covered by what you answered.</p>"
        )
    elif data.get("early"):
        banner = (
            "<p><strong>You finished early.</strong> This reflects "
            "only the questions answered so far; it is not the "
            "same as full coverage. You can keep answering later "
            "from the review flow.</p>"
        )
    else:
        banner = ""

    save_form = ""

    if answers:
        save_form = f"""
<form method="post" action="/preferences/wizard/save">
<input type="hidden" name="session_id" value="{esc(data.get("session_id", ""))}">
<p><button class="btn" type="submit">Save answers for review</button></p>
<p class="muted">Saving proposes suggestions for review. Nothing
becomes a preference until you explicitly accept it there.</p>
</form>
"""

    return f"""
<div class="card"><div class="card-head"><h2>Setup complete</h2></div>
{banner}
<p class="muted">Your answers have been recorded for this session.
What happens next depends on the approved persistence contract:
saving proposes suggestions, and only your explicit acceptance
makes anything an established preference.</p>
{answer_block}
<h3>Rules your answers establish</h3>
{rule_cards}
{save_form}
<p><a class="btn ghost" href="/preferences/review">Go to review</a>
<a class="btn ghost" href="/preferences">Preference Centre</a></p>
</div>
"""


def _wizard_saved_html(data):
    rules = data.get("rules", [])

    return f"""
<div class="card"><div class="card-head"><h2>Answers saved for review</h2></div>
<p>{esc(str(data.get("generated", 0)))} suggestion(s) were
generated from {len(rules)} rule(s). They now await your explicit
review: nothing was accepted automatically.</p>
<p><a class="btn" href="/preferences/review">Review suggestions</a>
<a class="btn ghost" href="/preferences">Preference Centre</a></p>
</div>
"""


def render_preferences_wizard(data):
    """Wizard: intro, question, sufficiency, completion, saved."""

    mode = data.get("mode", "intro")

    error_panel = _form_error_panel(data)

    if mode == "question":
        body = _wizard_question_html(data)
    elif mode == "sufficient":
        body = _wizard_completion_html(data, sufficiency=True)
    elif mode == "complete":
        body = _wizard_completion_html(data, sufficiency=False)
    elif mode == "saved":
        body = _wizard_saved_html(data)
    elif mode == "cancelled":
        body = """
<div class="card"><div class="card-head"><h2>Wizard cancelled</h2></div>
<p>Your answers were discarded. Nothing was saved or changed.</p>
<p><a class="btn ghost" href="/preferences/wizard">Start over</a>
<a class="btn ghost" href="/preferences">Preference Centre</a></p>
</div>
"""
    else:
        body = _wizard_intro_html(data)

    return layout(
        "Preference Wizard", "preferences", error_panel + body,
        refreshed_at=data.get("refreshed_at"),
    )


_OUTCOME_MEANINGS = {
    "Keep": (
        "Keep this file as-is",
        "Prefer to preserve this kind of media instead of "
        "converting it. Accepting records that preference; it "
        "does not convert the file.",
    ),
    "Balanced": (
        "Treat this file in a balanced way",
        "Aims to balance storage savings, quality, and "
        "compatibility rather than always choosing the smallest "
        "file. Accepting records the preference; it does not "
        "convert the file by itself.",
    ),
    "Optimise": (
        "Prefer efficient storage for this file",
        "Prefers efficient storage where the trade-off is "
        "acceptable. Accepting records that preference; any "
        "actual conversion still goes through NAMOA's normal "
        "optimisation review.",
    ),
    "Leave-alone": (
        "Leave this file out of suggestions",
        "Keeps this kind of media out of future suggestions "
        "without changing any analysis.",
    ),
}

_CHANGE_OPTIONS = ["Keep", "Balanced", "Optimise", "Leave-alone"]

# NOTE: _CHANGE_OPTIONS is retained only for backward compatibility of
# the historical review/change form vocabulary. The unified top-level
# decision controls are Accept / Reject / Manual Choice; Manual Choice
# is built from the shared recommendation fields (see
# _manual_choice_form_html).


def _current_facts_html(row):
    facts_map = row.get("facts")

    if not facts_map:
        return (
            '<p class="muted">Current file details are unavailable '
            "(the media may have moved since this was proposed).</p>"
        )

    items = []

    size = row.get("file_size_bytes")

    if size is not None:
        items.append(("File size", f"<strong>{esc(format_bytes(size))}</strong>"))

    for dimension in (
        "resolution",
        "codec",
        "bitrate_class",
        "container",
        "hdr",
        "audio_codec",
        "audio_channels",
        "size_class",
        "source_label",
    ):
        if dimension in facts_map:
            items.append(
                (
                    _dimension_label(dimension),
                    esc(str(facts_map[dimension])),
                )
            )

    return facts(items)


_CHIP_STATUS_LABELS = {
    "change": "CHANGE",
    "no-change": "NO CHANGE",
    "no-recommendation": "NO RECOMMENDATION",
}

#: Category accent classes for the summary chips. Colour is a secondary
#: cue only; the category label text already identifies the category.
#: Values map to existing theme tokens so both themes stay consistent.
_CHIP_CATEGORY_CLASSES = {
    "Video": "chip-cat-video",
    "Audio": "chip-cat-audio",
    "Picture": "chip-cat-picture",
    "Format": "chip-cat-format",
}


def _recommendation_chips_html(recommendation):
    """Compact per-file recommendation summary chips.

    Fields and values come from the existing recommendation context
    (surviving/preserving decision signals plus measured facts). The
    status label distinguishes CHANGE, NO CHANGE and NO RECOMMENDATION
    only where the underlying data supports that distinction. The
    category label carries a distinct accent per category so adjacent
    categories remain visually distinguishable.
    """

    recommendation = recommendation or {}

    fields = recommendation.get("fields") or []

    if not fields:
        return ""

    chips = []

    for field in fields:
        status = field.get("status") or "no-recommendation"

        category = field.get("category", "")

        category_class = _CHIP_CATEGORY_CLASSES.get(
            category, "chip-cat-other"
        )

        current = field.get("current")
        recommended = field.get("recommended")

        if status == "change" and recommended:
            value = (
                f'<span class="chip-current">'
                f"{esc(str(current)) if current else 'Unknown'}"
                f"</span>"
                f'<span class="chip-arrow" aria-hidden="true">→</span>'
                f'<span class="chip-target">{esc(str(recommended))}</span>'
            )
        elif current:
            value = f'<span class="chip-current">{esc(str(current))}</span>'
        else:
            value = '<span class="chip-current muted">Not measured</span>'

        chips.append(
            f'<div class="chip chip-{esc(status)} {category_class}">'
            f'<span class="chip-category">{esc(category)}</span>'
            f'<span class="chip-label">{esc(field.get("label", ""))}</span>'
            f'<span class="chip-value">{value}</span>'
            f'<span class="chip-status">{_CHIP_STATUS_LABELS.get(status, "")}</span>'
            f"</div>"
        )

    return (
        '<div class="recommendation-chips" '
        'aria-label="Recommendation summary">'
        + "".join(chips)
        + "</div>"
    )


def _manual_choice_form_html(
    row,
    recommendation,
    *,
    action,
    carousel_index=None,
):
    """Manual Choice editor, derived from the same recommendation fields.

    The controls and the summary chips share one field list
    (recommendation.fields). When the recommendation proposes concrete
    changes, each editable field offers the recommended or the current
    value; saving maps the selection through the existing review
    lifecycle (Superseded). When no change fields exist, the existing
    closed outcome vocabulary is offered instead.
    """

    suggestion = row.get("suggestion", {})

    suggestion_id = suggestion.get("suggestion_id", "")

    recommendation = recommendation or {}

    change_fields = [
        field
        for field in (recommendation.get("fields") or [])
        if field.get("status") == "change"
    ]

    index_input = (
        f'<input type="hidden" name="index" '
        f'value="{esc(str(carousel_index))}">'
        if carousel_index is not None
        else ""
    )

    if change_fields:
        controls = []

        for field in change_fields:
            key = field.get("key", "")

            controls.append(
                f'<fieldset class="wizard-question manual-field">'
                f"<legend>{esc(field.get('label', key))}"
                f'<span class="muted section-sub">'
                f"Recommended: {esc(str(field.get('recommended')))}"
                f" &middot; Current: "
                f"{esc(str(field.get('current') or 'Unknown'))}"
                f"</span></legend>"
                f'<div class="radio-stack">'
                f'<p><label><input type="radio" '
                f'name="field_{esc(key)}" value="recommended" checked>'
                f"<strong>Use recommended</strong> "
                f"{esc(str(field.get('recommended')))}</label></p>"
                f'<p><label><input type="radio" '
                f'name="field_{esc(key)}" value="current">'
                f"<strong>Keep current</strong> "
                f"{esc(str(field.get('current') or 'Unknown'))}</label></p>"
                f"</div></fieldset>"
            )

        controls.append(
            '<p class="manual-leave"><label>'
            '<input type="checkbox" name="leave_alone" value="1">'
            "Leave this file out of suggestions entirely"
            "</label></p>"
        )

        body = "".join(controls)
    else:
        options = "".join(
            f'<p><label><input type="radio" name="answer" '
            f'value="{value}"><strong>{esc(title)}</strong></label>'
            f'<span class="muted">{esc(hint)}</span></p>'
            for value, title, hint in _WIZARD_ANSWERS
        )

        body = (
            '<fieldset class="wizard-question manual-field">'
            "<legend>Choose the outcome you want"
            '<span class="muted section-sub">This file has no '
            "editable recommendation fields, so choose one of the "
            "existing outcomes.</span></legend>"
            f'<div class="radio-stack">{options}</div>'
            "</fieldset>"
        )

    return f"""
<form method="post" action="{esc(action)}" class="manual-choice-form">
{index_input}
<input type="hidden" name="suggestion_id" value="{esc(suggestion_id)}">
{body}
<p class="change-action"><button class="btn" type="submit">Save Choice</button></p>
</form>
"""


def _suggestion_card_html(row):
    suggestion = row.get("suggestion", {})

    suggestion_id = suggestion.get("suggestion_id", "")

    media_id = suggestion.get("media_id", "")

    stale = row.get("stale", False)

    recommendation = row.get("recommendation") or {}

    state_badge = (
        badge("Out of date", "stale")
        if stale
        else badge("Current", "current")
    )

    user_decision = row.get("user_decision")

    decision_badge = (
        f" {badge(user_decision, 'pending')}" if user_decision else ""
    )

    if stale:
        accept_note = (
            "<p class=\"muted\">This suggestion is out of date: "
            "the media or preference information changed since it "
            "was proposed. Acceptance will be refused until it is "
            "refreshed.</p>"
        )
    else:
        accept_note = ""

    proposed_answer = suggestion.get("proposed_answer")

    outcome_title, outcome_detail = _OUTCOME_MEANINGS.get(
        proposed_answer,
        (proposed_answer or "Needs your choice", ""),
    )

    if proposed_answer is None:
        head_action = (
            "<p class=\"muted\">This suggestion has no supportable "
            "answer yet. Continue the Preferences Wizard, reject "
            "it, or use Manual Choice below.</p>"
        )
    elif row.get("execution_completed"):
        head_action = f"""
<p class="muted">This file already has a successfully completed
optimisation. This suggestion is kept as history and is no longer
actionable.</p>
<form method="post" action="/preferences/review/reject">
<input type="hidden" name="suggestion_id" value="{esc(suggestion_id)}">
<button class="btn small btn-danger" type="submit">Reject</button>
</form>
<a class="btn small btn-preview" href="/preview/new?origin=wizard&amp;ref={esc(suggestion_id)}">Preview Optimisation</a>
"""
    elif row.get("execution_active"):
        head_action = f"""
<p class="muted">An optimisation for this file is already
requested and active. This suggestion is kept as history and is
no longer independently actionable while that work is in
flight.</p>
<form method="post" action="/preferences/review/reject">
<input type="hidden" name="suggestion_id" value="{esc(suggestion_id)}">
<button class="btn small btn-danger" type="submit">Reject</button>
</form>
<a class="btn small btn-preview" href="/preview/new?origin=wizard&amp;ref={esc(suggestion_id)}">Preview Optimisation</a>
"""
    else:
        head_action = f"""
<form method="post" action="/preferences/review/accept">
<input type="hidden" name="suggestion_id" value="{esc(suggestion_id)}">
<button class="btn small" type="submit">Accept</button>
</form>
<form method="post" action="/preferences/review/reject">
<input type="hidden" name="suggestion_id" value="{esc(suggestion_id)}">
<button class="btn small btn-danger" type="submit">Reject</button>
</form>
<a class="btn small btn-preview" href="/preview/new?origin=wizard&amp;ref={esc(suggestion_id)}">Preview Optimisation</a>
"""

    manual_form = _manual_choice_form_html(
        row, recommendation, action="/preferences/review/manual"
    )

    return f"""
<div class="card suggestion-card">
<div class="suggestion-head">
<div class="suggestion-identity">
<h3 class="media-filename">{esc(row.get("file_name") or suggestion.get("media_id", ""))}</h3>
<p class="recommendation-line"><strong>{esc(outcome_title)}</strong>
{_answer_badge(proposed_answer)} {state_badge}{decision_badge}</p>
</div>
<div class="suggestion-actions">{head_action}</div>
</div>
<p class="muted">{esc(suggestion.get("reason", ""))}</p>
<div class="section-head"><div>
<h3>Recommendation</h3>
<p class="muted section-sub">What accepting this recommendation
means for this file. Accepting records a preference; it does not
execute or change any file.</p>
</div></div>
{_recommendation_chips_html(recommendation)}
<div class="section-head"><div>
<h3>Measured facts</h3>
</div></div>
{_current_facts_html(row)}
<div class="recommended-outcome">
<p><strong>Recommended action:</strong> {esc(outcome_title)}</p>
<p class="muted">{esc(outcome_detail)}</p>
<p>{media_link(media_id, "See file details") if (media_id and row.get("media_available")) else '<span class="muted">File details are unavailable (the media may have moved).</span>'}</p>
</div>
<details class="disclosure manual-choice">
<summary>Manual Choice</summary>
<p class="muted">Choose the values you want instead of the
recommendation, then Save Choice. Saving supersedes this
recommendation through the existing review lifecycle; nothing is
executed.</p>
{manual_form}
</details>
<details class="disclosure"><summary>Why is this suggested?</summary>
{facts([
    ("Coverage", esc(suggestion.get("coverage_state", ""))),
    ("Matched rule", esc(suggestion.get("matched_rule_id", ""))),
    ("Rule version", esc(suggestion.get("rule_version", ""))),
    ("Source examples", esc(", ".join(suggestion.get("source_example_ids", [])) or "none recorded")),
    ("Basis", esc("established preference" if row.get("established") else "recent wizard answers (not yet established)")),
])}
</details>
{accept_note}
</div>
"""


def _review_status_badge(status):
    """Status-label badge for one file's review posture."""

    if not status:
        return badge("Unknown", "unknown")

    return badge(status.get("label", "Unknown"), status.get("kind", "unknown"))


def _review_tabs_html(view, categories):
    tabs = [
        (
            "needs",
            "Needs your Choice",
            categories.get("needs_choice", 0),
            "Actionable recommendations waiting for your decision.",
        ),
        (
            "recommendations",
            "See all Recommendations",
            categories.get("recommendations", 0),
            "Every file with recommendation history, decided or not.",
        ),
        (
            "context",
            "Needs More Context",
            categories.get("context", 0),
            "Files where there is not yet enough context for a supported recommendation.",
        ),
        (
            "waiting",
            "Waiting for Execution",
            categories.get("waiting", 0),
            "Decisions you have made that NAMOA has not yet executed.",
        ),
        (
            "all",
            "Show All",
            categories.get("all", 0),
            "Every analysed file and its current review status.",
        ),
    ]

    items = "".join(
        f'<a class="subnav-item{" active" if key == view else ""}" '
        f'href="/preferences/review?view={key}" '
        f'aria-label="{esc(label)} ({count})">'
        f"{esc(label)} ({count})</a>"
        for key, label, count, _hint in tabs
    )

    active_hint = next(
        hint for key, _label, _count, hint in tabs if key == view
    )

    return (
        f'<nav class="subnav" aria-label="Review views">{items}</nav>'
        f'<p class="muted">{esc(active_hint)}</p>'
    )


def _history_block_html(history):
    if not history:
        return empty_state(
            "No review history",
            "Accepted, rejected, and superseded suggestions will "
            "appear here.",
        )

    rows = []

    for row in history:
        if row.get("status") == "rejected":
            action = (
                f'<form method="post" action="/preferences/review/reopen">'
                f'<input type="hidden" name="suggestion_id" '
                f'value="{esc(row.get("suggestion_id", ""))}">'
                f'<button class="btn small ghost" type="submit">'
                f"Reopen</button></form>"
            )
        elif row.get("status") == "superseded":
            action = (
                '<span class="muted">Terminal: superseded rows '
                "cannot be reopened. Use Save choice on the live "
                "suggestion to decide again.</span>"
            )
        else:
            action = '<span class="muted">Terminal.</span>'

        rows.append(
            [
                esc(row.get("suggestion_id", "")),
                _suggestion_status_badge(row.get("status")),
                _answer_badge(row.get("proposed_answer")),
                action,
            ]
        )

    return table(
        ["Suggestion", "Status", "Answer", "Reconsider"], rows
    )


def _specify_form_html(item):
    """Specify Recommendation form reusing the Wizard answer cards."""

    suggestion_id = item.get("context_suggestion_id") or ""

    if not suggestion_id:
        return ""

    radios = "".join(
        f"<p><label>"
        f'<input type="radio" name="new_answer" value="{value}">'
        f"<strong>{esc(title)}</strong>"
        f"</label>"
        f'<span class="muted">{esc(hint)}</span></p>'
        for value, title, hint in _WIZARD_ANSWERS
    )

    return f"""
<form method="post" action="/preferences/review/specify">
<input type="hidden" name="suggestion_id" value="{esc(suggestion_id)}">
<fieldset class="wizard-question">
<legend>Specify Recommendation
<span class="muted section-sub">Choose the option that best matches
your preference, then Save. Saving records your decision; it does
not execute any optimisation.</span></legend>
<div class="radio-stack">{radios}</div>
</fieldset>
<p class="change-action"><button class="btn" type="submit">Save</button></p>
</form>
"""


def _context_card_html(item):
    """One Needs More Context item with its separate actions."""

    return f"""
<div class="card suggestion-card">
<div class="card-head">
<h3 class="media-filename">{esc(item.get("file_name") or item.get("media_id"))}</h3>
{badge("Needs More Context", "unknown")}
</div>
<p>This preference does not have enough context yet for NAMOA to
make a clear recommendation. Continue the Preferences Wizard to
build more context, or specify an explicit recommendation below.</p>
<div class="actions-row">
<a class="btn" href="/preferences/wizard">Continue Preferences Wizard</a>
</div>
{_specify_form_html(item)}
</div>
"""


def _waiting_card_html(item):
    """One Waiting for Execution item: decision made, not executed."""

    accepted = [
        row
        for row in item.get("suggestions", [])
        if row.get("status") == "accepted"
        and row.get("proposed_answer") in ("Balanced", "Optimise")
    ]

    answer = accepted[-1].get("proposed_answer") if accepted else None

    return f"""
<div class="card suggestion-card">
<div class="card-head">
<h3 class="media-filename">{esc(item.get("file_name") or item.get("media_id"))}</h3>
{badge("Waiting for Execution", "running")}
</div>
<p class="recommendation-line">Your decision:
{_answer_badge(answer)}</p>
<p class="muted">You made this decision. NAMOA has not yet
successfully completed the optimisation, so it is waiting for
execution. This is not the same as in progress or completed.</p>
<p><a class="btn ghost" href="/preferences/review?view=waiting">Waiting for Execution</a></p>
</div>
"""


def _completed_card_html(item):
    """One Optimisation Completed item from authoritative execution."""

    return f"""
<div class="card suggestion-card">
<div class="card-head">
<h3 class="media-filename">{esc(item.get("file_name") or item.get("media_id"))}</h3>
{badge("Optimisation Completed", "current")}
</div>
<p class="muted">An optimisation for this file completed
successfully. Review Suggestions shows the current facts for the
resulting file.</p>
</div>
"""


def render_preference_review(data):
    """
    Review Suggestions: five category views
    (Needs your Choice / See all Recommendations / Needs More
    Context / Waiting for Execution / Show All) with truthful
    counts computed on every load.
    """

    proposed = data.get("answered_proposed", data.get("proposed", []))

    categories = data.get("categories", {})

    view = data.get("view", "needs")

    notice = (
        f'<div class="notice">{esc(data["notice"])}</div>'
        if data.get("notice")
        else ""
    )

    refresh = data.get("refresh")

    if refresh:
        refresh_note = (
            f'<p class="muted">Refresh generated '
            f'{esc(str(refresh.get("generated", 0)))} suggestion(s); '
            f'{esc(str(refresh.get("proposed", 0)))} newly proposed'
            f'{"" if not refresh.get("skipped_decided") else ", " + esc(str(refresh.get("skipped_decided"))) + " already-decided skipped"}; '
            f'{esc(str(refresh.get("stored_total", 0)))} stored in total.</p>'
        )
    else:
        refresh_note = ""

    if proposed:
        cards = "".join(
            _suggestion_card_html(row) for row in proposed
        )

        accept_all = f"""
<div class="card"><div class="card-head"><h2>Accept all current suggestions</h2></div>
<p class="muted">Applies to the {len(proposed)} suggestion(s)
awaiting review below.</p>
<form method="post" action="/preferences/review/accept-all">
<p><button class="btn" type="submit">Accept all ({len(proposed)})</button></p>
<p class="muted">Every item is validated against presently observed
state first: if any single item is stale, ambiguous, or already
decided, nothing is accepted. Each acceptance is attributed
individually, and future files still need their own fresh
suggestions.</p>
</form>
</div>
"""
    else:
        cards = empty_state(
            "You have no recommendations waiting for a decision.",
            "There is nothing unresolved right now. Decided "
            "recommendations remain visible under See all "
            "Recommendations.",
        )
        accept_all = ""

    history = data.get("history", [])

    history_block = _history_block_html(history)

    groups = data.get("groups", [])

    if groups:
        group_cards = "".join(
            f'<div class="card"><div class="card-head">'
            f"<h3>{esc(group.get('file_name') or group.get('media_id'))}</h3>"
            f"</div>"
            + (
                f"<p>{badge(group.get('user_decision'), 'pending')}</p>"
                if group.get("user_decision")
                else "<p class=\"muted\">No decision recorded yet.</p>"
            )
            + table(
                ["Suggestion", "Status", "Answer"],
                [
                    [
                        esc(item.get("suggestion_id", "")),
                        _suggestion_status_badge(
                            item.get("status")
                        ),
                        _answer_badge(
                            item.get("proposed_answer")
                        ),
                    ]
                    for item in group.get("rows", [])
                ],
            )
            + "</div>"
            for group in groups
        )
    else:
        group_cards = empty_state(
            "No recommendations yet.",
            "Save wizard answers or refresh to generate "
            "recommendations.",
        )

    context_items = data.get("context_items", [])

    if context_items:
        context_block = "".join(
            _context_card_html(item) for item in context_items
        )
    else:
        context_block = empty_state(
            "Nothing needs more context.",
            "Every recommendation NAMOA holds has enough context "
            "for a supported suggestion.",
        )

    waiting_items = data.get("waiting_items", [])

    if waiting_items:
        waiting_block = "".join(
            _waiting_card_html(item) for item in waiting_items
        )
    else:
        waiting_block = empty_state(
            "Nothing is waiting for execution.",
            "Decisions you make will appear here until their "
            "optimisation completes.",
        )

    files_view = data.get("files_view", {})

    files = files_view.get("files", []) if files_view else []

    if files:
        file_rows = [
            [
                esc(item.get("file_name") or item.get("media_id")),
                _review_status_badge(item.get("status")),
                _coverage_badge(item.get("coverage_state")),
                str(item.get("suggestion_count", 0)),
                esc(item.get("user_decision") or "No decision yet"),
            ]
            for item in files
        ]
        files_block = table(
            ["File", "Status", "Coverage", "Suggestions", "Decision"],
            file_rows,
        )
    else:
        files_block = empty_state(
            "No analysable files.",
            "Scan the library so NAMOA has files to review.",
        )

    tabs = _review_tabs_html(view, categories)

    if view == "recommendations":
        main_section = group_cards
    elif view == "context":
        main_section = context_block
    elif view == "waiting":
        main_section = waiting_block
    elif view == "all":
        main_section = files_block
    else:
        main_section = f"""
{accept_all}
{cards}

<div class="card"><div class="card-head"><h2>History</h2></div>
{history_block}
</div>
"""

    content = f"""
<div class="card"><div class="card-head"><h2>Review suggestions</h2></div>
<p>Suggestions are proposals only. They become preferences solely
through your explicit acceptance below. Categories are computed
when this page loads, so every count is already correct.</p>
<div class="actions-row">
<a class="btn btn-wizard-magic" href="/preferences/review/carousel">Open Optimisation Carousel</a>
<form method="post" action="/preferences/review/refresh">
<button class="btn ghost" type="submit">Refresh suggestions</button>
</form>
</div>
{refresh_note}
</div>

<div class="stat-grid">
{stat_card("Needs your Choice", str(categories.get("needs_choice", 0)))}
{stat_card("See all Recommendations", str(categories.get("recommendations", 0)))}
{stat_card("Needs More Context", str(categories.get("context", 0)))}
{stat_card("Waiting for Execution", str(categories.get("waiting", 0)))}
{stat_card("Optimisation Completed", str(categories.get("completed", 0)))}
</div>

{tabs}

{main_section}
"""

    return layout(
        "Review Suggestions", "preferences",
        _form_error_panel(data) + notice + content,
        refreshed_at=data.get("refreshed_at"),
    )


def _carousel_card_html(data):
    """One carousel item: the same recommendation and controls as the
    Review Suggestions list, presented one item at a time with a
    stable decision area."""

    item = data.get("item") or {}

    recommendation = data.get("recommendation") or {}

    suggestion = item.get("suggestion", {})

    suggestion_id = suggestion.get("suggestion_id", "")

    media_id = suggestion.get("media_id", "")

    index = data.get("index", 0)

    proposed_answer = suggestion.get("proposed_answer")

    outcome_title, outcome_detail = _OUTCOME_MEANINGS.get(
        proposed_answer,
        (proposed_answer or "Needs your choice", ""),
    )

    if proposed_answer is None:
        accept_form = (
            '<p class="muted">No supportable answer is available for '
            "this item. Continue the Preferences Wizard, reject it, "
            "or use Manual Choice.</p>"
        )
    elif item.get("execution_completed"):
        accept_form = (
            '<p class="muted">This file already has a successfully '
            "completed optimisation. This suggestion is kept as "
            "history and is no longer actionable.</p>"
        )
    elif item.get("execution_active"):
        accept_form = (
            '<p class="muted">An optimisation for this file is '
            "already requested and active. This suggestion is kept "
            "as history and is no longer independently actionable "
            "while that work is in flight.</p>"
        )
    else:
        accept_form = f"""
<form method="post" action="/preferences/review/carousel/accept">
<input type="hidden" name="index" value="{esc(str(index))}">
<input type="hidden" name="suggestion_id" value="{esc(suggestion_id)}">
<button class="btn" type="submit">Accept</button>
</form>
"""

    reject_form = f"""
<form method="post" action="/preferences/review/carousel/reject">
<input type="hidden" name="index" value="{esc(str(index))}">
<input type="hidden" name="suggestion_id" value="{esc(suggestion_id)}">
<button class="btn btn-danger" type="submit">Reject</button>
</form>
<a class="btn btn-preview" href="/preview/new?origin=wizard&amp;ref={esc(suggestion_id)}">Preview Optimisation</a>
"""

    manual_form = _manual_choice_form_html(
        item,
        recommendation,
        action="/preferences/review/carousel/manual",
        carousel_index=index,
    )

    return f"""
<div class="card carousel-card">
<div class="suggestion-head">
<div class="suggestion-identity">
<h3 class="media-filename">{esc(item.get("file_name") or suggestion.get("media_id", ""))}</h3>
<p class="recommendation-line"><strong>{esc(outcome_title)}</strong>
{_answer_badge(proposed_answer)}</p>
</div>
</div>
<p class="muted">{esc(suggestion.get("reason", ""))}</p>
<div class="section-head"><div>
<h3>Recommendation</h3>
<p class="muted section-sub">What accepting this recommendation
means for this file. Accepting records a preference; it does not
execute or change any file.</p>
</div></div>
{_recommendation_chips_html(recommendation)}
<div class="recommended-outcome">
<p><strong>Recommended action:</strong> {esc(outcome_title)}</p>
<p class="muted">{esc(outcome_detail)}</p>
<p>{media_link(media_id, "See file details") if (media_id and item.get("media_available")) else '<span class="muted">File details are unavailable.</span>'}</p>
</div>
<div class="carousel-controls">
{accept_form}
{reject_form}
<details class="disclosure manual-choice">
<summary>Manual Choice</summary>
<p class="muted">Choose the values you want instead of the
recommendation, then Save Choice. Saving supersedes this
recommendation; nothing is executed.</p>
{manual_form}
</details>
</div>
</div>
"""


def render_preference_carousel(data):
    """Optimisation Carousel: one unresolved review item at a time,
    using the same recommendation context and decision path as Review
    Suggestions."""

    if data.get("empty"):
        body = empty_state(
            "Nothing is waiting for your decision.",
            "Every recommendation currently held has been decided. "
            "New items appear here as they are generated.",
        )
    else:
        body = _carousel_card_html(data)

    total = data.get("total", 0)

    position = data.get("position", 0)

    progress = (
        f'<p class="carousel-progress" aria-live="polite">'
        f"{esc(str(position))} / {esc(str(total))}</p>"
    )

    advance_class = (
        " carousel-advance" if data.get("advance") else ""
    )

    notice = (
        f'<div class="notice">{esc(data["notice"])}</div>'
        if data.get("notice")
        else ""
    )

    index = data.get("index", 0)

    total = data.get("total", 0)

    empty = bool(data.get("empty"))

    # Navigation links preserve the existing item population and never
    # submit a decision. First/last items render a disabled indicator.
    previous_control = (
        f'<a class="carousel-nav-button" '
        f'href="/preferences/review/carousel?index={index - 1}" '
        f'aria-label="Previous recommendation">&#8249;</a>'
        if (not empty and index > 0)
        else (
            '<span class="carousel-nav-button is-disabled" '
            'aria-disabled="true" '
            'aria-label="Previous recommendation (unavailable)">'
            "&#8249;</span>"
        )
    )

    next_control = (
        f'<a class="carousel-nav-button" '
        f'href="/preferences/review/carousel?index={index + 1}" '
        f'aria-label="Next recommendation">&#8250;</a>'
        if (not empty and index < total - 1)
        else (
            '<span class="carousel-nav-button is-disabled" '
            'aria-disabled="true" '
            'aria-label="Next recommendation (unavailable)">'
            "&#8250;</span>"
        )
    )

    nav = (
        '<nav class="carousel-nav" aria-label="Carousel navigation">'
        f"{previous_control}{next_control}</nav>"
    )

    content = f"""
<p class="muted carousel-intro">One unresolved recommendation at a
time. Each decision uses the same review lifecycle as Review
Suggestions. Accepting records a decision; it never executes a
conversion.</p>
{notice}
<div class="carousel{advance_class}">
{progress}
{nav}
{body}
</div>
"""

    return layout(
        "Optimisation Carousel", "preferences",
        _form_error_panel(data) + content,
        refreshed_at=data.get("refreshed_at"),
        head_actions=(
            '<a class="btn small ghost" href="/preferences/review">'
            "Back to Review Suggestions</a>"
        ),
    )


# ---------------------------------------------------------
# Phase 17 optimisation preview.
#
# Pure formatting over handler-assembled preview data. The
# preview page shows the pinned recommendation context, the
# authoritative transformation (or explicit override), the
# original and generated players, and the existing decision
# actions. Generating, closing, accepting, or rejecting never
# happens here; those are POST routes handled server-side.
# ---------------------------------------------------------


def _preview_timestamp_text(preview):
    timestamp = preview.get("timestamp_seconds")
    duration = preview.get("duration_seconds")

    if timestamp is None or duration is None:
        return "No sample selected yet."

    actual = preview.get("actual_duration_seconds")

    rendered = (
        f"Sample: {float(timestamp):.1f}s for "
        f"{float(duration):.1f}s (automatically selected, "
        "near the middle where possible)"
    )

    if actual is not None:
        rendered += f" · rendered {float(actual):.1f}s"

    return rendered


def _preview_override_form(preview, schema):
    """Explicit override editor from the operation schema."""

    token = esc(preview.get("token", ""))

    operation = preview.get("operation", "")

    current_params = preview.get("parameters") or {}

    if not schema:
        return (
            "<p class=\"muted\">Override controls are "
            "unavailable for this operation.</p>"
        )

    fields = []

    for param in schema.get("parameters") or []:
        name = param.get("name", "")

        if not name:
            continue

        allowed = param.get("allowed_values")

        current = current_params.get(name, param.get("default"))

        if allowed:
            options = "".join(
                f'<option value="{esc(str(option))}"'
                f'{" selected" if str(option) == str(current) else ""}>'
                f"{esc(str(option))}</option>"
                for option in allowed
            )
            control = (
                f'<select name="param_{esc(name)}">'
                f"{options}</select>"
            )
        else:
            control = (
                f'<input type="text" name="param_{esc(name)}" '
                f'value="{esc(str(current) if current is not None else "")}">'
            )

        fields.append(
            f"<p><label>{esc(param.get('description') or name)}"
            f"<br>{control}</label></p>"
        )

    return f"""
<form method="post" action="/preview/{token}/override" data-preview-generate>
<fieldset class="wizard-question">
<legend>Explicit User Override
<span class="muted section-sub">Supported parameters only,
validated against the closed operation registry. Unsupported
values are rejected and nothing changes. Applying an override
regenerates the preview immediately.</span></legend>
{''.join(fields)}
</fieldset>
<p><button class="btn" type="submit">Apply Override and Generate New Preview</button></p>
<p class="muted">The override immediately becomes the
authoritative context for Preview, Accept, execution, and
provenance. The original recommendation is preserved in the
queued job record.</p>
</form>
"""


# ---------------------------------------------------------
# Optimisation Preview user-facing presentation.
#
# The service layer (PreviewContext, RetentionAssessment,
# alternatives, RequestedTransformation) remains authoritative.
# Everything below only reformats data already present in the
# preview view dict: no safety, retention, or decision logic
# lives here.
# ---------------------------------------------------------

#: User-facing operation labels. Unknown operations fall back
#: to their raw registry identifier so nothing is hidden.
_PREVIEW_OPERATION_LABELS = {
    "codec_conversion": ("HEVC conversion", "MP4"),
    "codec_conversion_mkv": ("HEVC conversion", "MKV"),
    "remux_mp4": ("Container remux", "MP4"),
}

#: User-facing subtitle codec labels. Unknown codecs fall back
#: to their raw codec name so diagnostics are never lost.
_PREVIEW_SUBTITLE_LABELS = {
    "hdmv_pgs_subtitle": "Blu-ray (PGS)",
    "dvd_subtitle": "DVD (VobSub)",
    "dvd_sub": "DVD (VobSub)",
    "xsub": "DivX (XSUB)",
    "dvb_subtitle": "DVB",
    "subrip": "SubRip text",
    "srt": "SubRip text",
    "ass": "ASS/SSA text",
    "ssa": "ASS/SSA text",
    "mov_text": "MP4 timed text",
    "webvtt": "WebVTT text",
}

_PREVIEW_CONTENT_CLASS_LABELS = {
    "subtitle": "Subtitles",
    "chapter": "Chapters",
    "metadata": "Metadata",
    "audio": "Audio",
    "video": "Video",
}


def _preview_operation_presentation(operation):
    """(title, container) for an operation id, raw on unknown."""

    operation = str(operation or "")

    if operation in _PREVIEW_OPERATION_LABELS:
        return _PREVIEW_OPERATION_LABELS[operation]

    return (operation or "unresolved", "")


def _preview_param_rows(params):
    """User-facing optimisation facts, raw values preserved."""

    rows = []

    for name, value in sorted((params or {}).items()):
        text = str(value)

        if name == "target_codec" and text.lower() == "hevc":
            rows.append(("Video", "HEVC"))
        elif name == "quality" and text.lower().startswith(
            "crf_"
        ):
            rows.append(
                ("Quality", f"CRF {esc(text[4:])}")
            )
        elif name == "preset":
            rows.append(("Preset", esc(text.title())))
        elif name == "encoder":
            rows.append(("Encoder", esc(text)))
        else:
            rows.append((
                esc(str(name).replace("_", " ").title()),
                esc(text),
            ))

    return rows


def _preview_subtitle_label(codec):
    """User-facing subtitle codec label, raw on unknown."""

    codec = str(codec or "")

    return _PREVIEW_SUBTITLE_LABELS.get(codec, codec or "unknown")


def _preview_group_retention_items(items):
    """Group equivalent retention items: (verdict, class, codec)
    -> {"count": n, "track_indices": [...], "explanation": first}.
    Presentation-only grouping; the underlying items keep their
    individual detail for diagnostics.
    """

    groups = []

    for entry in items or []:
        key = (
            entry.get("verdict"),
            entry.get("content_class"),
            entry.get("codec"),
        )

        for group in groups:
            if group["key"] == key:
                group["count"] += 1
                group["track_indices"].append(
                    entry.get("track_index")
                )
                break
        else:
            groups.append({
                "key": key,
                "count": 1,
                "track_indices": [entry.get("track_index")],
                "explanation": entry.get("explanation") or "",
            })

    return groups


def _preview_content_summary(preview):
    """User-facing retention summary for the preview view.

    Returns {"blocked_headline", "group_lines", "has_blocked",
    "verdict"} derived only from the stored RetentionAssessment.
    Empty group_lines means nothing to disclose beyond the
    normal flow.
    """

    retention = preview.get("retention")

    if not isinstance(retention, dict):
        return {
            "blocked_headline": "",
            "group_lines": [],
            "has_blocked": False,
            "verdict": "",
        }

    verdict = retention.get("verdict", "ok")

    items = retention.get("items") or []

    output_container = _preview_operation_presentation(
        preview.get("operation", "")
    )[1]

    group_lines = []

    for group in _preview_group_retention_items(items):
        _, content_class, codec = group["key"]
        count = group["count"]

        class_label = _PREVIEW_CONTENT_CLASS_LABELS.get(
            str(content_class or ""), str(content_class or "")
        )

        if (
            group["key"][0] == "blocked"
            and content_class == "subtitle"
        ):
            group_lines.append(
                f"{class_label}: {count} "
                f"{esc(_preview_subtitle_label(codec))} "
                f"subtitle track{'s' if count != 1 else ''} "
                f"cannot be preserved in "
                f"{esc(output_container or 'this output')}."
            )
        elif content_class == "chapter":
            group_lines.append(
                f"{class_label}: preservation cannot "
                "currently be guaranteed."
            )
        elif content_class == "metadata":
            group_lines.append(
                f"{class_label}: best effort."
            )
        elif group["key"][0] == "blocked":
            group_lines.append(
                f"{class_label}: cannot be preserved in "
                f"{esc(output_container or 'this output')}."
            )
        elif group["key"][0] == "unassessable_present":
            group_lines.append(
                f"{class_label}: cannot currently be "
                "assessed."
            )
        elif group["key"][0] == "loss_acknowledgeable":
            group_lines.append(
                f"{class_label}: may not be fully preserved."
            )

    blocked_subs = [
        group for group in _preview_group_retention_items(items)
        if group["key"][0] == "blocked"
        and group["key"][1] == "subtitle"
    ]

    blocked_headline = ""

    if blocked_subs:
        total = sum(group["count"] for group in blocked_subs)
        kinds = ", ".join(sorted({
            _preview_subtitle_label(group["key"][2])
            for group in blocked_subs
        }))

        blocked_headline = (
            f"The recommended "
            f"{esc(output_container or 'output')} "
            f"conversion cannot preserve this file's {total} "
            f"{esc(kinds)} subtitle track"
            f"{'s' if total != 1 else ''}. NAMOA has stopped "
            f"the conversion rather than silently removing "
            f"them."
        )

    return {
        "blocked_headline": blocked_headline,
        "group_lines": group_lines,
        "has_blocked": any(
            entry.get("verdict") == "blocked"
            for entry in items
        ),
        "verdict": verdict,
    }


# ---------------------------------------------------------
# Preview playback presentation helpers.
#
# Presentation only: the service layer remains authoritative
# for positions, artifacts, retention, and decisions. Audio
# notes describe browser playback limitations truthfully;
# they never claim audio is missing, and no audio mapping is
# changed to satisfy the browser.
# ---------------------------------------------------------

#: Audio codecs no mainstream browser decodes reliably. When a
#: player source uses one of these, the UI says so instead of
#: letting silence imply the file lost its audio.
_PREVIEW_UNPLAYABLE_AUDIO = frozenset({
    "dts",
    "dtshd",
    "dts-hd",
    "dts_hd",
    "ac3",
    "eac3",
    "truehd",
    "mlp",
})

#: Audio codecs browsers generally play.
_PREVIEW_PLAYABLE_AUDIO = frozenset({
    "aac",
    "mp3",
    "opus",
    "vorbis",
    "flac",
    "pcm_s16le",
    "pcm_s24le",
    "wav",
})


def _preview_audio_note(audio_codecs, *, sample):
    """Truthful playback note for one player's audio, or "".

    - No audio tracks at all -> says so factually.
    - Only widely-unplayable codecs -> explains the browser
      limitation without claiming the audio is missing.
    - Otherwise (playable or unknown codecs) -> silent, so the
      UI never fakes a problem or a guarantee.
    """

    codecs = [
        str(codec).lower()
        for codec in (audio_codecs or [])
        if codec
    ]

    if not codecs:
        return (
            "This "
            + ("sample" if sample else "file")
            + " contains no audio tracks."
        )

    if all(
        codec in _PREVIEW_UNPLAYABLE_AUDIO for codec in codecs
    ):
        names = ", ".join(
            esc(codec.upper()) for codec in codecs
        )

        return (
            f"Browser playback note: {names} audio is not "
            f"widely supported by browsers, so you may hear "
            f"no sound here even though the "
            + ("sample" if sample else "file")
            + " contains audio tracks."
        )

    return ""


def _preview_format_timestamp(seconds):
    """H:MM:SS (or M:SS) display for a position, "" if unknown."""

    try:
        total = float(seconds)
    except (TypeError, ValueError):
        return ""

    if not (total == total and total >= 0):
        return ""

    whole = int(total)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)

    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"

    return f"{minutes:02d}:{secs:02d}"


def _preview_position_block(preview, settings):
    """Shared comparison-position control + snapshot form.

    The slider selects the source timestamp both players
    compare at. It posts ``start_seconds`` to the existing
    generate route, which builds the temporary sample there
    without touching transformation, observation, run, or
    lineage. Renders nothing usable when the source duration
    is unknown.
    """

    token = esc(preview.get("token", ""))

    total = preview.get("source_duration_seconds")

    try:
        total = float(total) if total is not None else None
    except (TypeError, ValueError):
        total = None

    if total is None or not (total == total and total > 0):
        return f"""
<div class="card"><div class="card-head"><h2>Preview position</h2></div>
<p class="muted">The source duration is not known yet, so a
comparison position cannot be selected. Generating a snapshot
uses the default middle position.</p>
<form method="post" action="/preview/{token}/generate" data-preview-generate>
<p><button class="btn" type="submit">Generate New Preview Snapshot</button></p>
<p class="muted">Builds a new temporary sample only. It does
not accept, reject, or queue anything, and it never changes
the optimisation itself.</p>
</form>
</div>
"""

    position = preview.get("timestamp_seconds")

    if position is None:
        position = preview.get("suggested_position_seconds")

    try:
        position = float(position)
    except (TypeError, ValueError):
        position = 0.0

    if not (position == position):
        position = 0.0

    position = max(0.0, min(position, total))

    window = 10.0

    try:
        window = float(
            (settings or {}).get("duration_seconds", 10.0)
        )
    except (TypeError, ValueError):
        window = 10.0

    window_label = (
        str(int(window))
        if float(window).is_integer()
        else str(window)
    )

    label = _preview_format_timestamp(position) or "0:00"
    total_label = _preview_format_timestamp(total)

    return f"""
<div class="card"><div class="card-head"><h2>Preview position</h2></div>
<p class="preview-position-row"><label>Preview position
<input type="range" id="preview-position" min="0"
max="{total:.1f}" step="0.1" value="{position:.1f}"
data-duration="{total:.1f}">
</label><strong id="preview-position-label">{esc(label)}</strong>
<span class="muted">of {esc(total_label)}</span></p>
<form method="post" action="/preview/{token}/generate" data-preview-generate>
<input type="hidden" id="preview-start-seconds"
name="start_seconds" value="{position:.1f}">
<p class="preview-position-row"><label>Start at (seconds)
<input type="number" id="preview-start-number" min="0"
max="{total:.1f}" step="0.1" value="{position:.1f}">
</label>
<button class="btn" type="submit">Generate New Preview Snapshot</button></p>
<p class="muted">Moving the slider seeks the Original player;
the snapshot covers ~{esc(window_label)} seconds from the
selected position without changing the optimisation.</p>
</form>
</div>
<script>
(function () {{
  var slider = document.getElementById("preview-position");
  var number = document.getElementById("preview-start-number");
  var hidden = document.getElementById("preview-start-seconds");
  var label = document.getElementById("preview-position-label");
  var original = document.getElementById("preview-original-player");
  var total = {total:.1f};

  function fmt(seconds) {{
    seconds = Math.max(0, Math.floor(seconds || 0));
    var h = Math.floor(seconds / 3600);
    var m = Math.floor((seconds % 3600) / 60);
    var s = seconds % 60;
    var mm = (m < 10 ? "0" : "") + m;
    var ss = (s < 10 ? "0" : "") + s;
    return (h > 0 ? h + ":" : "") + mm + ":" + ss;
  }}

  function apply(value, seek) {{
    var clamped = Math.max(0, Math.min(total, Number(value) || 0));
    if (slider && slider.value !== String(clamped)) {{
      slider.value = clamped;
    }}
    if (number && number.value !== String(clamped)) {{
      number.value = clamped;
    }}
    if (hidden) {{
      hidden.value = clamped.toFixed(1);
    }}
    if (label) {{
      label.textContent = fmt(clamped);
    }}
    if (seek && original && original.seekable) {{
      try {{
        original.currentTime = Math.min(
          clamped, original.duration || clamped
        );
      }} catch (e) {{}}
    }}
  }}

  function seekOriginal() {{
    if (!original) {{
      return;
    }}
    var seekToSlider = function () {{
      apply(slider ? slider.value : 0, true);
    }};
    if (original.readyState >= 1) {{
      apply(slider ? slider.value : 0, true);
    }} else {{
      original.addEventListener(
        "loadedmetadata", seekToSlider, {{once: true}}
      );
    }}
  }}

  if (slider) {{
    slider.addEventListener("input", function () {{
      apply(slider.value, true);
    }});
    seekOriginal();
  }}
  if (number) {{
    number.addEventListener("change", function () {{
      apply(number.value, true);
    }});
  }}
}})();
</script>
"""


def _preview_retention_block(preview, summary):
    """Content-retention consequence summary (no actions).

    Presents grouped user-facing consequences only. Decision
    actions (preservation alternative, acknowledgement) live in
    the decision card via _preview_preserve_actions and
    _preview_acknowledge_action so applicable choices sit
    together. Raw per-track diagnostics stay in Extended
    information, not here.
    """

    verdict = summary["verdict"]

    if verdict == "ok" or not summary["group_lines"]:
        return ""

    group_rows = "".join(
        f"<li>{line}</li>" for line in summary["group_lines"]
    )

    retention = preview.get("retention") or {}

    disclosures = retention.get("disclosures") or []

    disclosure_block = (
        "<p class=\"muted\">" + " ".join(
            esc(str(line)) for line in disclosures
        ) + "</p>"
        if disclosures else ""
    )

    return f"""
<div class="card"><div class="card-head"><h2>Content retention</h2></div>
<p><strong>This optimisation will not preserve everything.</strong></p>
<ul>{group_rows}</ul>
{disclosure_block}
</div>
"""


def _preview_preserve_actions(preview):
    """Verified preservation alternatives as decision actions.

    Each offered alternative posts to the existing /preserve
    flow (apply_override -> Preview -> Accept). Renders nothing
    when no alternative is offered.
    """

    token = esc(preview.get("token", ""))

    alternatives = preview.get("alternatives") or []

    alternative_forms = ""

    for alternative in alternatives:
        operation = esc(str(alternative.get("operation") or ""))

        params_hidden = "".join(
            f'<input type="hidden" name="param_{esc(str(name))}" '
            f'value="{esc(str(value))}">'
            for name, value in sorted(
                (alternative.get("parameters") or {}).items()
            )
        )

        alternative_forms += f"""
<form method="post" action="/preview/{token}/preserve" data-preview-generate>
<input type="hidden" name="operation" value="{operation}">
{params_hidden}
<p><button class="btn" type="submit">Preserve content and continue</button></p>
<p class="muted">{esc(alternative.get("explanation") or "")}</p>
</form>
"""

    if not alternative_forms:
        return ""

    return f"""
<div class="preview-action">
<span class="badge stale">Preservation alternative</span>
<p><strong>Preserve content</strong></p>
<p>Convert to MKV instead. The same HEVC optimisation
can be applied while preserving the supported subtitle
tracks.</p>
{alternative_forms}
</div>
"""


def _preview_acknowledge_action(preview, summary):
    """Acknowledgement action, only for acknowledgeable losses.

    Blocked and unassessable verdicts render nothing here, so
    no bypass path can ever be offered for them.
    """

    if summary["verdict"] != "loss_acknowledgeable":
        return ""

    token = esc(preview.get("token", ""))

    return f"""
<div class="preview-action warn">
<form method="post" action="/preview/{token}/acknowledge">
<p><strong>If deleting the original</strong></p>
<p><button class="btn btn-warn" type="submit">Acknowledge deletion</button></p>
<p class="muted">Confirms that you understand the original file
will be deleted if the optimisation completes successfully.
This acknowledgement is recorded with the queued operation.
It does not queue or execute anything and cannot bypass
blocked content or unsupported operations.</p>
</form>
</div>
"""


def _preview_current_operation_block(preview):
    """Current working operation indicator for the decision card.

    Exactly one operation is authoritative: the original
    recommendation, or the explicit user override once applied.
    Presentation only; the service layer remains authoritative.
    """

    override = preview.get("override")

    if override:
        return """
<div class="preview-action">
<p><strong>Current operation: Explicit user override</strong></p>
<p class="muted">The Preview represents your current optimisation
settings. The override you applied is now the operation that
will be queued if you accept it. The original recommendation
is preserved in the operation history.</p>
</div>
"""

    return """
<div class="preview-action">
<p><strong>Current operation: Recommendation</strong></p>
<p class="muted">The Preview represents the recommended
optimisation that will be queued if you accept it.</p>
</div>
"""


def _preview_retention_details(preview):
    """Collapsed per-track retention detail for Extended info."""

    retention = preview.get("retention")

    if not isinstance(retention, dict):
        return ""

    detail_rows = "".join(
        f"<li>{esc(entry.get('explanation') or '')}</li>"
        for entry in (retention.get("items") or [])
        if entry.get("explanation")
    )

    if not detail_rows:
        return ""

    return f"""
<details class="disclosure"><summary>Show content details</summary>
<ul>{detail_rows}</ul>
</details>
"""


def render_preview(data):
    """Optimisation Preview page (or closed/error states)."""

    if data.get("closed"):
        origin = data.get("origin") or "analysis"

        if origin == "wizard":
            back = "/preferences/review"
        elif origin == "carousel":
            back = "/preferences/review/carousel"
        else:
            back = "/opportunities"

        return layout(
            "Optimisation Preview", "opportunities",
            f"""
<div class="card"><div class="card-head"><h2>Preview closed</h2></div>
<p>The transient preview was deleted. No decision was changed.</p>
<p><a class="btn ghost" href="{back}">Back</a></p>
</div>
""",
            refreshed_at=data.get("refreshed_at"),
        )

    preview = data.get("preview")

    if preview is None:
        return layout(
            "Optimisation Preview", "opportunities",
            _form_error_panel(data),
            refreshed_at=data.get("refreshed_at"),
        )

    token = esc(preview.get("token", ""))

    origin = preview.get("origin", "analysis")

    if origin == "wizard":
        back_href = "/preferences/review"
        origin_label = "Wizard recommendation"
    elif origin == "carousel":
        back_href = "/preferences/review/carousel"
        origin_label = "Carousel recommendation"
    else:
        back_href = "/opportunities"
        origin_label = "Recommended optimisation"

    status = preview.get("status", "open")

    params = preview.get("parameters") or {}

    operation_title, output_container = (
        _preview_operation_presentation(
            preview.get("operation", "")
        )
    )

    fact_rows = "".join(
        f"<dt>{label}</dt><dd>{value}</dd>"
        for label, value in _preview_param_rows(params)
    )

    if output_container:
        fact_rows += (
            f"<dt>Output</dt><dd>{esc(output_container)}</dd>"
        )

    if not fact_rows:
        fact_rows = (
            "<dt>defaults</dt><dd>operation defaults apply</dd>"
        )

    summary = _preview_content_summary(preview)

    show_accept = not summary["has_blocked"]

    form_error = data.get("form_error") or {}

    raw_form_message = form_error.get("message", "")

    # A failed generation attempt keeps its raw diagnostic in
    # Technical details only. The primary message stays
    # friendly and makes no claim about the root cause: the
    # service layer reports the exit code and stderr tail, but
    # there is no authoritative classifier for causes such as
    # host memory pressure.
    generation_failed = (
        not summary["blocked_headline"]
        and preview.get("status") == "failed"
        and bool(preview.get("error"))
    )

    if summary["blocked_headline"]:
        panel_error = {
            "title": "Preview unavailable",
            "message": summary["blocked_headline"],
        }
    elif generation_failed:
        panel_error = {
            "title": "Preview unavailable",
            "message": (
                "We couldn't generate this preview. "
                "Your original file has not been changed."
            ),
        }
    else:
        panel_error = form_error

    data = dict(data, form_error=panel_error) if panel_error else data

    technical_rows = "".join(
        f"<dt>{esc(str(name))}</dt>"
        f"<dd>{esc(str(value))}</dd>"
        for name, value in sorted(params.items())
    ) or "<dt>defaults</dt><dd>operation defaults apply</dd>"

    technical_block = f"""
<details><summary>Technical details</summary>
<dl class="preview-params">
<dt>operation</dt><dd>{esc(preview.get("operation") or "unresolved")}</dd>
<dt>source</dt><dd>{esc(preview.get("source") or "")}</dd>
<dt>observation</dt><dd>{esc(str(preview.get("observation_id") or "unknown"))}</dd>
<dt>run</dt><dd>{esc(str(preview.get("run_id") or "unknown"))}</dd>
{technical_rows}
{"<dt>error</dt><dd>" + esc(preview.get("error") or "") + "</dd>" if preview.get("error") else ""}
</dl>
<p class="muted">The preview and any later Accept must match
this source version or refuse.</p>
</details>
"""

    override = preview.get("override")

    if override:
        override_block = f"""
<div class="recommended-outcome">
<p><strong>Explicit User Override active</strong></p>
<p class="muted">Operation {esc(str(override.get("operation", "")))}
with user-selected parameters. This override, not the original
recommendation, is what Preview shows and what Accept will
queue.</p>
</div>
"""
    else:
        override_block = ""

    if status == "accepted":
        accepted = data.get("accepted") or {}

        state_block = f"""
<div class="card"><div class="card-head"><h2>Queued</h2></div>
<p>Accepted and queued as execution job
{('<a href="/executions/' + str(accepted.get("job_id")) + '">'
  f'#{accepted.get("job_id")}</a>') if accepted.get("job_id") else ""}.
The preview sample was deleted. What was queued is exactly what
the preview showed.</p>
<p><a class="btn ghost" href="/executions">Open the optimisation queue</a></p>
</div>
"""
    elif status == "rejected":
        state_block = f"""
<div class="card"><div class="card-head"><h2>Rejected</h2><a class="btn small ghost" href="/">Go to dashboard</a></div>
<div class="notice" role="status"><strong>Optimisation decision was rejected.</strong>
The recommendation was recorded as rejected and kept in history.
Nothing was queued.</div>
<p>Rejected through the existing rejection path. The transient
preview was deleted.</p>
<p><a class="btn ghost" href="{back_href}">Back to opportunity</a></p>
</div>
"""
    else:
        state_block = ""

    players = ""

    source_audio_note = _preview_audio_note(
        preview.get("source_audio_codecs") or [],
        sample=False,
    )

    sample_audio_note = _preview_audio_note(
        preview.get("sample_audio_codecs") or [],
        sample=True,
    )

    source_audio_html = (
        f"<p class=\"muted\">{source_audio_note}</p>"
        if source_audio_note else ""
    )

    sample_audio_html = (
        f"<p class=\"muted\">{sample_audio_note}</p>"
        if sample_audio_note else ""
    )

    sample_video_note = ""

    if str(
        preview.get("operation") or ""
    ) in ("codec_conversion", "codec_conversion_mkv"):
        sample_video_note = (
            "<p class=\"muted\">HEVC video does not play in "
            "every browser. If the preview picture stays "
            "blank, the sample file itself is unaffected.</p>"
        )

    if preview.get("has_artifact"):
        players = f"""
<div class="card">
<div class="preview-players">
<div class="preview-pane">
<h3>Original</h3>
<video id="preview-original-player" controls
preload="metadata" src="/preview/{token}/original"></video>
<p class="muted">Full movie playback from the selected
preview position.</p>
{source_audio_html}
</div>
<div class="preview-pane">
<h3>Preview</h3>
<video controls preload="metadata" src="/preview/{token}/sample"></video>
<p class="muted">Temporary ~10-second transformed sample at
the selected position.</p>
{sample_audio_html}
{sample_video_note}
<p><a class="btn ghost" href="/preview/{token}/sample" download>Download preview copy for local playback checking</a></p>
<p class="muted">Some video and audio codecs are not supported
by every browser. You can download this Preview and open it
with a local media player such as VLC or MPV to check the
generated file directly. This downloads the generated Preview
artifact itself; nothing in your library is changed.</p>
</div>
</div>
</div>
"""
    elif summary["blocked_headline"]:
        # The blocked headline is presented in the Preview status
        # cell of the header card and in the error panel above, so
        # no separate full-width players card is rendered here.
        players = ""
    else:
        # The no-sample guidance lives in the Preview status cell
        # of the header card, keeping the comparison controls
        # immediately below the header.
        players = ""

    generate_form = ""

    form_message = raw_form_message

    error_text = preview.get("error") or ""

    error_block = ""

    # When the friendly blocked headline is shown — or when a
    # failed generation is summarised with the friendly primary
    # message above — the raw builder error stays available
    # under Technical details only: repeating it here would show
    # the same raw FFmpeg error twice on one page.
    if (
        error_text
        and error_text != form_message
        and not summary["blocked_headline"]
        and not generation_failed
    ):
        error_block = (
            f'<div class="notice">'
            f"{esc(error_text)}</div>"
        )

    notice = (
        f'<div class="notice">{esc(data["notice"])}</div>'
        if data.get("notice")
        else ""
    )

    if show_accept:
        accept_form = f"""
<div class="preview-action">
<form method="post" action="/preview/{token}/accept">
<p><button class="btn" type="submit">Accept and queue this optimisation</button></p>
<p class="muted">Queues the exact operation currently
represented by the Preview through the existing approval
boundary. Nothing runs until the queue runs it.</p>
<h3>Original file</h3>
<p><label class="check-label">
<input type="radio" name="delete_original" value="" checked>
Keep original
</label></p>
<p><label class="check-label">
<input type="radio" name="delete_original" value="true">
Delete original after successful optimisation
</label></p>
<p class="muted">The original will only be deleted after the
optimised file has completed successfully and passed the
existing verification and currency safeguards.</p>
</form>
</div>
"""
    else:
        accept_form = ""

    reject_form = f"""
<div class="preview-action danger">
<form method="post" action="/preview/{token}/reject">
<h3>Reject optimisation</h3>
<p class="muted">Reject this optimisation opportunity. Nothing
is queued or executed.</p>
<p><button class="btn btn-danger" type="submit">Reject optimisation</button></p>
</form>
</div>
"""

    preserve_actions = _preview_preserve_actions(preview)

    acknowledge_action = _preview_acknowledge_action(
        preview, summary
    )

    loading_script = """
<script>
(function () {
  function arm(form) {
    form.addEventListener("submit", function () {
      var scoped = form.querySelectorAll(
        'button[type="submit"]'
      );
      for (var i = 0; i < scoped.length; i++) {
        scoped[i].disabled = true;
      }
      var competing = document.querySelectorAll(
        'form[data-preview-generate] button[type="submit"]'
      );
      for (var j = 0; j < competing.length; j++) {
        competing[j].disabled = true;
      }
      var note = document.createElement("p");
      note.className = "muted";
      note.textContent =
        "Loading new preview… Hold on, almost there…";
      form.appendChild(note);
    });
  }
  var forms = document.querySelectorAll(
    "form[data-preview-generate]"
  );
  for (var k = 0; k < forms.length; k++) {
    arm(forms[k]);
  }
})();
</script>
"""

    options_schema = data.get("operation_schema") or {}

    if (options_schema.get("parameters") or []):
        options_block = f"""
<details class="disclosure preview-disclosure"><summary>Extended options</summary>
<div class="card"><div class="card-head"><h2>Explicit override</h2></div>
{_preview_override_form(preview, data.get("operation_schema"))}
</div>
</details>
"""
    else:
        options_block = ""

    position_html = _preview_position_block(
        preview, data.get("settings")
    )

    decision_html = f"""
<div class="card"><div class="card-head"><h2>What would you like to do?</h2></div>
<div class="preview-actions">
{_preview_current_operation_block(preview)}
{preserve_actions}
{accept_form}
{acknowledge_action}
{reject_form}
<p><a class="btn ghost" href="{back_href}">Back to opportunity</a></p>
</div>
</div>
"""

    if summary["has_blocked"]:
        middle_html = f"""
{_preview_retention_block(preview, summary)}

{decision_html}

{position_html}
"""
    else:
        middle_html = f"""
{position_html}

{_preview_retention_block(preview, summary)}

{decision_html}
"""

    if summary["blocked_headline"]:
        status_body = (
            f'<p><span class="status-marker status-blocked" '
            f'aria-hidden="true">●</span>'
            f'{summary["blocked_headline"]}</p>'
        )
    elif generation_failed:
        status_body = (
            '<p><span class="status-marker status-blocked" '
            'aria-hidden="true">●</span>'
            'Preview unavailable</p>'
        )
    elif preview.get("has_artifact"):
        status_body = (
            '<p><span class="status-marker status-ready '
            'status-glimmer" '
            'aria-hidden="true">●</span>'
            'Preview ready</p>'
        )
    elif status == "accepted":
        status_body = (
            '<p><span class="status-marker status-ready" '
            'aria-hidden="true">●</span>'
            'Queued</p>'
        )
    elif status == "rejected":
        status_body = (
            '<p><span class="status-marker status-neutral" '
            'aria-hidden="true">●</span>'
            'Rejected</p>'
        )
    else:
        status_body = (
            '<p><span class="status-marker status-neutral" '
            'aria-hidden="true">●</span>'
            'No preview sample yet. Choose a position below, '
            'then generate a snapshot to compare.</p>'
        )

    content = f"""
<div class="card preview-head"><div class="preview-head-grid">
<div class="preview-head-summary">
<div class="card-head"><h2>Preview summary</h2></div>
<p class="muted"><strong>{esc(preview.get("file_name") or "")}</strong>
· {esc(origin_label)} · {esc(_preview_timestamp_text(preview))}</p>
</div>
<div class="preview-head-status">
<div class="card-head"><h2>Preview status</h2></div>
{status_body}
</div>
</div></div>

{error_block}

{players}

{middle_html}
{loading_script}
{state_block}

<details class="disclosure preview-disclosure"><summary>Extended information</summary>
<div class="card"><div class="card-head"><h2>Recommended optimisation</h2></div>
<p><strong>{esc(operation_title)}</strong></p>
<dl class="preview-params">{fact_rows}</dl>
{technical_block}
{override_block}
</div>

<div class="card"><div class="card-head"><h2>Retention detail</h2></div>
{_preview_retention_details(preview)}
</div>
</details>
{options_block}
"""

    return layout(
        "Optimisation Preview", "opportunities",
        _form_error_panel(data) + notice + content,
        refreshed_at=data.get("refreshed_at"),
    )
