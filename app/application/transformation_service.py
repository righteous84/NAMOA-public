"""Requested-transformation application service (Phase 6).

Owns requested-transformation semantics: building the immutable
approved transformation from surviving recommendation signals or from
user-selected advanced parameters, validating parameters against the
closed operation registry, and resolving the executable operation.

It never creates intelligence, never executes anything, and never
duplicates recommendation/decision semantics. The transformation is a
record of what the user approved, distinct from the recommendation and
from the execution plan.
"""

import json

from app.execution.operations import (
    EXECUTABLE_OPERATIONS,
    OPERATION_CODEC_CONVERSION,
    OPERATION_CODEC_CONVERSION_MKV,
    OPERATION_REMUX_MP4,
    get_operation,
    operation_for_proposition,
    require_operation,
    validate_parameters,
)

from app.models.transformation import (
    RequestedTransformation,
    TransformationProposition,
    AUDIO_HANDLING_COPY,
)


class NoExecutablePropositionError(ValueError):
    """
    Raised when a candidate carries no surviving executable
    proposition. Distinct from parameter-validation ValueErrors so the
    approval boundary can distinguish "nothing executable to approve"
    (legacy fallback) from "the supplied parameters are invalid"
    (must propagate).
    """


class TransformationService:
    """
    Application-facing requested-transformation workflows.
    """

    def __init__(
        self,
        *,
        operation_service=None,
    ):

        self.operation_service = operation_service

    # -------------------------------------------------
    # Construction
    # -------------------------------------------------

    def build_from_candidate(
        self,
        candidate,
        *,
        recommendation_id=None,
        parameters=None,
        delete_original_requested=False,
    ) -> RequestedTransformation:
        """
        Build the requested transformation from a current-valid
        candidate's surviving proposition signals.

        Surviving signals are the opportunity signals whose
        proposition was not suppressed by fusion. A proposition
        without an executable operation cannot be approved and is
        refused (the approval boundary must not approve what cannot
        execute).

        `parameters` (advanced path) are validated against the
        resolved operation definition. When omitted the operation
        defaults apply.
        """

        signals = list(getattr(candidate, "signals", ()) or ())

        suppressed = set(
            getattr(candidate, "suppressed_propositions", ())
            or ()
        )

        suppressed.update(
            getattr(
                candidate,
                "standing_suppressed_propositions",
                (),
            )
            or ()
        )

        surviving = [
            signal
            for signal in signals
            if (
                getattr(signal, "direction", "")
                in ("optimize", "remux")
            )
            and (
                getattr(signal, "proposition", "")
                not in suppressed
            )
        ]

        if not surviving:

            raise NoExecutablePropositionError(
                "the recommendation carries no surviving "
                "executable proposition; nothing to approve"
            )

        # Resolve the primary executable operation from the first
        # surviving proposition that maps to an executable operation.
        operation = None

        chosen = None

        for signal in surviving:

            proposition = getattr(signal, "proposition", "")

            candidate_operation = (
                operation_for_proposition(proposition)
            )

            if candidate_operation in EXECUTABLE_OPERATIONS:

                operation = candidate_operation

                chosen = signal

                break

        if operation is None:

            raise NoExecutablePropositionError(
                "none of the surviving propositions maps to an "
                "executable operation; nothing can be approved"
            )

        # For codec_conversion the target codec must be validated
        # against the operation definition (HEVC only in this phase).
        validated = validate_parameters(
            operation,
            parameters,
        )

        operation_definition = require_operation(operation)

        propositions = []

        for signal in surviving:

            proposition = getattr(signal, "proposition", "")

            mapped = operation_for_proposition(proposition)

            if mapped != operation:

                continue

            propositions.append(
                TransformationProposition(
                    proposition=proposition,
                    current_state=getattr(
                        signal, "current_state", None
                    ),
                    target_state=getattr(
                        signal, "target_state", None
                    ),
                    parameters=dict(validated),
                )
            )

        if not propositions:

            propositions.append(
                TransformationProposition(
                    proposition=(
                        "container_remux"
                        if operation == OPERATION_REMUX_MP4
                        else "codec_conversion"
                    ),
                    current_state=(
                        getattr(chosen, "current_state", None)
                    ),
                    target_state=(
                        getattr(chosen, "target_state", None)
                    ),
                    parameters=dict(validated),
                )
            )

        return RequestedTransformation(
            source="recommendation",
            recommendation_id=recommendation_id,
            propositions=tuple(propositions),
            operation=operation,
            preserve_resolution=bool(
                operation_definition.expected_output.get(
                    "preserve_resolution", True
                )
            ),
            preserve_hdr=bool(
                operation_definition.expected_output.get(
                    "preserve_hdr", True
                )
            ),
            audio_handling=AUDIO_HANDLING_COPY,
            captured_from_run_id=getattr(
                candidate, "analysis_run_id", None
            ),
            captured_from_observation_id=getattr(
                candidate, "observation_id", None
            ),
            parameters=dict(validated),
        )

    def build_from_advanced(
        self,
        *,
        operation,
        parameters=None,
        recommendation_id=None,
        preserve_resolution=True,
        preserve_hdr=True,
        audio_handling=AUDIO_HANDLING_COPY,
        captured_from_run_id=None,
        captured_from_observation_id=None,
    ) -> RequestedTransformation:
        """
        Build the requested transformation from a user-selected
        operation and validated parameters (advanced path).

        The operation must be executable and registered. Parameters
        are validated against the operation definition; a free-form
        value can never reach the registry.
        """

        if operation not in EXECUTABLE_OPERATIONS:

            raise ValueError(
                f"operation '{operation}' is not executable"
            )

        validated = validate_parameters(
            operation,
            parameters,
        )

        operation_definition = require_operation(operation)

        proposition = (
            "container_remux"
            if operation == OPERATION_REMUX_MP4
            else "codec_conversion"
            if operation
            in (
                OPERATION_CODEC_CONVERSION,
                OPERATION_CODEC_CONVERSION_MKV,
            )
            else operation
        )

        return RequestedTransformation(
            source="advanced",
            recommendation_id=recommendation_id,
            propositions=(
                TransformationProposition(
                    proposition=proposition,
                    target_state=validated.get("target_codec"),
                    parameters=dict(validated),
                ),
            ),
            operation=operation,
            preserve_resolution=preserve_resolution,
            preserve_hdr=preserve_hdr,
            audio_handling=audio_handling,
            captured_from_run_id=captured_from_run_id,
            captured_from_observation_id=(
                captured_from_observation_id
            ),
            parameters=dict(validated),
        )

    # -------------------------------------------------
    # Serialization
    # -------------------------------------------------

    def serialize(self, transformation) -> dict:
        return transformation.to_dict()

    def parse(self, payload) -> RequestedTransformation | None:
        return RequestedTransformation.from_dict(payload)

    def to_json(self, transformation) -> str:
        return json.dumps(
            transformation.to_dict(),
            indent=2,
        )

    def resolve_operation(self, transformation) -> str:
        """
        The operation a transformation resolves to, validated against
        the registry. Raises ValueError for a non-executable or
        unregistered operation.
        """

        operation = transformation.operation

        definition = get_operation(operation)

        if definition is None:
            raise ValueError(
                f"transformation operation '{operation}' is not "
                "registered"
            )

        if not definition.executable:
            raise ValueError(
                f"transformation operation '{operation}' is not "
                "executable"
            )

        return operation