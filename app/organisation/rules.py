"""
Versioned organisation rule components (Sprint 13 INTELLIGENCE).

Each rule component is deterministic, pure (no filesystem, no
database access), explainable, and declares its own
semantic_version following the established versioning invariant:

> Any change that can alter the analytical meaning of a rule
> component requires its semantic version to change. Existing
> semantic versions are never reused for different semantics.

Rule components consume organisation EVIDENCE only (facts
derived from persisted filesystem observations). They never
invoke optimisation experts, the decision engine, or execution,
and they never merge media identities.
"""

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------
# Library classification rules
# ---------------------------------------------------------

CATEGORY_MOVIES = "movies"

CATEGORY_TV = "tv"

CATEGORY_UNCLASSIFIED = "unclassified"


@dataclass(frozen=True, slots=True)
class ClassificationResult:

    category: str

    confidence: float

    reasoning: list = field(default_factory=list)


class LibraryClassificationRules:
    """
    Classify a lineage's library category from its filename and
    current path segments.

    Conservative under uncertainty: an unrecognised item is
    UNCLASSIFIED and receives NO destination proposal rather
    than a guessed destination.
    """

    name = "library_classification_rules"

    semantic_version = "1.0.0"

    # Episode-style markers: S01E02, s1e2, 1x02, "episode 4".
    TV_EPISODE_PATTERN = re.compile(
        r"s\d{1,2}\s?e\d{1,3}",
        re.IGNORECASE,
    )

    TV_CROSS_PATTERN = re.compile(
        r"(?<!\d)\d{1,2}x\d{1,2}(?!\d)",
        re.IGNORECASE,
    )

    TV_WORD_PATTERN = re.compile(
        r"\b(season|serie|series|episode)\b",
        re.IGNORECASE,
    )

    # Directory segments that indicate television libraries.
    TV_PATH_SEGMENTS = frozenset(
        {"tv", "tv shows", "shows", "series", "seasons"}
    )

    # A plausible release year in a filename suggests a movie.
    MOVIE_YEAR_PATTERN = re.compile(
        r"(?<!\d)(19\d{2}|20\d{2})(?!\d)"
    )

    MOVIES_PATH_SEGMENTS = frozenset({"movies", "films"})

    @classmethod
    def classify(
        self,
        *,
        file_name: str | None,
        path_segments: tuple[str, ...] = (),
    ) -> ClassificationResult:

        name = file_name or ""

        stem = re.sub(
            r"\.[A-Za-z0-9]+$",
            "",
            name,
        )

        lowered_segments = [
            segment.casefold().strip()
            for segment in path_segments
        ]

        # Television markers take precedence: episodic naming
        # inside a movies directory still indicates tv.
        for pattern in (
            self.TV_EPISODE_PATTERN,
            self.TV_CROSS_PATTERN,
            self.TV_WORD_PATTERN,
        ):

            match = pattern.search(stem)

            if match:
                return ClassificationResult(
                    category=CATEGORY_TV,
                    confidence=0.9,
                    reasoning=[
                        "filename episode marker "
                        f"'{match.group(0)}' indicates "
                        "episodic media",
                    ],
                )

        if set(lowered_segments) & self.TV_PATH_SEGMENTS:
            return ClassificationResult(
                category=CATEGORY_TV,
                confidence=0.7,
                reasoning=[
                    f"path segment "
                    f"{sorted(set(lowered_segments) & self.TV_PATH_SEGMENTS)[0]!r}"
                    " indicates a television library",
                ],
            )

        year_match = self.MOVIE_YEAR_PATTERN.search(stem)

        if year_match:
            return ClassificationResult(
                category=CATEGORY_MOVIES,
                confidence=0.8,
                reasoning=[
                    "filename year marker "
                    f"'{year_match.group(0)}' indicates a "
                    "movie",
                ],
            )

        if (
            set(lowered_segments)
            & self.MOVIES_PATH_SEGMENTS
        ):
            return ClassificationResult(
                category=CATEGORY_MOVIES,
                confidence=0.6,
                reasoning=[
                    "path segment indicates a movie "
                    "library",
                ],
            )

        return ClassificationResult(
            category=CATEGORY_UNCLASSIFIED,
            confidence=0.3,
            reasoning=[
                "no deterministic category marker found; "
                "conservatively unclassified",
            ],
        )


# ---------------------------------------------------------
# Naming consistency rules
# ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NamingResult:

    proposed_name: str | None

    changed: bool

    reasoning: list = field(default_factory=list)


