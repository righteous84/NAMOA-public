"""Provider association ranking (Sprint 15).

Pure deterministic functions that rank candidate provider
records against one NAMOA file path. No I/O is performed.

Strengths, strongest first:

- exact_path: canonicalised paths match exactly.
- cross_provider_id: external ids (tmdb, tvdb, imdb) agree
  across two or more providers for the same lineage.
- single_id_title: a single provider external id, or an exact
  title and year match (movies) or title, season and episode
  match (episodes) with corroborating filename evidence.
- fuzzy_ambiguous: title similarity only, never authoritative.

Media-kind safety (Sprint 15 correction): provider
records carry a semantic kind (movie vs TV
series/season/episode) and NAMOA lineage paths carry a
layout hint (/Movies.../ vs /TV.../). A candidate whose
kind group is provably incompatible with the lineage
path hint is demoted to fuzzy_ambiguous however strong
its ids look: TMDB 607 identifies both the Men In
Black movie and a Powerpuff Girls series mapping, so
ids alone must never bridge movie and TV lineages.
Exact canonical path matches are exempt (same file).
Unknown kinds on either side stay permissive, because
absence of evidence is not evidence of incompatibility.
"""

import os
import re

STRENGTH_ORDER = (
    "exact_path",
    "cross_provider_id",
    "single_id_title",
    "fuzzy_ambiguous",
)

_STRENGTH_RANK = {
    name: index for index, name in enumerate(STRENGTH_ORDER)
}

_EXTERNAL_ID_KEYS = ("tmdb", "tvdb", "imdb")

# Semantic media-kind groups. Provider file rows inherit
# their group from the owning provider (a Radarr file is
# a movie file; a Sonarr file is an episode file);
# Jellyfin file rows stay unknown (permissive).
_KIND_GROUPS = {
    "movie": "movie",
    "series": "tv",
    "season": "tv",
    "episode": "tv",
}

_FILE_KIND_GROUPS = {
    "radarr": "movie",
    "sonarr": "tv",
}


def provider_kind_group(kind, provider) -> str:
    """
    Semantic group of one provider record kind: movie,
    tv, or unknown. File rows resolve through the owning
    provider; anything unrecognised stays unknown
    (permissive, never a false incompatibility).
    """

    text = str(kind or "").strip().lower()

    if text in _KIND_GROUPS:
        return _KIND_GROUPS[text]

    if text == "file":
        return _FILE_KIND_GROUPS.get(
            str(provider or "").strip().lower(), "unknown"
        )

    return "unknown"


def lineage_kind_hint(namoa_path) -> str:
    """
    Semantic group hint from a NAMOA lineage path: movie
    when a path segment names a Movies library
    (Movies, Movies-KIDS, ...), tv for a TV library
    (TV, TV-KIDS, ...), else unknown. Pure layout
    reading; unknown stays permissive.
    """

    if not isinstance(namoa_path, str):
        return "unknown"

    for segment in namoa_path.replace("\\", "/").split("/"):
        text = segment.strip().lower()

        if not text:
            continue

        if text == "movies" or text.startswith(
            ("movies-", "movies_")
        ):
            return "movie"

        if text == "tv" or text.startswith(
            ("tv-", "tv_")
        ):
            return "tv"

    return "unknown"


def kinds_compatible(kind, provider, namoa_path) -> bool:
    """
    True unless the provider record kind is provably
    incompatible with the lineage path hint (TV record
    against a Movies path or vice versa). Unknown on
    either side is permissive: only demonstrated
    incompatibility rejects.
    """

    provider_group = provider_kind_group(kind, provider)

    if provider_group == "unknown":
        return True

    lineage_group = lineage_kind_hint(namoa_path)

    if lineage_group == "unknown":
        return True

    return provider_group == lineage_group


def _canonical_path(value):
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    normalized = os.path.normpath(text)
    if len(normalized) > 1 and normalized.endswith(os.sep):
        normalized = normalized.rstrip(os.sep)
    return normalized


def _normalise_text(value):
    if not isinstance(value, str):
        return ""
    lowered = value.strip().lower()
    return re.sub(r"\s+", " ", lowered)


def _slug_tokens(value):
    if not isinstance(value, str):
        return []
    return re.findall(r"[a-z0-9]+", value.lower())


def _external_ids(candidate):
    ids = candidate.get("provider_ids")
    if not isinstance(ids, dict):
        return {}
    cleaned = {}
    for key in _EXTERNAL_ID_KEYS:
        for raw_key, raw_value in ids.items():
            if not isinstance(raw_key, str):
                continue
            if raw_key.strip().lower() != key:
                continue
            if raw_value is None or isinstance(raw_value, bool):
                continue
            text = str(raw_value).strip().lower()
            if text and text != "0":
                cleaned[key] = text
    return cleaned


def _work_key(candidate):
    ids = _external_ids(candidate)
    if ids:
        return (
            "ids",
            tuple(sorted(ids.items())),
        )
    title = _normalise_text(candidate.get("title"))
    year = candidate.get("year")
    season = candidate.get("season_number")
    episode = candidate.get("episode_number")
    kind = str(candidate.get("kind") or "").strip().lower()
    if kind == "episode":
        return ("episode", title, season, episode)
    return ("title", title, year)


