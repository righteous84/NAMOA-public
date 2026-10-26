"""Requested-transformation read model (Phase 6).

A requested transformation is the frozen, immutable representation of
what the user actually approved. It is deliberately distinct from:

- the recommendation that caused the approval
- the execution plan generated from the approval

It is captured at approval time (from surviving signals, or from
user-selected advanced parameters) and never rewritten.
"""

from dataclasses import dataclass, field
from typing import Any, Optional


#: Payload schema version. A structural change to the payload that
#: changes its meaning MUST bump this version.
TRANSFORMATION_SCHEMA_VERSION = 1

#: Source of the requested transformation.
SOURCE_RECOMMENDATION = "recommendation"
SOURCE_ADVANCED = "advanced"
#: Source marker for an explicit user override of a recommendation.
#: The transformation still derives from the closed operation
#: registry and validated parameters; the marker (plus
#: ``context_detail``) preserves the distinction between a system
#: recommendation and a user-selected override in provenance.
SOURCE_USER_OVERRIDE = "user-override"

#: Audio handling modes (closed set).
AUDIO_HANDLING_COPY = "copy"
AUDIO_HANDLING_CONVERT = "convert"
AUDIO_HANDLING_REMOVE = "remove"


@dataclass(frozen=True, slots=True)
class TransformationProposition:
    """
    One selected change within a requested transformation. Carries the
    structured proposition identity and the current/target states the
    user approved.
    """

    proposition: str
    current_state: Optional[str] = None
    target_state: Optional[str] = None
    parameters: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "proposition": self.proposition,
            "current_state": self.current_state,
            "target_state": self.target_state,
            "parameters": dict(self.parameters),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "TransformationProposition":
        return cls(
            proposition=payload.get("proposition", ""),
            current_state=payload.get("current_state"),
            target_state=payload.get("target_state"),
            parameters=dict(payload.get("parameters") or {}),
        )


@dataclass(frozen=True, slots=True)
class RequestedTransformation:
    """
    The immutable approved transformation.

    `delete_original_after_success` is deliberately NOT part of this
    semantic. Deletion is a separate file-lifecycle action stored as
    `delete_original_requested` on the execution record (default
    false).
    """

    schema_version: int = TRANSFORMATION_SCHEMA_VERSION

    source: str = SOURCE_RECOMMENDATION

    recommendation_id: Optional[int] = None

    propositions: tuple = ()

    operation: str = ""

    preserve_resolution: bool = True

    preserve_hdr: bool = True

    audio_handling: str = AUDIO_HANDLING_COPY

    captured_from_run_id: Optional[int] = None

    captured_from_observation_id: Optional[int] = None

    parameters: dict = field(default_factory=dict)

    #: Optional provenance detail for explicit user overrides and
    #: preview contexts (for example origin stream, suggestion id,
    #: preview token). Empty for plain recommendation approvals.
    #: Additive and optional: payloads written before this field
    #: existed read back as empty, so no migration is required.
    context_detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "recommendation_id": self.recommendation_id,
            "propositions": [
                p.to_dict() for p in self.propositions
            ],
            "operation": self.operation,
            "preserve_resolution": self.preserve_resolution,
            "preserve_hdr": self.preserve_hdr,
            "audio_handling": self.audio_handling,
            "captured_from_run_id": self.captured_from_run_id,
            "captured_from_observation_id": (
                self.captured_from_observation_id
            ),
            "parameters": dict(self.parameters),
            "context_detail": dict(self.context_detail),
        }

    @classmethod
    def from_dict(
        cls,
        payload: Optional[dict],
    ) -> Optional["RequestedTransformation"]:
        if not isinstance(payload, dict):
            return None

        return cls(
            schema_version=payload.get(
                "schema_version", TRANSFORMATION_SCHEMA_VERSION
            ),
            source=payload.get("source", SOURCE_RECOMMENDATION),
            recommendation_id=payload.get("recommendation_id"),
            propositions=tuple(
                TransformationProposition.from_dict(p)
                for p in (payload.get("propositions") or [])
                if isinstance(p, dict)
            ),
            operation=payload.get("operation", ""),
            preserve_resolution=bool(
                payload.get("preserve_resolution", True)
            ),
            preserve_hdr=bool(payload.get("preserve_hdr", True)),
            audio_handling=payload.get(
                "audio_handling", AUDIO_HANDLING_COPY
            ),
            captured_from_run_id=payload.get(
                "captured_from_run_id"
            ),
            captured_from_observation_id=payload.get(
                "captured_from_observation_id"
            ),
            parameters=dict(payload.get("parameters") or {}),
            context_detail=dict(
                payload.get("context_detail") or {}
            ),
        )