class NamingConsistencyRules:
    """
    Propose a consistent filename by normalising separator
    characters only (runs of dots/underscores become single
    spaces).

    Deliberately minimal and reversible-looking: no case
    changes, no content reordering, no information removal. A
    name that would not actually change produces NO proposal.
    """

    name = "naming_consistency_rules"

    semantic_version = "1.0.0"

    SEPARATOR_RUN = re.compile(r"[._]+")

    MULTI_SPACE = re.compile(r"\s+")

    EXTENSION = re.compile(r"^(\..+)$")

    @classmethod
    def proposed_name(
        self,
        file_name: str | None,
    ) -> NamingResult:

        if not file_name:

            return NamingResult(
                proposed_name=None,
                changed=False,
                reasoning=["no filename observed"],
            )

        stem, dot, extension = file_name.rpartition(".")

        if not dot:

            stem = file_name

            extension = ""

        normalised_stem = self.MULTI_SPACE.sub(
            " ",
            self.SEPARATOR_RUN.sub(" ", stem),
        ).strip()

        if extension:

            candidate = f"{normalised_stem}.{extension}"

        else:

            candidate = normalised_stem

        if candidate == file_name or not normalised_stem:

            return NamingResult(
                proposed_name=None,
                changed=False,
                reasoning=[
                    "filename already consistent with the "
                    "naming rules",
                ],
            )

        return NamingResult(
            proposed_name=candidate,
            changed=True,
            reasoning=[
                "separator characters normalised to "
                "single spaces",
            ],
        )


# ---------------------------------------------------------
# Destination template rules
# ---------------------------------------------------------


class DestinationTemplateRules:
    """
    Deterministic destination template over a configured policy
    root and a classification result.

    Purely lexical string construction: this module NEVER
    touches the filesystem. Destination validation belongs to
    the Sprint 14 execution boundary.
    """

    name = "destination_template_rules"

    semantic_version = "1.0.0"

    @staticmethod
    def destination_directory(
        library_root: str,
        category: str,
    ) -> str:
        """
        Purely lexical template: {root}/{category}. The root's
        absolute/relative form is preserved exactly as configured
        (only trailing separators are trimmed).
        """

        root = (library_root or "").rstrip("/")

        if not root:

            return category

        return f"{root}/{category}"

    @staticmethod
    def full_destination(
        destination_directory: str,
        file_name: str,
    ) -> str:

        return (
            f"{destination_directory}"
            "/"
            f"{file_name}"
        )


def select_library_root(
    library_roots: tuple[str, ...] | list,
    current_path: str,
) -> str | None:
    """
    Deterministic root-selection rule shared by destination
    proposals: prefer the configured root that lexically
    contains the current path; otherwise the first configured
    root. Returns None when no roots are configured.
    Accepts plain paths or {path, alias} profile roots.
    """

    cleaned = []

    for root in library_roots or ():
        if isinstance(root, dict):
            root = root.get("path")

        if isinstance(root, str) and root.strip():
            cleaned.append(root.strip())

    library_roots = cleaned

    if not library_roots:

        return None

    from app.organisation.evidence import (
        normalise_path,
    )

    normalized_path = normalise_path(current_path)

    for root in library_roots:

        normalized_root = normalise_path(root)

        if normalized_path.startswith(normalized_root):

            return root

    return library_roots[0]


# ---------------------------------------------------------
# Grouping + ordering rules
# ---------------------------------------------------------

MINIMUM_GROUP_SIZE = 2


class GroupingRules:
    """
    Grouping key rule: lineages belong to the same group when
    their resolved destination directory is identical. Groups
    below the minimum size produce no grouping proposal.
    """

    name = "library_grouping_rules"

    semantic_version = "1.0.0"

    minimum_group_size = MINIMUM_GROUP_SIZE


class OrderingRules:
    """
    Within-group ordering rule: members order deterministically
    by casefolded final filename.
    """

    name = "group_ordering_rules"

    semantic_version = "1.0.0"

    sort_key_name = "final_name_casefold"

    @staticmethod
    def sort_key(final_name: str) -> str:

        return (final_name or "").casefold()


# ---------------------------------------------------------
# Duplicate detection rules
# ---------------------------------------------------------

DUPLICATE_CONFIRMED_CONFIDENCE = 0.99

DUPLICATE_RISK = "medium"