def _resolve_work_keys(candidates):
    """
    Work key per candidate with same-provider
    parent adoption: a record carrying no external
    ids of its own (provider file rows never do)
    joins the work of its declared parent record
    when a sibling candidate from the same provider
    carries that parent item id and has external
    ids. A file row is part of its parent movie or
    series. It is not a second work claiming the
    same file. Candidates with their own ids never
    move.
    Deterministic: first id-bearing parent in
    candidate order wins.
    """

    raw = [_work_key(candidate) for candidate in candidates]

    parents = {}

    for index, candidate in enumerate(candidates):
        if raw[index][0] != "ids":
            continue

        key = (
            str(candidate.get("provider") or "")
            .strip()
            .lower(),
            str(candidate.get("provider_item_id") or ""),
        )

        if key not in parents:
            parents[key] = raw[index]

    resolved = list(raw)

    for index, candidate in enumerate(candidates):
        if raw[index][0] == "ids":
            continue

        parent_id = candidate.get("parent_provider_id")

        if parent_id is None or (
            isinstance(parent_id, str) and not parent_id.strip()
        ):
            continue

        key = (
            str(candidate.get("provider") or "")
            .strip()
            .lower(),
            str(parent_id),
        )

        if key in parents:
            resolved[index] = parents[key]

    return resolved


def _validate_candidate(candidate):
    if not isinstance(candidate, dict):
        raise ValueError("candidate must be a dict")
    for key in ("provider", "provider_item_id", "kind"):
        value = candidate.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                "candidate requires non-empty string: " + key
            )


def rank_associations(namoa_path, candidates):
    """Rank provider candidates against one NAMOA path.

    Args:
        namoa_path: normalized NAMOA file path string.
        candidates: list of dicts with provider,
            provider_item_id, kind, path (optional),
            provider_ids (optional dict), title, year,
            season_number and episode_number.

    Returns:
        Ranked list of dicts with provider, provider_item_id,
        kind, strength and basis keys, strongest first.
    """

    if not isinstance(namoa_path, str):
        raise ValueError("namoa_path must be a string")
    if not isinstance(candidates, list):
        raise ValueError("candidates must be a list")
    for candidate in candidates:
        _validate_candidate(candidate)

    # An empty path means provider-lookup
    # identification without a local file yet: exact
    # path matches cannot happen, and title-overlap
    # evidence needs a real basename, so only
    # external-id candidates can rise above fuzzy.
    # Never a guess either way.
    target = _canonical_path(namoa_path)
    basename = os.path.basename(target).lower() if target else ""
    basename_tokens = set(_slug_tokens(basename))

    id_groups = {}
    for index, candidate in enumerate(candidates):
        for key, value in _external_ids(candidate).items():
            id_groups.setdefault((key, value), set()).add(index)

    cross_provider = set()
    for (_, _), indexes in id_groups.items():
        providers = {
            str(candidates[i].get("provider")).strip().lower()
            for i in indexes
        }
        if len(providers) >= 2:
            cross_provider.update(indexes)

    ranked = []
    work_keys = _resolve_work_keys(candidates)
    for index, candidate in enumerate(candidates):
        work = _work_display(work_keys[index])
        provider = str(candidate.get("provider")).strip()
        provider_item_id = str(candidate.get("provider_item_id"))
        kind = str(candidate.get("kind")).strip()
        candidate_path = candidate.get("path")
        canonical_candidate = _canonical_path(candidate_path or "")

        if canonical_candidate and canonical_candidate == target:
            ranked.append(
                {
                    "provider": provider,
                    "provider_item_id": provider_item_id,
                    "kind": kind,
                    "work": work,
                    "strength": "exact_path",
                    "basis": (
                        "canonical path matches NAMOA path "
                        + target
                    ),
                }
            )
            continue

        if not kinds_compatible(
            candidate.get("kind"),
            candidate.get("provider"),
            target,
        ):
            ranked.append(
                {
                    "provider": provider,
                    "provider_item_id": provider_item_id,
                    "kind": kind,
                    "work": work,
                    "strength": "fuzzy_ambiguous",
                    "basis": (
                        "media kind incompatible with "
                        "lineage path "
                        + target
                        + "; not authoritative"
                    ),
                }
            )
            continue

        if index in cross_provider:
            ids = _external_ids(candidate)
            detail = ", ".join(
                key + "=" + value
                for key, value in sorted(ids.items())
            )
            ranked.append(
                {
                    "provider": provider,
                    "provider_item_id": provider_item_id,
                    "kind": kind,
                    "work": work,
                    "strength": "cross_provider_id",
                    "basis": (
                        "external id agreement across providers: "
                        + detail
                    ),
                }
            )
            continue

        if _is_single_id_title(candidate, basename_tokens):
            ranked.append(
                {
                    "provider": provider,
                    "provider_item_id": provider_item_id,
                    "kind": kind,
                    "work": work,
                    "strength": "single_id_title",
                    "basis": _single_basis(candidate),
                }
            )
            continue

        ranked.append(
            {
                "provider": provider,
                "provider_item_id": provider_item_id,
                "kind": kind,
                "work": work,
                "strength": "fuzzy_ambiguous",
                "basis": (
                    "title similarity only for "
                    + repr(candidate.get("title"))
                    + "; not authoritative"
                ),
            }
        )

    ranked.sort(
        key=lambda item: (
            _STRENGTH_RANK[item["strength"]],
            item["provider"].lower(),
            item["provider_item_id"],
        )
    )
    return ranked


