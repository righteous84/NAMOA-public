"""
Organisation PROFILES (Sprint 15).

Operator-owned organisation configuration: roots, movie/TV/
category templates, category folders, intelligent category
rule selection, explicit tag mappings, naming components,
and collision policy.

Profiles are NOT intelligence and NOT policy values
themselves. They are versioned configuration whose payload
is snapshotted verbatim into every decision run they
influence and covered by the profile digest, following the
established policy/preferences attribution pattern:

- rendering/evaluation semantics are versioned code
  (`PROFILE_TEMPLATE_VERSION`); a semantic change
  requires a version change
- each saved profile payload carries its digest; equal
  payloads always produce equal digests
- tag mappings are evaluated as deterministic policy:
  user priority, then specificity, then mapping id;
  conflicts resolve to needs-review, never to a silent
  arbitrary pick

Templates render pure strings over normalised metadata.
Rendering validates every component through
`app.organisation.paths` and never touches the
filesystem.
"""

import hashlib
import json
import os

from app.organisation.paths import (
    COLLISION_POLICIES,
    COLLISION_REVIEW,
    is_within_roots,
    validate_component,
    validate_rendered_path,
)


#: Semantic version of the profile/template rendering and
#: tag-map evaluation meaning. A change that can alter a
#: rendered destination, a mapping outcome, or precedence
#: MUST bump this version.
PROFILE_TEMPLATE_VERSION = "1.1.0"

#: Built-in template kinds.
TEMPLATE_MOVIE = "movie"

TEMPLATE_TV = "tv"

TEMPLATE_CATEGORY = "category"

TEMPLATE_KINDS = frozenset(
    {TEMPLATE_MOVIE, TEMPLATE_TV, TEMPLATE_CATEGORY}
)

#: Built-in template names shipped as named defaults.
BUILTIN_BASIC_MOVIES = "Basic Movies"

BUILTIN_BASIC_TV = "Basic TV"

BUILTIN_BASIC_CATEGORY = "Basic Category"

#: Maximum rendered path length guarded at validation
#: (filesystem limits vary; stay conservative).
MAX_RENDERED_PATH_LENGTH = 1024

#: Default provider metadata/source priority: Radarr,
#: then Sonarr, then Jellyfin. Priority resolves which
#: value wins when providers disagree about the SAME
#: semantic field; it never suppresses compatible
#: metadata or tags from lower-priority providers,
#: and never overrides association safety.
DEFAULT_PROVIDER_PRIORITY = ("radarr", "sonarr", "jellyfin")


def normalise_provider_priority(value):
    """
    Normalised provider priority list, defaulting to
    Radarr > Sonarr > Jellyfin. Accepts any ordering
    of the three known providers; anything else is
    refused with guidance. Deterministic, persisted
    verbatim on the profile.
    """

    if value is None or value == []:
        return list(DEFAULT_PROVIDER_PRIORITY)

    if isinstance(value, str):
        items = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value]
    else:
        raise ValueError(
            "provider priority must be a list of "
            "provider names"
        )

    items = [item for item in items if item]
    known = {
        name.casefold(): name
        for name in DEFAULT_PROVIDER_PRIORITY
    }
    normalised = []

    for item in items:
        canonical = known.get(item.casefold())

        if canonical is None:
            raise ValueError(
                f"unknown provider in provider priority: "
                f"{item!r} (expected "
                f"{list(DEFAULT_PROVIDER_PRIORITY)})"
            )

        if canonical in normalised:
            raise ValueError(
                f"duplicate provider in provider "
                f"priority: {canonical!r}"
            )

        normalised.append(canonical)

    if sorted(
        name.casefold() for name in normalised
    ) != sorted(
        name.casefold() for name in DEFAULT_PROVIDER_PRIORITY
    ):
        raise ValueError(
            "provider priority must order exactly "
            f"{list(DEFAULT_PROVIDER_PRIORITY)}"
        )

    return normalised


def normalise_certification(value) -> str:
    """
    Normalised certification/rating for classification
    policy matching: surrounding whitespace removed,
    upper-cased (so ``g``, `` G `` and ``G`` agree).
    Non-string or empty input normalises to ``""``
    (no certification evidence). The original provider
    value is retained separately as provenance (merge
    ``_sources``/``_disagreements``); only the
    normalised form drives policy matching.
    """

    if not isinstance(value, str):
        return ""

    return value.strip().upper()


def validate_certification_rules(rules) -> list:
    """
    Validate explicit certification/rating classification
    rules. Each rule needs a non-empty normalised
    certification, a target category, and a media kind
    of movie, tv, or any (omitted means any). Unique
    on (certification, media kind).
    """

    problems = []

    if rules is None:
        return problems

    if not isinstance(rules, list):
        return ["certification rules must be a list"]

    seen = set()

    for index, rule in enumerate(rules):
        where = f"certification rule #{index}"

        if not isinstance(rule, dict):
            problems.append(f"{where} must be an object")
            continue

        rule_id = rule.get("id")

        if (
            not isinstance(rule_id, str)
            or not rule_id.strip()
        ):
            problems.append(
                f"{where} must define a non-empty id"
            )
            rule_id = where

        cert = normalise_certification(
            rule.get("certification")
        )

        if not cert:
            problems.append(
                f"{where} must define a non-empty "
                f"certification/rating"
            )
            continue

        category = rule.get("category")

        if not isinstance(category, str) or not category:
            problems.append(
                f"{where} must define a non-empty target "
                f"category"
            )

        kind = str(rule.get("media_kind") or "any").strip(
        ).casefold()

        if kind in ("movies", "movie"):
            kind = "movie"
        elif kind in ("tv", "series", "show", "shows"):
            kind = "tv"
        elif kind in ("any", "all", "*"):
            kind = "any"
        else:
            problems.append(
                f"{where} media kind must be movie, tv, "
                f"or any"
            )
            continue

        key = (cert, kind)

        if key in seen:
            problems.append(
                f"{where} duplicates an earlier rule for "
                f"the same certification and media kind"
            )
        else:
            seen.add(key)

    return problems