class DuplicateDetectionRules:
    """
    Evidence-backed duplicate detection.

    Semantics (deliberately conservative):

    - A duplicate CANDIDATE requires exact sha256 content-hash
      equality between two lineages' CURRENT observations.
      Byte-identical content is strong DUPLICATE evidence.
    - It is NEVER identity equivalence: candidates never merge,
      rewrite or equate media identities.
    - Weak signals (same size, similar names, same directory)
      are NEVER sufficient on their own. Lineages without a
      recorded hash honestly receive no candidate; hash absence
      is reported as coverage, never fabricated.
    """

    name = "duplicate_detection_rules"

    semantic_version = "1.0.0"

    method = "sha256_exact_current_observation"

    confidence = DUPLICATE_CONFIRMED_CONFIDENCE

    risk = DUPLICATE_RISK

    @staticmethod
    def find_duplicate_groups(
        hashed_lineages,
    ) -> list[dict]:
        """
        Group lineages by exact sha256 equality.

        hashed_lineages: iterable of objects exposing
        media_id, sha256_hash, path/name facts. Returns one
        dict per duplicated hash with the primary member (lowest
        media id) separated from the remaining duplicates.
        """

        by_hash: dict[str, list] = {}

        for lineage in hashed_lineages:

            digest = getattr(lineage, "sha256_hash", None)

            if not digest:
                continue

            by_hash.setdefault(digest, []).append(lineage)

        groups = []

        for digest in sorted(by_hash):

            members = sorted(
                by_hash[digest],
                key=lambda item: item.media_id,
            )

            if len(members) < 2:
                continue

            groups.append(
                {
                    "sha256": digest,
                    "primary": members[0],
                    "duplicates": members[1:],
                }
            )

        return groups




# ---------------------------------------------------------
# Metadata-aware category rules (Sprint 15 INTELLIGENCE)
# ---------------------------------------------------------

#: Verdicts for category suitability assessment.
SUITABLE = "suitable"

INCOMPATIBLE = "incompatible"

INSUFFICIENT_EVIDENCE = "insufficient-evidence"

CONFLICTING_EVIDENCE = "conflicting-evidence"

SUITABILITY_VERDICTS = frozenset(
    {
        SUITABLE,
        INCOMPATIBLE,
        INSUFFICIENT_EVIDENCE,
        CONFLICTING_EVIDENCE,
    }
)


@dataclass(frozen=True, slots=True)
class CategoryDecision:
    """
    One intelligent category decision over normalised
    provider metadata.

    `category` is None when the evidence is insufficient
    or conflicting; callers must surface review state
    rather than place the media.
    """

    category: str | None

    confidence: float

    reasoning: list = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SuitabilityVerdict:
    """
    Suitability of content for one safety-sensitive
    category. Never decided by a single weak signal.
    """

    verdict: str

    reasoning: list = field(default_factory=list)


class MetadataCategoryRules:
    """
    Map normalised provider metadata to a configured
    category using genre sets, collection membership,
    network/studio, and provider flags.

    Input `metadata` is a plain dict built by the
    planning layer from canonical provider records
    (keys used: `genres`, `collections`, `network`,
    `studio`, `provider_flags`, `title`, `year`).
    `categories` maps category name to its folder;
    only configured categories can be chosen.

    Conservative by construction: a category is chosen
    only when at least two corroborating signals from
    distinct sources support it, or when an explicit
    collection membership names it. Ties, single
    signals, and empty evidence produce a None
    category so the caller surfaces review state.
    """

    name = "metadata_category_rules"

    semantic_version = "1.0.0"

    confidence = 0.75

    @classmethod
    def _signals(
        cls,
        metadata: dict,
        category: str,
        category_signals: dict,
    ) -> list:
        signals = category_signals.get(category, {})

        matched = []

        genres = {
            str(value).casefold()
            for value in (metadata.get("genres") or [])
        }

        for genre in signals.get("genres", []) or []:
            if str(genre).casefold() in genres:
                matched.append(f"genre '{genre}'")

        collections = {
            str(value).casefold()
            for value in (metadata.get("collections") or [])
        }

        for collection in signals.get("collections", []) or []:
            if str(collection).casefold() in collections:
                matched.append(
                    f"collection '{collection}'"
                )

        network = str(metadata.get("network") or "").casefold()

        studio = str(metadata.get("studio") or "").casefold()

        for outlet in signals.get("networks", []) or []:
            if outlet and (
                str(outlet).casefold() == network
                or str(outlet).casefold() == studio
            ):
                matched.append(f"network/studio '{outlet}'")

        flags = {
            str(value).casefold()
            for value in (
                metadata.get("provider_flags") or []
            )
        }

        for flag in signals.get("provider_flags", []) or []:
            if str(flag).casefold() in flags:
                matched.append(f"provider flag '{flag}'")

        return matched

    @classmethod
    def classify(
        cls,
        *,
        metadata: dict,
        categories: dict,
        category_signals: dict | None = None,
    ) -> CategoryDecision:
        metadata = dict(metadata or {})

        categories = dict(categories or {})

        category_signals = dict(category_signals or {})

        scored = []

        for category in sorted(categories):
            matched = cls._signals(
                metadata, category, category_signals
            )

            collections = {
                str(value).casefold()
                for value in (metadata.get("collections") or [])
            }

            named_by_collection = any(
                str(value).casefold() in collections
                for value in (
                    category_signals.get(category, {}).get(
                        "collections", []
                    )
                    or []
                )
            )

            if named_by_collection or len(matched) >= 2:
                scored.append((category, matched))

        if not scored:
            return CategoryDecision(
                category=None,
                confidence=0.0,
                reasoning=[
                    "no category reached the corroboration "
                    "threshold; review required",
                ],
            )

        scored.sort(key=lambda item: item[0])

        best = max(scored, key=lambda item: len(item[1]))

        contenders = [
            item for item in scored
            if len(item[1]) == len(best[1])
        ]

        if len(contenders) > 1:
            names = sorted(item[0] for item in contenders)
            return CategoryDecision(
                category=None,
                confidence=0.0,
                reasoning=[
                    f"categories {names} tie on evidence; "
                    f"review required",
                ],
            )

        category, matched = best

        return CategoryDecision(
            category=category,
            confidence=cls.confidence,
            reasoning=[
                f"category '{category}' corroborated by "
                f"{'; '.join(sorted(matched))}",
            ],
        )


