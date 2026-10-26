"""
Recommendation semantics service.

Generates the human-readable interpretation of an
OpportunityAssessment. Recommendations are the human-readable
interpretation of the opportunity: WHAT is present, WHAT is
suboptimal, WHAT should change, WHY, EVIDENCE, BENEFIT, RISK /
trade-off, and POLICY influence.

The narrative is derived from the structured assessment and its
surviving proposition signals; it is never disconnected free text.
Internal numerical values remain available for engineering views, but
ordinary presentation favours explanation over unexplained numbers.

This is part of the existing recommendation layer (policy versioned
with this component). It is not a second recommendation engine.
"""

from app.models.opportunity_assessment import OpportunityAssessment


class RecommendationSemanticsService:
    """
    Versioned recommendation-semantics policy for building human
    readable recommendations and preservation conclusions.
    """

    semantic_version = "1.0.0"

    # ---------------------------------------------------------
    # Summary line
    # ---------------------------------------------------------

    @staticmethod
    def summary(
        assessment,
    ) -> str:
        """
        One-line human summary for an assessment.

            none         -> "No recommendation."
            weak         -> "Low optimisation opportunity."
            meaningful   -> "Medium optimisation opportunity."
            strong       -> "High optimisation opportunity."
        """

        if assessment is None:
            return "No recommendation."

        level = getattr(
            assessment,
            "opportunity_level",
            "none",
        )

        return SUMMARY_LINES.get(
            level,
            SUMMARY_LINES["none"],
        )

    # ---------------------------------------------------------
    # Full narrative
    # ---------------------------------------------------------

    @staticmethod
    def narrative(
        assessment,
        *,
        policy_payload=None,
    ) -> list:
        """
        Human-readable narrative lines for an assessment.

        For a worthwhile opportunity the narrative explains what is
        currently present, what is suboptimal, what should change, why,
        what evidence supports it, what benefit is expected, what
        trade-off or risk exists, and what policy influenced the
        result.

        For a preservation conclusion the narrative explains why no
        worthwhile improvement exists.
        """

        if assessment is None:
            return ["No recommendation."]

        level = getattr(
            assessment,
            "opportunity_level",
            "none",
        )

        if level == "none":
            return RecommendationSemanticsService._preservation_narrative(
                assessment,
            )

        lines = [
            f"{RecommendationSemanticsService.summary(assessment)}",
        ]

        active_signals = list(
            getattr(assessment, "active_signals", []) or []
        )

        if not active_signals:
            active_signals = [
                s
                for s in (assessment.signals or [])
                if s.direction in ("optimize", "remux")
            ]

        for signal in active_signals:
            lines.extend(
                RecommendationSemanticsService._proposition_lines(
                    signal,
                )
            )

        if assessment.preservation_reasons:

            lines.append("Preservation considerations:")

            for reason in assessment.preservation_reasons:
                lines.append(f"- {reason}.")

        if assessment.suppressed_signals:

            lines.append("Suppressed propositions:")

            for item in assessment.suppressed_signals:
                lines.append(
                    f"- {item.get('proposition')}: "
                    f"{item.get('reason')}."
                )

        if policy_payload:
            lines.append(
                "Policy: "
                f"{policy_payload.get('aggressiveness', 'standard')} "
                "aggressiveness, encoding speed "
                f"'{policy_payload.get('encoding_speed', 'normal')}'."
            )

        return lines

    @staticmethod
    def _proposition_lines(signal) -> list:
        """
        Human lines for one surviving proposition signal.
        """

        lines = []

        current = signal.current_state or "the current state"
        target = signal.target_state or "a more efficient target"

        if signal.rule == "codec_rule":

            lines.append(
                f"The video is encoded with {current}. "
                f"Converting it to {target} is expected to reduce "
                "storage while preserving the current resolution and "
                "HDR characteristics."
            )

        elif signal.rule == "bitrate_rule":

            lines.append(
                f"The video uses {current}, which is materially "
                f"higher than necessary for its resolution and "
                "codec. Reducing the bitrate toward "
                f"{target} is expected to reduce storage without "
                "changing the resolution."
            )

        elif signal.rule == "audio_rule":

            lines.append(
                f"The audio track uses {current}. Converting it to "
                f"{target} could reduce storage without changing the "
                "video stream, at a lossy quality trade-off."
            )

        elif signal.rule == "container_rule":

            lines.append(
                f"The file uses the {current} container. Remuxing to "
                f"{target} improves compatibility and handling; this "
                "is not a storage-saving change."
            )

        elif signal.rule == "resolution_rule":

            lines.append(
                f"The current {current} resolution appears inflated "
                f"for its source; reducing it to {target} is expected "
                "to save storage but carries a significant quality "
                "trade-off."
            )

        else:

            lines.append(
                f"{current} -> {target}."
            )

        if signal.reason:
            lines.append(f"Why: {signal.reason}")

        if signal.benefit and signal.benefit != "none":
            lines.append(
                f"Expected benefit: {signal.benefit}."
            )

        trade_offs = []

        if signal.cost and signal.cost != "none":
            trade_offs.append(f"{signal.cost} {signal.rule.split('_')[0]} cost")

        if signal.risk and signal.risk != "unknown":
            trade_offs.append(f"{signal.risk} risk")

        if trade_offs:
            lines.append(
                "Primary trade-off: "
                + ", ".join(trade_offs)
                + "."
            )

        return lines

    @staticmethod
    def _preservation_narrative(assessment) -> list:
        """
        Human lines explaining why no worthwhile improvement exists.
        """

        lines = ["No recommendation."]

        reasons = list(
            assessment.preservation_reasons or []
        )

        if not reasons:
            reasons = [
                signal.reason
                for signal in (assessment.signals or [])
                if signal.direction == "preserve"
                and signal.reason
            ]

        if reasons:
            lines.append(
                "This file does not present a worthwhile "
                "improvement under the current policy:"
            )
            for reason in reasons:
                lines.append(f"- {reason}.")

        if assessment.suppressed_signals:
            lines.append("Considered but suppressed:")
            for item in assessment.suppressed_signals:
                lines.append(
                    f"- {item.get('proposition')}: "
                    f"{item.get('reason')}."
                )

        return lines


SUMMARY_LINES = {
    "none": "No recommendation.",
    "weak": "Low optimisation opportunity.",
    "meaningful": "Medium optimisation opportunity.",
    "strong": "High optimisation opportunity.",
}