def validate_collection_rules(rules) -> list:
    """
    Validate explicit collection-to-category rules.
    Each rule names a collection and a target
    category. Unique on normalised collection name.
    """

    problems = []

    if rules is None:
        return problems

    if not isinstance(rules, list):
        return ["collection rules must be a list"]

    seen = set()

    for index, rule in enumerate(rules):
        where = f"collection rule #{index}"

        if not isinstance(rule, dict):
            problems.append(f"{where} must be an object")
            continue

        rule_id = rule.get("id")

        if (
            not isinstance(rule_id, str)
            or not rule_id.strip()
        ):
            problems.append(
                f"{where} must define a non-empty id"
            )
            rule_id = where

        collection = rule.get("collection")

        if (
            not isinstance(collection, str)
            or not collection.strip()
        ):
            problems.append(
                f"{where} must define a non-empty "
                f"collection name"
            )
            continue

        category = rule.get("category")

        if not isinstance(category, str) or not category:
            problems.append(
                f"{where} must define a non-empty target "
                f"category"
            )

        key = collection.strip().casefold()

        if key in seen:
            problems.append(
                f"{where} duplicates an earlier rule for "
                f"the same collection"
            )
        else:
            seen.add(key)

    return problems


#: Filename policy modes: keep the existing
#: filename (separator cleanup only), build clean
#: readable names from resolved metadata, extend
#: clean names with file-evidence tokens, or render
#: an advanced custom pattern with the existing
#: template renderer.
FILENAME_KEEP = "keep"

FILENAME_CLEAN = "clean"

FILENAME_EXTENDED = "extended"

FILENAME_TEMPLATE = "template"

FILENAME_MODES = frozenset(
    {
        FILENAME_KEEP,
        FILENAME_CLEAN,
        FILENAME_EXTENDED,
        FILENAME_TEMPLATE,
    }
)


def normalise_filename_policy(value) -> dict:
    """
    Normalised filename policy dict. Missing or empty
    input means keep (today's behaviour, byte-safe
    default); anything else must name a known mode,
    with template mode requiring a pattern.
    Deterministic; raises ValueError with guidance.
    """

    if value is None or value == {}:
        return {"mode": FILENAME_KEEP}

    if not isinstance(value, dict):
        raise ValueError(
            "filename policy must be an object with "
            "a mode"
        )

    mode = str(value.get("mode") or FILENAME_KEEP).strip(
    ).casefold()

    if mode not in FILENAME_MODES:
        raise ValueError(
            f"unknown filename mode '{value.get('mode')}' "
            f"(expected one of {sorted(FILENAME_MODES)})"
        )

    pattern = value.get("pattern")
    separator = value.get("separator")

    if mode == FILENAME_TEMPLATE:
        if (
            not isinstance(pattern, str)
            or not pattern.strip()
        ):
            raise ValueError(
                "custom filename mode needs a "
                "non-empty filename pattern"
            )

        return {"mode": mode, "pattern": pattern.strip()}

    if mode == FILENAME_EXTENDED:
        policy = {"mode": mode}

        if isinstance(pattern, str) and pattern.strip():
            policy["pattern"] = pattern.strip()

        if isinstance(separator, str) and separator:
            if "/" in separator or "\\" in separator:
                raise ValueError(
                    "extended filename separator must "
                    "not contain path separators"
                )

            policy["separator"] = separator

        return policy

    return {"mode": mode}


def validate_filename_policy(value) -> list:
    """Problems with the filename policy (empty ok)."""

    if value is None or value == {}:
        return []

    try:
        normalise_filename_policy(value)
    except ValueError as error:
        return [str(error)]

    return []


def validate_organisation_rules(rules) -> list:
    """
    Validate the unified ordered organisation
    rules. Each rule needs a non-empty stable id,
    a media kind (movie, tv, any), and a non-empty
    target category. Rating, collection, genre,
    and tag conditions are optional; every
    supplied condition is an AND condition, and an
    empty condition means Any. Ids must be unique:
    reorder stability and matched-rule references
    depend on it.
    """

    problems = []

    if rules is None:
        return problems

    if not isinstance(rules, list):
        return ["organisation rules must be a list"]

    seen_ids = set()

    for index, rule in enumerate(rules):
        where = f"organisation rule #{index}"

        if not isinstance(rule, dict):
            problems.append(f"{where} must be an object")
            continue

        rule_id = rule.get("id")

        if (
            not isinstance(rule_id, str)
            or not rule_id.strip()
        ):
            problems.append(
                f"{where} must define a non-empty id"
            )
            continue

        if rule_id in seen_ids:
            problems.append(
                f"{where} duplicates rule id "
                f"'{rule_id}'"
            )
        else:
            seen_ids.add(rule_id)

        kind = str(rule.get("media_kind") or "any").strip(
        ).casefold()

        if kind in ("movies", "movie"):
            pass
        elif kind in ("tv", "series", "show", "shows"):
            pass
        elif kind in ("any", "all", "*"):
            pass
        else:
            problems.append(
                f"{where} media kind must be movie, tv, "
                f"or any"
            )

        category = rule.get("category")

        if not isinstance(category, str) or not category:
            problems.append(
                f"{where} must define a non-empty target "
                f"category"
            )

        for field in ("certification", "collection"):
            value = rule.get(field)

            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                problems.append(
                    f"{where} {field} must be a non-empty "
                    f"rating/collection name when present"
                )

        for field in ("genres", "tags"):
            values = rule.get(field)

            if values is None:
                continue

            if not isinstance(values, list) or not all(
                isinstance(label, str) and label.strip()
                for label in values
            ):
                problems.append(
                    f"{where} {field} must be a list of "
                    f"non-empty labels when present"
                )

        provider = rule.get("provider")

        if provider is not None and (
            not isinstance(provider, str) or not provider
        ):
            problems.append(
                f"{where} provider scope must be a name "
                f"or null (any provider)"
            )

        fallback = rule.get("fallback")

        if fallback is not None and not isinstance(
            fallback, bool
        ):
            problems.append(
                f"{where} fallback must be true or false "
                f"when present"
            )

    return problems