def _is_single_id_title(candidate, basename_tokens):
    ids = _external_ids(candidate)
    if ids:
        return True
    kind = str(candidate.get("kind") or "").strip().lower()
    title = candidate.get("title")
    if not isinstance(title, str) or not title.strip():
        return False
    title_tokens = set(_slug_tokens(title))
    if not title_tokens:
        return False
    overlap = title_tokens & basename_tokens
    if not overlap:
        return False
    if kind == "episode":
        season = candidate.get("season_number")
        episode = candidate.get("episode_number")
        return season is not None and episode is not None
    year = candidate.get("year")
    return year is not None


def _single_basis(candidate):
    ids = _external_ids(candidate)
    if ids:
        detail = ", ".join(
            key + "=" + value for key, value in sorted(ids.items())
        )
        return "provider external id: " + detail
    kind = str(candidate.get("kind") or "").strip().lower()
    if kind == "episode":
        return (
            "title/season/episode corroborated by filename: "
            + repr(candidate.get("title"))
            + " S"
            + str(candidate.get("season_number"))
            + "E"
            + str(candidate.get("episode_number"))
        )
    return (
        "title/year corroborated by filename: "
        + repr(candidate.get("title"))
        + " (" + str(candidate.get("year")) + ")"
    )


def detect_conflicts(ranked):
    """Describe conflicts within one file's ranked associations.

    A conflict is reported when two or more authoritative claims
    (exact_path, cross_provider_id or single_id_title) point at
    different works for the same file.
    """

    if ranked is None:
        raise ValueError("ranked must be a list")
    if not isinstance(ranked, list):
        raise ValueError("ranked must be a list")
    strong = [
        item
        for item in ranked
        if isinstance(item, dict)
        and item.get("strength")
        in ("exact_path", "cross_provider_id", "single_id_title")
    ]
    if len(strong) < 2:
        return []
    works = {}
    for item in strong:
        works.setdefault(_conflict_work_key(item), []).append(item)
    if len(works) <= 1:
        return []
    descriptions = []
    for work, items in sorted(works.items(), key=lambda kv: kv[0]):
        claims = ", ".join(
            sorted(
                str(entry.get("provider"))
                + ":"
                + str(entry.get("provider_item_id"))
                for entry in items
            )
        )
        descriptions.append(work + " claimed by " + claims)
    return [
        "conflicting provider claims for one file: "
        + " | ".join(descriptions)
    ]


def _work_display(work) -> str:
    """
    Deterministic string identity for one candidate
    work: shared external ids first, otherwise the
    corroborated title key. Providers agreeing on
    the same ids describe the same work, so they
    must never count as conflicting claims.
    """

    try:
        return repr(work)
    except Exception:
        return str(work)


def _conflict_work_key(item):
    work = item.get("work")

    if isinstance(work, str) and work:
        return "work:" + work

    provider = str(item.get("provider") or "").strip().lower()
    provider_item_id = str(item.get("provider_item_id") or "")
    return provider + ":" + provider_item_id


def find_duplicate_claims(all_ranked_by_media):
    """Find one provider item claimed by two or more lineages.

    Args:
        all_ranked_by_media: mapping of media key to the ranked
            association list for that media item.

    Returns:
        List of human readable conflict strings.
    """

    if not isinstance(all_ranked_by_media, dict):
        raise ValueError("all_ranked_by_media must be a dict")
    claimants = {}
    for media_key, ranked in all_ranked_by_media.items():
        if not isinstance(ranked, list):
            raise ValueError("ranked entries must be lists")
        for item in ranked:
            if not isinstance(item, dict):
                continue
            if item.get("strength") == "fuzzy_ambiguous":
                continue
            provider = str(item.get("provider") or "").strip()
            provider_item_id = str(
                item.get("provider_item_id") or ""
            ).strip()
            if not provider or not provider_item_id:
                continue
            claim_key = (
                provider.lower(),
                provider_item_id,
            )
            claimants.setdefault(claim_key, set()).add(str(media_key))
    conflicts = []
    for (provider_lower, provider_item_id), media_keys in sorted(
        claimants.items()
    ):
        unique_media = sorted(media_keys)
        if len(unique_media) >= 2:
            conflicts.append(
                "provider item "
                + provider_lower
                + ":"
                + provider_item_id
                + " claimed by multiple lineages: "
                + ", ".join(unique_media)
            )
    return conflicts
