import json
from pathlib import Path


# Documented conservative default for an evidence source that has no
# configured active weight. Unknown sources are neither trusted nor
# distrusted outright; the default is part of the attributable policy
# snapshot so historical runs record exactly what was in force.
UNKNOWN_SOURCE_DEFAULT = 0.5

ACTIVE_POLICY_NAME = "active-evidence-source-trust"


class EvidenceWeightService:
    """
    Provides configurable trust weights for ACTIVE evidence sources.

    Semantic policy (Sprint 10 correction):

    - Only sources that actually produce classification evidence in
      the running system are configured under "sources". These values
      are production intelligence and participate in run attribution.
    - Sources listed under "reserved_sources" document intended future
      trust ordering. They are NOT active intelligence: no component
      may read them as weights, and they must never be formalised as
      if they influenced a result.

    This service does not interpret evidence.
    It only supplies configuration values and the attributable policy
    snapshot.
    """

    def __init__(self):

        self.config_path = (
            Path(__file__)
            .resolve()
            .parents[2]
            / "config"
            / "evidence_weights.json"
        )

        self.weights = self._load()

    def _load(self):

        if not self.config_path.exists():
            return {
                "policy": ACTIVE_POLICY_NAME,
                "sources": {},
                "unknown_source_default": (
                    UNKNOWN_SOURCE_DEFAULT
                ),
                "reserved_sources": {},
            }

        with open(self.config_path, "r") as file:
            return json.load(file)

    def get_source_weight(
        self,
        source: str
    ) -> float:
        """
        Return trust multiplier for an ACTIVE evidence source.

        An unconfigured source receives the documented conservative
        default rather than silent full trust.
        """

        sources = self.weights.get(
            "sources",
            {}
        )

        if source in sources:
            return sources[source]

        return self.get_unknown_source_default()

    def get_unknown_source_default(self) -> float:

        value = self.weights.get(
            "unknown_source_default",
            UNKNOWN_SOURCE_DEFAULT,
        )

        try:
            return float(value)
        except (TypeError, ValueError):
            return UNKNOWN_SOURCE_DEFAULT

    def active_policy(self) -> dict:
        """
        The attributable evidence-weighting policy snapshot for a run:
        active source weights, the unknown-source default, and the
        names of reserved-but-inactive sources.
        """

        return {
            "policy": self.weights.get(
                "policy",
                ACTIVE_POLICY_NAME,
            ),
            "sources": dict(
                self.weights.get("sources", {})
            ),
            "unknown_source_default": (
                self.get_unknown_source_default()
            ),
            "reserved_source_names": sorted(
                self.weights.get(
                    "reserved_sources",
                    {}
                ).keys()
            ),
        }