def _rule_kind(rule: dict) -> str:
    """Normalised media kind of one unified rule."""

    kind = str(
        (rule or {}).get("media_kind") or "any"
    ).strip().casefold()

    if kind in ("movies", "movie"):
        return "movie"

    if kind in ("tv", "series", "show", "shows"):
        return "tv"

    return "any"


def describe_rule(rule: dict) -> str:
    """
    Human one-line description of one unified rule
    for What-If ("Movie + G → Movies Kids").
    Empty (Any) conditions are omitted except the
    media kind, which always shows.
    """

    rule = rule or {}
    kinds = {"movie": "Movie", "tv": "TV", "any": "Any kind"}
    parts = [kinds.get(_rule_kind(rule), "Any kind")]

    cert = normalise_certification(rule.get("certification"))

    if cert:
        parts.append(cert)

    collection = rule.get("collection")

    if isinstance(collection, str) and collection.strip():
        parts.append(f"collection '{collection.strip()}'")

    for field in ("genres", "tags"):
        values = rule.get(field) or []

        for label in values:
            if isinstance(label, str) and label.strip():
                parts.append(label.strip())

    provider = rule.get("provider")

    if isinstance(provider, str) and provider.strip():
        parts.append(f"[{provider.strip()}]")

    return (
        f"{' + '.join(parts)} → {rule.get('category') or '?'}"
    )


def match_organisation_rule(
    rules,
    *,
    media_kind,
    certification: str = "",
    collections=(),
    genres=(),
    combined_tags=(),
    tags_by_provider=None,
) -> dict | None:
    """
    First matching unified rule, top to bottom.
    Every supplied condition is an AND: media kind
    (any matches all), normalised certification,
    collection membership (case-insensitive),
    every listed genre present, every listed tag
    label present (in the combined cross-provider
    set, or in the scoped provider's set when the
    rule names one). Returns the rule or None.
    Deterministic; never raises on shapes.
    """

    want_kind = str(media_kind or "any").strip().casefold()

    if want_kind in ("movies",):
        want_kind = "movie"

    if want_kind in ("series", "show", "shows"):
        want_kind = "tv"

    cert = normalise_certification(certification)

    have_collections = {
        str(value).strip().casefold()
        for value in (collections or [])
        if isinstance(value, str) and value.strip()
    }
    have_genres = {
        str(value).strip().casefold()
        for value in (genres or [])
        if isinstance(value, str) and value.strip()
    }
    have_tags = {
        str(tag).strip().casefold()
        for tag in (combined_tags or [])
        if isinstance(tag, str) and str(tag).strip()
    }
    scoped_sets = {}

    for provider, tags in (tags_by_provider or {}).items():
        scoped_sets[str(provider).strip().casefold()] = {
            str(tag).strip().casefold()
            for tag in (tags or [])
            if isinstance(tag, str) and str(tag).strip()
        }

    for rule in rules or []:
        if not isinstance(rule, dict):
            continue

        rule_kind = _rule_kind(rule)

        if rule_kind != "any" and rule_kind != want_kind:
            continue

        rule_cert = normalise_certification(
            rule.get("certification")
        )

        if rule_cert and rule_cert != cert:
            continue

        collection = rule.get("collection")

        if (
            isinstance(collection, str)
            and collection.strip()
            and collection.strip().casefold()
            not in have_collections
        ):
            continue

        labels = [
            str(label).strip().casefold()
            for label in (rule.get("genres") or [])
            if isinstance(label, str) and label.strip()
        ]

        if labels and not all(
            label in have_genres for label in labels
        ):
            continue

        scope = rule.get("provider")
        pool = have_tags

        if isinstance(scope, str) and scope.strip():
            pool = scoped_sets.get(
                scope.strip().casefold(), set()
            )

        wanted = [
            str(label).strip().casefold()
            for label in (rule.get("labels") or [])
            if isinstance(label, str) and label.strip()
        ] or [
            str(label).strip().casefold()
            for label in (rule.get("tags") or [])
            if isinstance(label, str) and label.strip()
        ]

        if wanted and not all(
            label in pool for label in wanted
        ):
            continue

        if not rule.get("category"):
            continue

        return rule

    return None


def builtin_templates() -> dict:
    """
    The named built-in templates. Users clone and edit;
    built-ins themselves are never rewritten.
    """

    return {
        BUILTIN_BASIC_MOVIES: {
            "kind": TEMPLATE_MOVIE,
            "pattern": "{root}/{Title} ({Year})/",
            "description": (
                "Movies grouped in per-title folders "
                "with release year."
            ),
        },
        BUILTIN_BASIC_TV: {
            "kind": TEMPLATE_TV,
            "pattern": "{root}/{Series}/Season {Season}/",
            "description": (
                "Series grouped per show with numbered "
                "season folders."
            ),
        },
        BUILTIN_BASIC_CATEGORY: {
            "kind": TEMPLATE_CATEGORY,
            "pattern": "{root}/{Category}/{TitleOrSeries}/",
            "description": (
                "Category folder containing the title "
                "or series structure."
            ),
        },
    }


def default_profile_payload() -> dict:
    """
    A minimal valid profile payload built on the
    built-in templates. Deterministic.
    """

    return {
        "name": "Default",
        "roots": [],
        "sources": [],
        "movie_template": BUILTIN_BASIC_MOVIES,
        "tv_template": BUILTIN_BASIC_TV,
        "category_template": BUILTIN_BASIC_CATEGORY,
        "templates": builtin_templates(),
        "categories": {},
        "intelligent_rules": {},
        "tag_mappings": [],
        "naming": {
            "separator": " ",
            "case": "preserve",
        },
        "collision_policy": COLLISION_REVIEW,
        "platform": "posix" if os.name != "nt" else "windows",
    }


