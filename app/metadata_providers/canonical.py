"""Canonical provider records (Sprint 15).

Pure normalisation layer for metadata providers. Raw provider
dicts are converted into frozen canonical records. Unknown
fields are ignored and missing data becomes None or empty
containers. Nothing is fabricated.
"""

from dataclasses import dataclass, field


ADAPTER_VERSIONS = {
    "jellyfin": "1.0.0",
    "radarr": "1.0.0",
    "sonarr": "1.0.0",
}


@dataclass(frozen=True)
class CanonicalMovie:
    """Canonical movie record from any provider."""

    provider: str = ""
    provider_item_id: str = ""
    kind: str = "movie"
    title: str | None = None
    year: int | None = None
    season_number: int | None = None
    episode_number: int | None = None
    path: str | None = None
    parent_provider_id: str | None = None
    provider_ids: dict = field(default_factory=dict)
    genres: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    certification: str | None = None
    collections: list = field(default_factory=list)
    ratings: dict = field(default_factory=dict)
    monitored: bool = True
    has_file: bool = False


@dataclass(frozen=True)
class ProviderSeries:
    """Canonical series record from any provider."""

    provider: str = ""
    provider_item_id: str = ""
    kind: str = "series"
    title: str | None = None
    year: int | None = None
    season_number: int | None = None
    episode_number: int | None = None
    path: str | None = None
    parent_provider_id: str | None = None
    provider_ids: dict = field(default_factory=dict)
    genres: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    certification: str | None = None
    collections: list = field(default_factory=list)
    ratings: dict = field(default_factory=dict)
    monitored: bool = True
    has_file: bool = False


@dataclass(frozen=True)
class ProviderEpisode:
    """Canonical episode record from any provider."""

    provider: str = ""
    provider_item_id: str = ""
    kind: str = "episode"
    title: str | None = None
    year: int | None = None
    season_number: int | None = None
    episode_number: int | None = None
    path: str | None = None
    parent_provider_id: str | None = None
    provider_ids: dict = field(default_factory=dict)
    genres: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    certification: str | None = None
    collections: list = field(default_factory=list)
    ratings: dict = field(default_factory=dict)
    monitored: bool = True
    has_file: bool = False


@dataclass(frozen=True)
class ProviderFile:
    """Canonical file record from any provider."""

    provider: str = ""
    provider_item_id: str = ""
    kind: str = "file"
    title: str | None = None
    year: int | None = None
    season_number: int | None = None
    episode_number: int | None = None
    path: str | None = None
    parent_provider_id: str | None = None
    provider_ids: dict = field(default_factory=dict)
    genres: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    certification: str | None = None
    collections: list = field(default_factory=list)
    ratings: dict = field(default_factory=dict)
    monitored: bool = True
    has_file: bool = True


@dataclass(frozen=True)
class ProviderTag:
    """Canonical tag record from any provider."""

    provider: str = ""
    provider_item_id: str = ""
    kind: str = "tag"
    title: str | None = None
    year: int | None = None
    season_number: int | None = None
    episode_number: int | None = None
    path: str | None = None
    parent_provider_id: str | None = None
    provider_ids: dict = field(default_factory=dict)
    genres: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    certification: str | None = None
    collections: list = field(default_factory=list)
    ratings: dict = field(default_factory=dict)
    monitored: bool = True
    has_file: bool = False


def _clean_str(value):
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return str(value)


