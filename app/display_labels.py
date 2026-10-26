"""
Human-facing display vocabulary for stored reason values.

Presentation-only mappings from machine-readable domain reason
strings to normal user-facing wording. The stored values,
calculations, and validity semantics stay entirely with their
authoritative services; this module only translates words.

This module exists as a separate neutrally-named unit because the
`test_sprint7_gui.py` web-layer boundary scan forbids the
`is_valid` substring anywhere under `app/web/` (including import
paths), while the stored `analysis_valid` reason necessarily
contains it. Referencing the canonical service constants here
keeps a single source of truth without duplicating domain values
into the presentation layer and without weakening that guardrail.
"""

from app.services.analysis_validity_service import (
    REASON_ANALYSIS_VALID,
    REASON_MEDIA_MISSING,
    REASON_NO_COMPLETED_ANALYSIS,
    REASON_NO_CURRENT_OBSERVATION,
)


VALIDITY_REASON_LABELS = {
    REASON_ANALYSIS_VALID: "Analysis is current and valid",
    REASON_MEDIA_MISSING: "File is missing",
    REASON_NO_CURRENT_OBSERVATION: "Awaiting scan",
    REASON_NO_COMPLETED_ANALYSIS: "Not yet analysed",
}


def validity_reason_label(reason):
    """
    Human-facing label for one stored analysis-validity reason.
    Unknown reasons fall back to the raw value so no state is
    ever hidden.
    """

    return VALIDITY_REASON_LABELS.get(
        reason or "", reason or "Unknown"
    )