def builtin_profile_presets() -> list:
    """
    Ready-made starting profiles for the normal GUI
    flow. Each preset is a complete payload except for
    library roots, which only the operator can know.
    Presets default to keeping existing filenames
    (safe: organisation moves files into the correct
    folder structure without renaming valuable
    release filenames); clean and extended naming
    stay one checkbox away in the File Naming
    section. Presets are never mutated and never
    saved directly; selecting one pre-fills the
    profile editor and the operator saves it as a
    new profile version through the single existing
    save path. Deterministic.
    """

    base_templates = builtin_templates()

    def _payload(
        name,
        categories,
        organisation_rules,
        category_template=BUILTIN_BASIC_CATEGORY,
        filename_mode=FILENAME_KEEP,
    ):
        payload = default_profile_payload()
        payload["name"] = name
        payload["roots"] = []
        payload["categories"] = dict(categories)
        payload["tag_mappings"] = []
        payload["category_template"] = category_template
        payload["filename_policy"] = {"mode": filename_mode}
        payload["certification_rules"] = []
        payload["collection_rules"] = []
        payload["organisation_rules"] = list(
            organisation_rules
        )
        payload["templates"] = {
            key: dict(template)
            for key, template in base_templates.items()
        }
        return payload

    def _rule(
        rule_id,
        media_kind,
        category,
        *,
        certification="",
        collection="",
        genres=(),
        tags=(),
        provider=None,
        fallback=False,
    ):
        rule = {
            "id": rule_id,
            "media_kind": media_kind,
            "category": category,
        }

        if certification:
            rule["certification"] = certification

        if collection:
            rule["collection"] = collection

        if genres:
            rule["genres"] = list(genres)

        if tags:
            rule["tags"] = list(tags)

        if provider:
            rule["provider"] = provider

        if fallback:
            rule["fallback"] = True

        return rule

    def _fallback(kind, category):
        media = "Movie" if kind == "movie" else "TV"

        return _rule(
            f"fallback-{kind}",
            kind,
            category,
            fallback=True,
        )

    standard_rules = [
        _fallback("movie", "Movies"),
        _fallback("tv", "Series"),
    ]

    movies_kids_rules = [
        _rule(
            "r-movie-kids-anime", "movie", "Kids Anime",
            tags=["Kids", "Anime"],
        ),
        _rule(
            "r-tv-kids-anime", "tv", "Kids Anime TV",
            tags=["Kids", "Anime"],
        ),
        _rule(
            "r-movie-anime", "movie", "Anime",
            tags=["Anime"],
        ),
        _rule(
            "r-tv-anime", "tv", "Anime TV",
            tags=["Anime"],
        ),
        _rule(
            "r-movie-g", "movie", "Movies Kids",
            certification="G",
        ),
        _rule(
            "r-tv-g", "tv", "Series Kids",
            certification="G",
        ),
        _rule(
            "r-movie-kids", "movie", "Movies Kids",
            tags=["Kids"],
        ),
        _rule(
            "r-tv-kids", "tv", "Series Kids",
            tags=["Kids"],
        ),
        _fallback("movie", "Movies"),
        _fallback("tv", "Series"),
    ]

    anime_rules = [
        _rule(
            "r-movie-anime", "movie", "Anime Movies",
            tags=["Anime"],
        ),
        _rule(
            "r-tv-anime", "tv", "Anime TV",
            tags=["Anime"],
        ),
        _fallback("movie", "Movies"),
        _fallback("tv", "Series"),
    ]

    toons_rules = [
        _rule(
            "r-tv-kids-anime", "tv", "Kids Anime",
            tags=["Kids", "Anime"],
        ),
        _rule(
            "r-movie-kids-anime", "movie", "Kids Anime",
            tags=["Kids", "Anime"],
        ),
        _rule(
            "r-tv-anime", "tv", "Anime",
            tags=["Anime"],
        ),
        _rule(
            "r-movie-anime", "movie", "Anime",
            tags=["Anime"],
        ),
        _rule(
            "r-tv-g", "tv", "Kids TV",
            certification="G",
        ),
        _rule(
            "r-tv-kids", "tv", "Kids TV",
            tags=["Kids"],
        ),
        _rule(
            "r-live-action", "any", "Live Action",
            tags=["Live Action"],
        ),
        _rule(
            "r-tv-animation", "tv", "Cartoons",
            genres=["Animation"],
        ),
        _rule(
            "r-movie-animation", "movie", "Cartoons",
            genres=["Animation"],
        ),
        _fallback("movie", "Movies"),
        _fallback("tv", "TV"),
    ]

    return [
        {
            "key": "movies-tv",
            "name": "Standard Movies + TV",
            "description": (
                "One complete setup for a mixed library: "
                "movies in per-title folders with release "
                "year, series in per-show season folders. "
                "Two fallback rules organise every "
                "recognised Movie and TV item. Add your "
                "library sources and destination roots, "
                "then save."
            ),
            "payload": _payload(
                "Standard Movies + TV",
                {"Movies": "Movies", "Series": "TV"},
                standard_rules,
            ),
        },
        {
            "key": "movies-tv-kids",
            "name": "Movies & TV with Kids Categories",
            "description": (
                "Movies and series plus Kids, Anime "
                "and Kids Anime categories driven by "
                "an ordered rule set (tags, G "
                "certification, media type) with "
                "Movie/TV fallbacks. Add your library "
                "sources and destination roots, then "
                "save."
            ),
            "payload": _payload(
                "Movies & TV with Kids Categories",
                {
                    "Movies": "Movies",
                    "Movies Kids": "Movies-KIDS",
                    "Series": "TV",
                    "Series Kids": "TV-KIDS",
                    "Anime": "Movies-Anime",
                    "Kids Anime": "Movies-KIDS-Anime",
                    "Anime TV": "TV-Anime",
                    "Kids Anime TV": "TV-KIDS-Anime",
                },
                movies_kids_rules,
            ),
        },
        {
            "key": "movies-tv-anime",
            "name": "Movies / TV / Anime",
            "description": (
                "Standard movies and series plus Anime "
                "Movies and Anime TV categories that "
                "keep media kinds apart, with Movie/TV "
                "fallbacks. Add your library sources "
                "and destination roots, then save."
            ),
            "payload": _payload(
                "Movies / TV / Anime",
                {
                    "Movies": "Movies",
                    "Series": "TV",
                    "Anime Movies": "Anime/Movies",
                    "Anime TV": "Anime/TV",
                },
                anime_rules,
            ),
        },
        {
            "key": "tv-kids-cartoons",
            "name": "Kids TV, Anime & Cartoons",
            "description": (
                "TV organisation by evidence: Kids TV, "
                "Anime (stronger than generic "
                "Animation), Cartoons, and Live "
                "Action, with Movie/TV fallbacks so "
                "nothing ordinary is left behind. Add "
                "your library sources and destination "
                "roots, then save."
            ),
            "payload": _payload(
                "Kids TV, Anime & Cartoons",
                {
                    "TV": "TV",
                    "Movies": "Movies",
                    "Kids TV": "TV-KIDS",
                    "Anime": "TV-Anime",
                    "Kids Anime": "TV-KIDS-Anime",
                    "Cartoons": "TV-Cartoons",
                    "Live Action": "Live-Action",
                },
                toons_rules,
            ),
        },
        {
            "key": "blank",
            "name": "Custom / Blank",
            "description": (
                "An empty starting point with the basic "
                "templates. Fill every section yourself, "
                "then save."
            ),
            "payload": _payload(
                "Custom Profile",
                [],
                [],
            ),
        },
    ]