def _clean_int(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            try:
                as_float = float(stripped)
            except ValueError:
                return None
            if as_float.is_integer():
                return int(as_float)
            return None
    return None


def _clean_str_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        cleaned = []
        for item in value:
            if isinstance(item, str) and item.strip():
                cleaned.append(item.strip())
            elif isinstance(item, dict):
                name = item.get("Name") or item.get("name")
                if isinstance(name, str) and name.strip():
                    cleaned.append(name.strip())
        return cleaned
    return []


def _normalise_provider_ids(raw_ids):
    if not isinstance(raw_ids, dict):
        return {}
    normalised = {}
    for key, value in raw_ids.items():
        if not isinstance(key, str):
            continue
        if value is None or isinstance(value, bool):
            continue
        text = str(value).strip()
        if not text:
            continue
        normalised[key.strip().lower()] = text
    return normalised


def _servarr_provider_ids(raw):
    if not isinstance(raw, dict):
        return {}
    mapping = (
        ("tmdbId", "tmdb"),
        ("tmdbid", "tmdb"),
        ("tvdbId", "tvdb"),
        ("tvdbid", "tvdb"),
        ("imdbId", "imdb"),
        ("imdbid", "imdb"),
    )
    ids = {}
    for raw_key, canonical_key in mapping:
        value = raw.get(raw_key)
        if value is None or isinstance(value, bool):
            continue
        text = str(value).strip()
        if text and text != "0":
            ids[canonical_key] = text
    nested = raw.get("ProviderIds")
    if isinstance(nested, dict):
        ids.update(_normalise_provider_ids(nested))
    alternate = raw.get("providerIds")
    if isinstance(alternate, dict):
        ids.update(_normalise_provider_ids(alternate))
    return ids


def _resolve_tag_labels(tag_ids, tag_map):
    if tag_map is None:
        tag_map = {}
    if not isinstance(tag_map, dict):
        raise ValueError("tag_map must be a dict or None")
    if tag_ids is None:
        return []
    if isinstance(tag_ids, str):
        return [tag_ids.strip()] if tag_ids.strip() else []
    if not isinstance(tag_ids, (list, tuple)):
        return []
    labels = []
    for item in tag_ids:
        if isinstance(item, str):
            if item.strip():
                labels.append(item.strip())
            continue
        if isinstance(item, dict):
            label = item.get("label") or item.get("Label")
            if isinstance(label, str) and label.strip():
                labels.append(label.strip())
            continue
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            label = tag_map.get(item) or tag_map.get(str(item))
            if isinstance(label, str) and label.strip():
                labels.append(label.strip())
            continue
        if isinstance(item, float) and item.is_integer():
            label = tag_map.get(int(item))
            if isinstance(label, str) and label.strip():
                labels.append(label.strip())
    return labels


def _flatten_ratings(raw):
    if not isinstance(raw, dict):
        return {}
    flattened = {}
    community = raw.get("CommunityRating")
    if isinstance(community, (int, float)) and not isinstance(
        community, bool
    ):
        flattened["community"] = float(community)
    ratings = raw.get("ratings")
    if isinstance(ratings, dict):
        for key, value in ratings.items():
            if not isinstance(key, str):
                continue
            if isinstance(value, dict):
                inner = value.get("value")
                if isinstance(inner, (int, float)) and not isinstance(
                    inner, bool
                ):
                    flattened[key.strip().lower()] = float(inner)
            elif isinstance(value, (int, float)) and not isinstance(
                value, bool
            ):
                flattened[key.strip().lower()] = float(value)
    return flattened


def normalize_jellyfin_item(raw):
    """Normalise one raw Jellyfin item dict to a canonical record."""

    if not isinstance(raw, dict):
        raise ValueError("raw Jellyfin item must be a dict")
    item_type = raw.get("Type")
    if not isinstance(item_type, str) or not item_type.strip():
        raise ValueError("raw Jellyfin item requires a Type string")
    normalized_type = item_type.strip().lower()
    item_id = raw.get("Id")
    if item_id is None:
        raise ValueError("raw Jellyfin item requires an Id")
    provider_item_id = str(item_id)
    title = _clean_str(
        raw.get("Name")
        or raw.get("OriginalTitle")
        or raw.get("SortName")
    )
    year = _clean_int(raw.get("ProductionYear"))
    path = _clean_str(raw.get("Path"))
    provider_ids = _normalise_provider_ids(raw.get("ProviderIds"))
    genres = _clean_str_list(raw.get("Genres"))
    tags = _clean_str_list(raw.get("Tags"))
    certification = _clean_str(raw.get("OfficialRating"))
    ratings = _flatten_ratings(raw)
    media_sources = raw.get("MediaSources")
    has_file = bool(media_sources) or path is not None
    parent = _clean_str(
        raw.get("SeriesId")
        or raw.get("SeasonId")
        or raw.get("ParentId")
    )
    parent_id = str(parent) if parent else None

    if normalized_type == "movie":
        return CanonicalMovie(
            provider="jellyfin",
            provider_item_id=provider_item_id,
            kind="movie",
            title=title,
            year=year,
            path=path,
            parent_provider_id=None,
            provider_ids=provider_ids,
            genres=genres,
            tags=tags,
            certification=certification,
            collections=[],
            ratings=ratings,
            monitored=True,
            has_file=has_file,
        )
    if normalized_type == "series":
        return ProviderSeries(
            provider="jellyfin",
            provider_item_id=provider_item_id,
            kind="series",
            title=title,
            year=year,
            path=path,
            parent_provider_id=None,
            provider_ids=provider_ids,
            genres=genres,
            tags=tags,
            certification=certification,
            collections=[],
            ratings=ratings,
            monitored=True,
            has_file=False,
        )
    if normalized_type == "season":
        return ProviderSeries(
            provider="jellyfin",
            provider_item_id=provider_item_id,
            kind="series",
            title=title,
            year=year,
            season_number=_clean_int(raw.get("IndexNumber")),
            path=path,
            parent_provider_id=parent_id,
            provider_ids=provider_ids,
            genres=genres,
            tags=tags,
            certification=certification,
            collections=[],
            ratings=ratings,
            monitored=True,
            has_file=False,
        )
    if normalized_type == "episode":
        return ProviderEpisode(
            provider="jellyfin",
            provider_item_id=provider_item_id,
            kind="episode",
            title=title,
            year=year,
            season_number=_clean_int(raw.get("ParentIndexNumber")),
            episode_number=_clean_int(raw.get("IndexNumber")),
            path=path,
            parent_provider_id=parent_id,
            provider_ids=provider_ids,
            genres=genres,
            tags=tags,
            certification=certification,
            collections=[],
            ratings=ratings,
            monitored=True,
            has_file=has_file,
        )
    raise ValueError(
        "unsupported Jellyfin item Type: " + item_type.strip()
    )


def normalize_radarr_tag_map(raw):
    """Normalise a raw Radarr tag list to an id to label map."""

    if raw is None:
        return {}
    if not isinstance(raw, (list, tuple)):
        raise ValueError("raw Radarr tags must be a list or None")
    tag_map = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        tag_id = _clean_int(item.get("id"))
        label = _clean_str(item.get("label"))
        if tag_id is not None and label is not None:
            tag_map[tag_id] = label
    return tag_map


def normalize_radarr_movie(raw, tag_map=None):
    """Normalise one raw Radarr movie dict to a CanonicalMovie."""

    if not isinstance(raw, dict):
        raise ValueError("raw Radarr movie must be a dict")
    if tag_map is None:
        tag_map = {}
    if not isinstance(tag_map, dict):
        raise ValueError("tag_map must be a dict or None")
    movie_id = raw.get("id")
    if movie_id is None:
        raise ValueError("raw Radarr movie requires an id")
    title = _clean_str(raw.get("title"))
    year = _clean_int(raw.get("year"))
    path = _clean_str(raw.get("path") or raw.get("folderPath"))
    provider_ids = _servarr_provider_ids(raw)
    genres = _clean_str_list(raw.get("genres"))
    tags = _resolve_tag_labels(raw.get("tags"), tag_map)
    certification = _clean_str(raw.get("certification"))
    collections = []
    collection = raw.get("collection")
    if isinstance(collection, dict):
        collection_title = _clean_str(collection.get("title"))
        if collection_title:
            collections.append(collection_title)
    extra_collections = raw.get("collections")
    if isinstance(extra_collections, (list, tuple)):
        for item in extra_collections:
            if isinstance(item, str) and item.strip():
                collections.append(item.strip())
            elif isinstance(item, dict):
                item_title = _clean_str(item.get("title"))
                if item_title:
                    collections.append(item_title)
    ratings = _flatten_ratings(raw)
    monitored = raw.get("monitored", True)
    monitored_value = bool(monitored) if monitored is not None else True
    has_file = bool(raw.get("hasFile", False))
    movie_file = raw.get("movieFile")
    if isinstance(movie_file, dict) and movie_file.get("path"):
        has_file = True
    return CanonicalMovie(
        provider="radarr",
        provider_item_id=str(movie_id),
        kind="movie",
        title=title,
        year=year,
        path=path,
        parent_provider_id=None,
        provider_ids=provider_ids,
        genres=genres,
        tags=tags,
        certification=certification,
        collections=collections,
        ratings=ratings,
        monitored=monitored_value,
        has_file=has_file,
    )


def normalize_sonarr_tag_map(raw):
    """Normalise a raw Sonarr tag list to an id to label map."""

    return normalize_radarr_tag_map(raw)


def normalize_sonarr_series(raw, tag_map=None):
    """Normalise one raw Sonarr series dict to a ProviderSeries."""

    if not isinstance(raw, dict):
        raise ValueError("raw Sonarr series must be a dict")
    if tag_map is None:
        tag_map = {}
    if not isinstance(tag_map, dict):
        raise ValueError("tag_map must be a dict or None")
    series_id = raw.get("id")
    if series_id is None:
        raise ValueError("raw Sonarr series requires an id")
    title = _clean_str(raw.get("title"))
    year = _clean_int(raw.get("year"))
    path = _clean_str(raw.get("path") or raw.get("folderPath"))
    provider_ids = _servarr_provider_ids(raw)
    genres = _clean_str_list(raw.get("genres"))
    tags = _resolve_tag_labels(raw.get("tags"), tag_map)
    certification = _clean_str(raw.get("certification"))
    collections = []
    ratings = _flatten_ratings(raw)
    monitored = raw.get("monitored", True)
    monitored_value = bool(monitored) if monitored is not None else True
    return ProviderSeries(
        provider="sonarr",
        provider_item_id=str(series_id),
        kind="series",
        title=title,
        year=year,
        path=path,
        parent_provider_id=None,
        provider_ids=provider_ids,
        genres=genres,
        tags=tags,
        certification=certification,
        collections=collections,
        ratings=ratings,
        monitored=monitored_value,
        has_file=False,
    )


def normalize_sonarr_episode(raw):
    """Normalise one raw Sonarr episode dict to a ProviderEpisode."""

    if not isinstance(raw, dict):
        raise ValueError("raw Sonarr episode must be a dict")
    episode_id = raw.get("id")
    if episode_id is None:
        raise ValueError("raw Sonarr episode requires an id")
    series_id = raw.get("seriesId")
    parent_id = str(series_id) if series_id is not None else None
    title = _clean_str(raw.get("title"))
    season_number = _clean_int(raw.get("seasonNumber"))
    episode_number = _clean_int(raw.get("episodeNumber"))
    has_file = bool(raw.get("hasFile", False))
    monitored = raw.get("monitored", True)
    monitored_value = bool(monitored) if monitored is not None else True
    return ProviderEpisode(
        provider="sonarr",
        provider_item_id=str(episode_id),
        kind="episode",
        title=title,
        year=None,
        season_number=season_number,
        episode_number=episode_number,
        path=None,
        parent_provider_id=parent_id,
        provider_ids={},
        genres=[],
        tags=[],
        certification=None,
        collections=[],
        ratings={},
        monitored=monitored_value,
        has_file=has_file,
    )


def normalize_sonarr_episode_file(raw):
    """Normalise one raw Sonarr episode file dict to a ProviderFile."""

    if not isinstance(raw, dict):
        raise ValueError("raw Sonarr episode file must be a dict")
    file_id = raw.get("id")
    if file_id is None:
        raise ValueError("raw Sonarr episode file requires an id")
    series_id = raw.get("seriesId")
    parent_id = str(series_id) if series_id is not None else None
    path = _clean_str(raw.get("path"))
    season_number = _clean_int(raw.get("seasonNumber"))
    episode_number = None
    episodes = raw.get("episodes")
    if isinstance(episodes, (list, tuple)) and episodes:
        first = episodes[0] if isinstance(episodes[0], dict) else None
        if first is not None:
            episode_number = _clean_int(first.get("episodeNumber"))
            if season_number is None:
                season_number = _clean_int(first.get("seasonNumber"))
    return ProviderFile(
        provider="sonarr",
        provider_item_id=str(file_id),
        kind="file",
        title=None,
        year=None,
        season_number=season_number,
        episode_number=episode_number,
        path=path,
        parent_provider_id=parent_id,
        provider_ids={},
        genres=[],
        tags=[],
        certification=None,
        collections=[],
        ratings={},
        monitored=True,
        has_file=True,
    )


def normalize_radarr_movie_file(raw):
    """Normalise one raw Radarr movie file dict to a ProviderFile."""

    if not isinstance(raw, dict):
        raise ValueError("raw Radarr movie file must be a dict")
    file_id = raw.get("id")
    if file_id is None:
        raise ValueError("raw Radarr movie file requires an id")
    movie_id = raw.get("movieId")
    parent_id = str(movie_id) if movie_id is not None else None
    path = _clean_str(raw.get("path"))
    return ProviderFile(
        provider="radarr",
        provider_item_id=str(file_id),
        kind="file",
        title=None,
        year=None,
        season_number=None,
        episode_number=None,
        path=path,
        parent_provider_id=parent_id,
        provider_ids={},
        genres=[],
        tags=[],
        certification=None,
        collections=[],
        ratings={},
        monitored=True,
        has_file=True,
    )
