"""Metadata provider package (Sprint 15)."""

from app.metadata_providers.association import (
    detect_conflicts,
    find_duplicate_claims,
    rank_associations,
)
from app.metadata_providers.canonical import (
    ADAPTER_VERSIONS,
    CanonicalMovie,
    ProviderEpisode,
    ProviderFile,
    ProviderSeries,
    ProviderTag,
    normalize_jellyfin_item,
    normalize_radarr_movie,
    normalize_radarr_movie_file,
    normalize_radarr_tag_map,
    normalize_sonarr_episode,
    normalize_sonarr_episode_file,
    normalize_sonarr_series,
    normalize_sonarr_tag_map,
)
from app.metadata_providers.http import (
    HttpClient,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
    sanitize_url,
)
from app.metadata_providers.jellyfin import JellyfinAdapter
from app.metadata_providers.radarr import RadarrAdapter
from app.metadata_providers.sonarr import SonarrAdapter

__all__ = [
    "ADAPTER_VERSIONS",
    "CanonicalMovie",
    "HttpClient",
    "JellyfinAdapter",
    "ProviderAuthError",
    "ProviderEpisode",
    "ProviderError",
    "ProviderFile",
    "ProviderSeries",
    "ProviderTag",
    "ProviderUnavailableError",
    "RadarrAdapter",
    "SonarrAdapter",
    "detect_conflicts",
    "find_duplicate_claims",
    "normalize_jellyfin_item",
    "normalize_radarr_movie",
    "normalize_radarr_movie_file",
    "normalize_radarr_tag_map",
    "normalize_sonarr_episode",
    "normalize_sonarr_episode_file",
    "normalize_sonarr_series",
    "normalize_sonarr_tag_map",
    "rank_associations",
    "sanitize_url",
]