def get_profile_preset(key: str) -> dict | None:
    """One preset payload by key, or None when unknown."""

    for preset in builtin_profile_presets():
        if preset.get("key") == key:
            import copy

            return copy.deepcopy(preset)

    return None


# Sections for the guided profile completion checklist.
# Each entry names the validate_profile problem
# keywords that mark the section incomplete.
COMPLETION_SECTIONS = (
    ("profile", "Profile name"),
    ("locations", "Library locations"),
    ("roottags", "Root tags"),
    ("movie", "Movie template"),
    ("tv", "TV template"),
    ("categories", "Category folders"),
    ("mappings", "Tag mappings"),
)


ROOT_ALIAS_PATTERN = r"root(_[A-Za-z0-9]+|-[A-Za-z0-9]+|[2-9][0-9]*)?"

_ROOT_ALIAS_RE = None


def _root_alias_re():
    global _ROOT_ALIAS_RE

    if _ROOT_ALIAS_RE is None:
        import re

        _ROOT_ALIAS_RE = re.compile(
            "^" + ROOT_ALIAS_PATTERN + "$"
        )

    return _ROOT_ALIAS_RE


def is_valid_root_alias(alias) -> bool:
    """
    True when alias is a template-safe root token name
    (without braces): root, root2..rootN, root_movies,
    root-TV and similar. Python format_map accepts any
    brace-free key, so hyphen and underscore styles
    both render; anything else is refused.
    """

    if not isinstance(alias, str):
        return False

    return _root_alias_re().match(alias.strip()) is not None


def default_root_alias(index: int) -> str:
    """Positional default alias: {root}, {root2}, ..."""

    if index <= 0:
        return "root"

    return f"root{index + 1}"


def normalise_profile_roots(roots) -> list:
    """
    Normalise the roots list to [(path, alias|None)]
    entries. Strings are legacy roots without an alias;
    dicts carry {path, alias}. Order is preserved;
    nothing is renumbered here.
    """

    normalised = []

    for entry in roots or []:
        if isinstance(entry, dict):
            normalised.append(
                (
                    entry.get("path"),
                    entry.get("alias"),
                )
            )
        else:
            normalised.append((entry, None))

    return normalised


def assign_root_aliases(roots) -> tuple[list, list]:
    """
    Assign stable aliases to every root: kept aliases
    stay untouched (no silent renumbering on remove or
    reorder); missing aliases receive the next free
    positional default. Returns ([(path, alias)],
    [problems]). Paths are not validated here.
    """

    pairs = normalise_profile_roots(roots)
    problems = []
    taken = set()
    assigned = []

    for path, alias in pairs:
        text = (
            alias.strip()
            if isinstance(alias, str)
            else ""
        )

        if not text:
            assigned.append((path, None))
            continue

        if not is_valid_root_alias(text):
            problems.append(
                f"root alias '{text}' is invalid; use "
                f"root, root2, or a root_name/root-name "
                f"style token"
            )
            assigned.append((path, None))
            continue

        if text in taken:
            problems.append(
                f"root alias '{text}' is used more than "
                f"once; aliases must be unique"
            )
            assigned.append((path, None))
            continue

        taken.add(text)
        assigned.append((path, text))

    counter = 0
    final = []

    for path, alias in assigned:
        if alias is not None:
            final.append((path, alias))
            continue

        while default_root_alias(counter) in taken:
            counter += 1

        fresh = default_root_alias(counter)
        counter += 1
        taken.add(fresh)
        final.append((path, fresh))

    return final, problems


def root_token_fields(roots) -> dict:
    """
    Template field map {alias: path} for every root
    with a usable path. Pure; invalid entries are
    skipped (validation reports them separately).
    """

    assigned, _ = assign_root_aliases(roots)
    fields = {}

    for path, alias in assigned:
        if (
            isinstance(path, str)
            and path.strip()
            and alias not in fields
        ):
            fields[alias] = path.strip()

    return fields


def resolve_root_token(roots, token: str):
    """(path, alias) for one {token}, or None."""

    for path, alias in assign_root_aliases(roots)[0]:
        if alias == token:
            return path, alias

    return None