class CategorySuitabilityRules:
    """
    Assess suitability of content for one safety-sensitive
    category (for example Kids).

    Combines the certification/OfficialRating with at least
    one independent corroborating signal (genre, provider
    kids flag, collection). A single keyword or tag can
    never decide. Conflicting or insufficient evidence
    stays visible as needs-review and never forces
    placement into or out of the category silently.
    """

    name = "category_suitability_rules"

    semantic_version = "1.0.0"

    #: Certifications treated as family-suitable evidence.
    #: Conservative closed set; unknown ratings are not
    #: suitability evidence in either direction.
    FAMILY_CERTIFICATIONS = frozenset(
        {"G", "PG", "TV-G", "TV-Y", "TV-Y7", "U", "Uc"}
    )

    #: Certifications treated as family-incompatible evidence.
    ADULT_CERTIFICATIONS = frozenset(
        {"R", "NC-17", "TV-MA", "18", "X"}
    )

    @classmethod
    def assess(
        cls,
        *,
        metadata: dict,
        category: str,
        category_signals: dict | None = None,
    ) -> SuitabilityVerdict:
        metadata = dict(metadata or {})

        signals = (category_signals or {}).get(category, {})

        certification = str(
            metadata.get("certification") or ""
        ).strip().upper()

        cert_suitable = certification in cls.FAMILY_CERTIFICATIONS

        cert_incompatible = (
            certification in cls.ADULT_CERTIFICATIONS
        )

        corroborating = []

        genres = {
            str(value).casefold()
            for value in (metadata.get("genres") or [])
        }

        for genre in signals.get("genres", []) or []:
            if str(genre).casefold() in genres:
                corroborating.append(f"genre '{genre}'")

        flags = {
            str(value).casefold()
            for value in (
                metadata.get("provider_flags") or []
            )
        }

        for flag in signals.get("provider_flags", []) or []:
            if str(flag).casefold() in flags:
                corroborating.append(
                    f"provider flag '{flag}'"
                )

        collections = {
            str(value).casefold()
            for value in (metadata.get("collections") or [])
        }

        for collection in signals.get("collections", []) or []:
            if str(collection).casefold() in collections:
                corroborating.append(
                    f"collection '{collection}'"
                )

        if cert_suitable and corroborating:
            return SuitabilityVerdict(
                verdict=SUITABLE,
                reasoning=[
                    f"certification '{certification}' plus "
                    f"{'; '.join(sorted(corroborating))}",
                ],
            )

        if cert_incompatible:
            return SuitabilityVerdict(
                verdict=INCOMPATIBLE,
                reasoning=[
                    f"certification '{certification}' is "
                    f"incompatible with '{category}'",
                ],
            )

        if cert_suitable or corroborating:
            return SuitabilityVerdict(
                verdict=INSUFFICIENT_EVIDENCE,
                reasoning=[
                    "only a single suitability signal; "
                    "certification plus independent "
                    "corroboration is required",
                ],
            )

        return SuitabilityVerdict(
            verdict=INSUFFICIENT_EVIDENCE,
            reasoning=[
                "no suitability evidence; review required",
            ],
        )


RULE_COMPONENT_CLASSES = (
    LibraryClassificationRules,
    NamingConsistencyRules,
    DestinationTemplateRules,
    GroupingRules,
    OrderingRules,
    DuplicateDetectionRules,
    MetadataCategoryRules,
    CategorySuitabilityRules,
)
