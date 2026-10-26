"""
Preference match dimensions (Phase 15, Phase A).

Single versioned allowlist of dimensions the preference compiler may
use. Semantic attributes (actor, director, studio, genre, year, title
and arbitrary free text) are structurally excluded: the condition
builder accepts only the keys listed here, and anything else raises.
"""

# Semantic version of the dimension vocabulary and normalisation
# behaviour. Any addition, removal, redefinition, or band change
# MUST bump this version in the same change.
DIMENSIONS_VERSION = "1.0.0"

# Strong dimensions: discrete measured technical facts. Any of these
# may appear in a rule alone or in combination.
STRONG_DIMENSIONS = frozenset({
    "media_type",
    "resolution",
    "codec",
    "bitrate_class",
    "hdr",
    "container",
    "category",
    "audio_codec",
})

# Contextual dimensions: refinements only. A rule whose conditions
# use ONLY contextual dimensions is never emitted by the compiler;
# contextual conditions may narrow a rule that already carries at
# least one strong condition.
CONTEXTUAL_DIMENSIONS = frozenset({
    "collection",
    "tag",
    "source_label",
    "size_class",
    "audio_channels",
})

# Explicitly excluded semantic vocabulary. Listed so the exclusion is
# reviewable; enforcement is structural (anything not allowlisted
# raises), not by blocklist matching.
EXCLUDED_DIMENSIONS = frozenset({
    "actor",
    "director",
    "studio",
    "genre",
    "year",
    "title",
})

ALLOWED_DIMENSIONS = STRONG_DIMENSIONS | CONTEXTUAL_DIMENSIONS

# Fixed tie-break order for deterministic dimension removal during
# generalisation. Recorded as compiler-version behaviour: least
# discriminating dimension first (fewest distinct values across the
# example population); ties broken by lowest index here.
DIMENSION_ORDER = (
    "media_type",
    "category",
    "resolution",
    "codec",
    "container",
    "hdr",
    "audio_codec",
    "bitrate_class",
    "collection",
    "tag",
    "source_label",
    "size_class",
    "audio_channels",
)

# Minimum consistent examples sharing all remaining conditions before
# a broader rule may be emitted. Architect-confirmed default.
GENERALISATION_THRESHOLD_N = 3

# Wizard answers. Presentation labels ("Keep quality", "Not sure")
# map to these canonical values at the UI boundary, which is outside
# Phase A scope. Unknown answers raise.
ANSWERS = frozenset({
    "Keep",
    "Balanced",
    "Optimise",
    "Leave-alone",
})

_RESOLUTION_BUCKETS = ("2160p", "1080p", "720p", "480p")

_BITRATE_CLASSES = ("low", "standard", "high")

_SIZE_CLASSES = ("small", "medium", "large")

_MEDIA_TYPES = ("movie", "tv")


def normalise_dimension(dimension: str, value):
    """
    Normalise one raw fact value to its canonical match value.

    Normative case contract (compiler version 1.0.0 behaviour):

    - media_type: stripped and lowercased; must be movie/tv.
    - codec, hdr, container, audio_codec: stripped, then
      uppercased (HEVC, HDR10, MKV); other casing never matches.
    - resolution, bitrate_class, size_class: integers map to
      lowercased bucket labels (2160p, high, large); supplied
      strings are stripped and lowercased, then validated.
    - category, collection, tag, source_label: stripped only;
      case is preserved exactly, so "Anime" and "anime" are
      different values. The authoritative instruction does not
      require broader case normalisation; this is intentional,
      not an oversight.
    - audio_channels: integer channel count, no case concept.

    Raises ValueError for unknown dimensions, excluded dimensions,
    and invalid values, so none of those can silently enter a rule.
    """

    if dimension not in ALLOWED_DIMENSIONS:
        if dimension in EXCLUDED_DIMENSIONS:
            raise ValueError(
                f"dimension '{dimension}' is excluded from "
                "preference matching"
            )
        raise ValueError(
            f"unknown preference dimension '{dimension}'"
        )

    if dimension == "media_type":
        text = str(value).strip().lower()
        if text not in _MEDIA_TYPES:
            raise ValueError(
                f"invalid media_type '{value}' "
                "(expected 'movie' or 'tv')"
            )
        return text

    if dimension == "resolution":
        if isinstance(value, bool):
            raise ValueError(
                f"invalid resolution '{value}'"
            )
        if isinstance(value, int):
            if value >= 2160:
                return "2160p"
            if value >= 1080:
                return "1080p"
            if value >= 720:
                return "720p"
            return "480p"
        text = str(value).strip().lower()
        if text not in _RESOLUTION_BUCKETS:
            raise ValueError(
                f"invalid resolution '{value}'"
            )
        return text

    if dimension == "bitrate_class":
        if isinstance(value, bool):
            raise ValueError(
                f"invalid bitrate_class '{value}'"
            )
        if isinstance(value, int):
            if value >= 20_000_000:
                return "high"
            if value >= 8_000_000:
                return "standard"
            return "low"
        text = str(value).strip().lower()
        if text not in _BITRATE_CLASSES:
            raise ValueError(
                f"invalid bitrate_class '{value}'"
            )
        return text

    if dimension == "size_class":
        if isinstance(value, bool):
            raise ValueError(
                f"invalid size_class '{value}'"
            )
        if isinstance(value, int):
            if value >= 10 * 1024 * 1024 * 1024:
                return "large"
            if value >= 1024 * 1024 * 1024:
                return "medium"
            return "small"
        text = str(value).strip().lower()
        if text not in _SIZE_CLASSES:
            raise ValueError(
                f"invalid size_class '{value}'"
            )
        return text

    if dimension == "audio_channels":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                f"invalid audio_channels '{value}' "
                "(expected channel count)"
            )
        if value <= 0:
            raise ValueError(
                f"invalid audio_channels '{value}'"
            )
        return value

    text = str(value).strip()

    if not text:
        raise ValueError(
            f"invalid {dimension} '{value}' (empty value)"
        )

    if dimension in ("codec", "hdr", "container", "audio_codec"):
        return text.upper()

    return text