def fill_root_aliases(payload: dict) -> dict:
    """
    Return a copy of the payload whose roots are all
    explicit {path, alias} dicts with stable aliases.
    Valid user-edited aliases are preserved verbatim;
    only blank aliases receive the next free default,
    so removing or reordering roots never silently
    renumbers the survivors. Invalid or duplicate alias
    text is preserved untouched so validation refuses
    it with guidance instead of silently repairing it.
    Historical versions are untouched (only new saves
    pass through here).
    """

    payload = dict(payload or {})
    pairs = normalise_profile_roots(payload.get("roots"))

    taken = set()

    for _path, alias in pairs:
        text = (
            alias.strip()
            if isinstance(alias, str)
            else ""
        )

        if text:
            taken.add(text)

    interim = []
    counter = 0

    for path, alias in pairs:
        text = (
            alias.strip()
            if isinstance(alias, str)
            else ""
        )

        if text:
            interim.append((path, text))
            continue

        while default_root_alias(counter) in taken:
            counter += 1

        fresh = default_root_alias(counter)
        counter += 1
        taken.add(fresh)
        interim.append((path, fresh))

    payload["roots"] = [
        {"path": path, "alias": alias}
        for path, alias in interim
    ]

    seen = set()
    sources = []

    for entry in payload.get("sources") or []:
        path = (
            entry.get("path")
            if isinstance(entry, dict)
            else entry
        )

        if not isinstance(path, str):
            continue

        cleaned = path.strip()

        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            sources.append(cleaned)

    payload["sources"] = sources

    return payload


def display_root_rows(roots) -> list:
    """
    Editor rows [{path, alias}] for the Library
    Locations section. Assigned aliases are shown so
    the PATH -> TOKEN relationship is visible; raw
    invalid alias text is preserved so the operator
    can fix it instead of losing input.
    """

    rows = []

    for entry in normalise_profile_roots(roots):
        raw_path, raw_alias = entry
        path = (
            raw_path.strip()
            if isinstance(raw_path, str)
            else ""
        )
        text = (
            raw_alias.strip()
            if isinstance(raw_alias, str)
            else ""
        )

        if text and not is_valid_root_alias(text):
            rows.append({"path": path, "alias": text})
        else:
            rows.append({"path": path, "alias": ""})

    assigned, _ = assign_root_aliases(roots)
    filled = []

    for index, row in enumerate(rows):
        if row["alias"]:
            filled.append(row)
        elif index < len(assigned):
            filled.append(
                {"path": row["path"], "alias": assigned[index][1]}
            )
        else:
            filled.append(row)

    return filled


def root_tokens_in_pattern(pattern: str) -> list:
    """Brace tokens in a pattern that look like root tags."""

    import re

    tokens = []

    for token in re.findall(r"\{([^{}]+)\}", pattern or ""):
        name = token.strip()

        if name.startswith("root") and name not in tokens:
            tokens.append(name)

    return tokens


def profile_completion(payload: dict) -> dict:
    """
    Guided-completion checklist derived from the real
    profile validation plus the genuine requirements
    validation cannot see: at least one library
    source, at least one organisation destination,
    and at least one category folder. Pure; never
    touches the filesystem. Returns section states,
    the incomplete labels, and overall readiness.
    """

    problems = validate_profile(payload or {})

    flagged = {key: [] for key, _ in COMPLETION_SECTIONS}

    for problem in problems:
        text = str(problem).lower()

        if "tag mapping" in text:
            flagged["mappings"].append(problem)
        elif (
            "root alias" in text
            or "root tag" in text
            or "root token" in text
            or "destination tag" in text
        ):
            flagged["roottags"].append(problem)
        elif "movie folder structure" in text:
            flagged["movie"].append(problem)
        elif "tv folder structure" in text:
            flagged["tv"].append(problem)
        elif "category folder structure" in text:
            flagged["categories"].append(problem)
        elif "movie pattern" in text:
            flagged["movie"].append(problem)
        elif "tv pattern" in text:
            flagged["tv"].append(problem)
        elif "category pattern" in text:
            flagged["categories"].append(problem)
        elif "movie_template" in text:
            flagged["movie"].append(problem)
        elif "tv_template" in text:
            flagged["tv"].append(problem)
        elif "template" in text:
            flagged["categories"].append(problem)
        elif "categor" in text:
            flagged["categories"].append(problem)
        elif "library source" in text:
            flagged["locations"].append(problem)
        elif "organisation destination" in text:
            flagged["locations"].append(problem)
        elif "organisation root" in text or "roots" in text:
            flagged["locations"].append(problem)
        elif "movie" in text:
            flagged["movie"].append(problem)
        elif "tv" in text or "series" in text:
            flagged["tv"].append(problem)
        elif "naming" in text or "collision" in text:
            flagged["profile"].append(problem)
        else:
            flagged["profile"].append(problem)

    payload = payload or {}
    roots = payload.get("roots") or []
    categories = payload.get("categories") or {}
    sources = [
        source
        for source in (payload.get("sources") or [])
        if isinstance(source, str) and source.strip()
    ]

    if not sources:
        flagged["locations"].append(
            "Library source required. Choose where "
            "NAMOA is allowed to look for media."
        )

    if not roots:
        flagged["locations"].append(
            "Organisation destination required. "
            "Choose where NAMOA should place organised "
            "media."
        )

    if not categories:
        flagged["categories"].append(
            "at least one category folder is required"
        )

    sections = []

    for key, label in COMPLETION_SECTIONS:
        detail = list(flagged[key])
        sections.append(
            {
                "key": key,
                "label": label,
                "complete": not detail,
                "detail": detail,
            }
        )

    incomplete = [
        section["label"]
        for section in sections
        if not section["complete"]
    ]

    return {
        "sections": sections,
        "incomplete": incomplete,
        "complete": not incomplete,
    }


def profile_digest(payload: dict) -> str:
    """
    Deterministic sha256 digest over the canonical profile
    payload. Equal payloads always produce equal digests;
    any relevant change produces a different one.
    """

    canonical_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )

    return hashlib.sha256(
        canonical_json.encode("utf-8")
    ).hexdigest()


def validate_profile(payload: dict) -> list:
    """
    Validate a profile payload. Returns a list of
    human-readable problems (empty when valid). Pure;
    never touches the filesystem.
    """

    problems = []

    if not isinstance(payload, dict):
        return ["profile payload must be an object"]

    name = payload.get("name")

    if not isinstance(name, str) or not name.strip():
        problems.append("profile name must be non-empty")

    roots = payload.get("roots") or []

    if not isinstance(roots, list):
        problems.append("profile roots must be a list")
        roots = []

    for entry in roots:
        if isinstance(entry, dict):
            path = entry.get("path")
        else:
            path = entry

        if not isinstance(path, str) or not path.strip():
            problems.append(
                f"organisation root must be a non-empty "
                f"path, got {path!r}"
            )
        elif not os.path.isabs(path):
            problems.append(
                f"organisation root must be absolute, "
                f"got {path!r}"
            )

    _assigned, alias_problems = assign_root_aliases(roots)
    problems.extend(alias_problems)

    known_tokens = {
        alias for _, alias in _assigned
    }

    sources = payload.get("sources") or []

    if not isinstance(sources, list):
        problems.append("profile sources must be a list")
    else:
        for source in sources:
            if isinstance(source, dict):
                source_path = source.get("path")
            else:
                source_path = source

            if (
                not isinstance(source_path, str)
                or not source_path.strip()
            ):
                problems.append(
                    f"source location must be a non-empty "
                    f"path, got {source_path!r}"
                )
            elif not os.path.isabs(source_path):
                problems.append(
                    f"source location must be absolute, "
                    f"got {source_path!r}"
                )

    templates = payload.get("templates") or {}

    if not isinstance(templates, dict):
        problems.append("profile templates must be an object")
        templates = {}

    for template_name, template in templates.items():
        problems.extend(
            _validate_template(
                template_name, template, known_tokens
            )
        )

    for key in (
        "movie_template", "tv_template", "category_template"
    ):
        selected = payload.get(key)
        if selected is not None and selected not in templates:
            problems.append(
                f"profile {key} '{selected}' does not name "
                f"a defined template"
            )

    categories = payload.get("categories") or {}

    if not isinstance(categories, dict):
        problems.append("profile categories must be an object")
    else:
        for category, folder in categories.items():
            if not isinstance(folder, str) or not folder:
                problems.append(
                    f"category '{category}' must map to a "
                    f"non-empty folder"
                )

    mappings = payload.get("tag_mappings") or []

    problems.extend(validate_tag_mappings(mappings))

    problems.extend(
        validate_certification_rules(
            payload.get("certification_rules")
        )
    )

    problems.extend(
        validate_collection_rules(
            payload.get("collection_rules")
        )
    )

    problems.extend(
        validate_filename_policy(
            payload.get("filename_policy")
        )
    )

    problems.extend(
        validate_organisation_rules(
            payload.get("organisation_rules")
        )
    )

    if "provider_priority" in payload:
        try:
            normalise_provider_priority(
                payload.get("provider_priority")
            )
        except ValueError as error:
            problems.append(str(error))

    naming = payload.get("naming") or {}

    if not isinstance(naming, dict):
        problems.append("profile naming must be an object")

    collision = payload.get(
        "collision_policy", COLLISION_REVIEW
    )

    if collision not in COLLISION_POLICIES:
        problems.append(
            f"unknown collision policy '{collision}' "
            f"(expected one of {sorted(COLLISION_POLICIES)})"
        )

    platform = payload.get("platform")

    if platform not in (None, "posix", "windows"):
        problems.append(
            f"unknown platform '{platform}' (expected "
            f"'posix' or 'windows')"
        )

    return problems


def _validate_template(
    name, template, known_tokens=None
) -> list:
    problems = []

    if not isinstance(template, dict):
        return [f"template '{name}' must be an object"]

    kind = template.get("kind")

    if kind not in TEMPLATE_KINDS:
        problems.append(
            f"template '{name}' has unknown kind "
            f"'{kind}' (expected one of "
            f"{sorted(TEMPLATE_KINDS)})"
        )

    pattern = template.get("pattern")

    if not isinstance(pattern, str) or not pattern:
        problems.append(
            f"Folder structure needs attention. "
            f"{_template_label(name)} pattern is "
            f"missing: check the Movie and TV "
            f"structure before saving"
        )
    else:
        tokens = root_tokens_in_pattern(pattern)

        if not tokens:
            problems.append(
                f"Folder structure needs attention. "
                f"{_template_label(name)} pattern must "
                f"reference one of your organisation "
                f"destination tags listed under "
                f"Organisation Destinations above"
            )
        elif known_tokens is not None:
            for token in tokens:
                if token not in known_tokens:
                    problems.append(
                        f"Folder structure needs attention. "
                        f"{_template_label(name)} pattern "
                        f"references a destination tag "
                        f"that is not configured; use one "
                        f"of the destination tags listed "
                        f"under Organisation Destinations "
                        f"above"
                    )

    return problems


def _template_label(name) -> str:
    """Human section label for a template reference."""

    kinds = {
        "movie": "Movie",
        "tv": "TV",
        "category": "Category",
        "Basic Movies": "Movie",
        "Basic TV": "TV",
        "Basic Category": "Category",
    }

    return kinds.get(str(name), str(name))


def validate_tag_mappings(mappings) -> list:
    """
    Validate explicit tag mappings. Returns problems
    (empty when valid). Uniqueness is enforced on
    (provider scope, normalised label set).
    """

    problems = []

    if not isinstance(mappings, list):
        return ["tag mappings must be a list"]

    seen = set()

    for index, mapping in enumerate(mappings):
        where = f"tag mapping #{index}"

        if not isinstance(mapping, dict):
            problems.append(f"{where} must be an object")
            continue

        mapping_id = mapping.get("id")

        if not isinstance(mapping_id, str) or not mapping_id:
            problems.append(
                f"{where} must define a non-empty id"
            )
            mapping_id = where

        provider = mapping.get("provider")

        if provider is not None and (
            not isinstance(provider, str) or not provider
        ):
            problems.append(
                f"{where} provider scope must be a name "
                f"or null (any provider)"
            )

        labels = mapping.get("labels")

        if not isinstance(labels, list) or not labels or not all(
            isinstance(label, str) and label.strip()
            for label in labels
        ):
            problems.append(
                f"{where} must define a non-empty list of "
                f"tag labels"
            )
            continue

        category = mapping.get("category")

        if not isinstance(category, str) or not category:
            problems.append(
                f"{where} must define a non-empty target "
                f"category"
            )

        priority = mapping.get("priority", 100)

        if not isinstance(priority, int) or isinstance(
            priority, bool
        ):
            problems.append(
                f"{where} priority must be an integer"
            )

        override = mapping.get("override_policy")

        if override is not None and not isinstance(
            override, bool
        ):
            problems.append(
                f"{where} override_policy must be true or "
                f"false when present"
            )

        key = (
            str(provider or "*").casefold(),
            tuple(
                sorted(
                    label.strip().casefold()
                    for label in labels
                    if isinstance(label, str)
                )
            ),
        )

        if key in seen:
            problems.append(
                f"{where} duplicates an earlier mapping "
                f"for the same provider scope and label "
                f"set"
            )
        else:
            seen.add(key)

    return problems


def tag_mapping_rank(mapping: dict) -> tuple:
    """
    Deterministic precedence key shared by single- and
    multi-provider evaluation: greatest specificity
    (most matching labels) first, then lower user
    priority number, then lowest mapping id. A more
    specific rule always beats a less specific one,
    whatever the priorities say; exact ties stay
    reviewable conflicts, never silent picks.
    """

    return (
        -len(mapping.get("labels") or []),
        int(mapping.get("priority", 100)),
        str(mapping.get("id") or ""),
    )


def evaluate_tag_mappings(
    mappings: list,
    *,
    provider: str,
    tags: list,
) -> dict:
    """
    Deterministic tag-map evaluation (policy, not
    intelligence). Returns a dict describing the outcome:

    - {"outcome": "match", "mapping": ..., "reason": ...}
    - {"outcome": "no_match"}
    - {"outcome": "conflict", "candidates": [...],
      "reason": ...} (exact precedence tie)

    Precedence, in order: greatest specificity
    (most labels), lower user priority number,
    lowest mapping id. Tag comparison is casefolded;
    provider scope must equal the mapping scope or
    the mapping scope must be null (any provider).
    A mapping matches only when ALL of its labels
    are present (conjunction).
    """

    available = {
        str(tag).strip().casefold()
        for tag in (tags or [])
        if isinstance(tag, str) and str(tag).strip()
    }

    provider_key = str(provider or "").strip().casefold()

    hits = []

    for mapping in mappings or []:
        scope = mapping.get("provider")

        if scope is not None and str(scope).strip(
        ).casefold() != provider_key:
            continue

        labels = [
            str(label).strip().casefold()
            for label in (mapping.get("labels") or [])
            if isinstance(label, str) and str(label).strip()
        ]

        if not labels:
            continue

        if not all(label in available for label in labels):
            continue

        hits.append(mapping)

    if not hits:
        return {"outcome": "no_match"}

    def rank(mapping):
        return tag_mapping_rank(mapping)

    ordered = sorted(hits, key=rank)

    winner = ordered[0]

    tied = [
        candidate for candidate in ordered[1:]
        if rank(candidate) == rank(winner)
    ]

    if tied:
        return {
            "outcome": "conflict",
            "candidates": [winner, *tied],
            "reason": (
                "multiple tag mappings match with equal "
                "precedence; manual review required"
            ),
        }

    return {
        "outcome": "match",
        "mapping": winner,
        "reason": (
            f"explicit tag mapping '{winner.get('id')}' "
            f"matched labels "
            f"{sorted(winner.get('labels') or [])} for "
            f"category '{winner.get('category')}'"
        ),
    }


def render_template(
    template: dict,
    *,
    root: str,
    values: dict,
    windows: bool | None = None,
    root_fields: dict | None = None,
) -> tuple[str | None, str | None]:
    """
    Render one template pattern over normalised metadata
    values. Returns (destination, error): exactly one is
    not None. Pure string rendering; never touches the
    filesystem. Unknown placeholders fail closed to
    review (error) rather than guessing.

    Multi-root: root_fields maps every root alias to
    its path ({root: ..., root2: ..., root_movies:
    ...}); the token written in the pattern explicitly
    selects the destination root. root remains the
    legacy single-root field and the fallback when a
    pattern carries no root token.
    """

    pattern = (template or {}).get("pattern", "")

    if not isinstance(pattern, str) or not pattern:
        return None, "template pattern is empty"

    fields = dict(values or {})

    combined = dict(root_fields or {})
    combined.setdefault("root", root)
    fields.update(combined)

    root_paths = [
        str(path)
        for path in combined.values()
        if isinstance(path, str) and path
    ]

    try:
        rendered = pattern.format_map(_StrictFields(fields))
    except KeyError as error:
        return (
            None,
            f"template references unknown field {error}; "
            f"review required",
        )

    if len(rendered) > MAX_RENDERED_PATH_LENGTH:
        return (
            None,
            "rendered destination exceeds the maximum "
            "supported path length; review required",
        )

    reason = validate_rendered_path(
        rendered,
        root_paths or [root],
        windows=windows,
    )

    if reason is not None:
        return None, f"{reason}; review required"

    return rendered, None


class _StrictFields(dict):
    def __missing__(self, key):
        raise KeyError(key)


def profile_snapshot(payload: dict) -> dict:
    """
    The attributable profile snapshot recorded verbatim in
    decision runs: payload plus digest.
    """

    payload = dict(payload or {})

    return {
        "payload": payload,
        "digest": profile_digest(payload),
    }
