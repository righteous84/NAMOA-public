"""Radarr metadata provider adapter (Sprint 15).

Thin wrapper over the Radarr v3 HTTP API. Auth uses the
X-Api-Key header only, never the apikey query parameter, so
secret values never appear in URLs. All methods return raw
dicts and lists. Normalisation lives in canonical.py.
"""

from urllib.parse import urlencode

from app.metadata_providers.http import HttpClient


class RadarrAdapter:
    """Adapter for the Radarr API."""

    provider_name = "radarr"

    def __init__(self, base_url, api_key, http=None):
        if (
            not isinstance(base_url, str)
            or not base_url.strip()
        ):
            raise ValueError("base_url must be a non-empty string")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key must be a non-empty string")
        self.base_url = base_url.strip().rstrip("/")
        self.api_key = api_key.strip()
        if http is None:
            self.http = HttpClient()
        elif isinstance(http, HttpClient):
            self.http = http
        else:
            raise ValueError("http must be an HttpClient or None")

    def _headers(self):
        return {
            "X-Api-Key": self.api_key,
            "Accept": "application/json",
        }

    def _url(self, path, query=None):
        url = self.base_url + path
        if query:
            url = url + "?" + urlencode(query, doseq=True)
        return url

    def test_connection(self):
        """Check connectivity via /api/v3/system/status."""

        payload = self.http.get(
            self._url("/api/v3/system/status"),
            headers=self._headers(),
        )
        if not isinstance(payload, dict):
            return {"ok": True, "version": None}
        version = payload.get("version") or payload.get("Version")
        return {"ok": True, "version": version}

    def list_movies(self):
        """List raw movies."""

        payload = self.http.get(
            self._url("/api/v3/movie"), headers=self._headers()
        )
        if isinstance(payload, list):
            return payload
        return []

    def lookup_movies(self, term):
        """Search provider records by title via movie/lookup.

        Read-only lookup for identifying unseen local
        files: the term normally comes from local
        filename analysis (candidate title). Returns
        raw movie-shaped dicts (same normalisation as
        list_movies); the association authority
        decides whether any candidate is strong
        enough, never this method.
        """

        if not isinstance(term, str) or not term.strip():
            raise ValueError("term must be a non-empty string")
        payload = self.http.get(
            self._url(
                "/api/v3/movie/lookup",
                query={"term": term.strip()},
            ),
            headers=self._headers(),
        )
        if isinstance(payload, list):
            return payload
        return []

    def get_movie(self, movie_id):
        """Fetch one raw movie by id."""

        if movie_id is None or str(movie_id).strip() == "":
            raise ValueError("movie_id must be provided")
        payload = self.http.get(
            self._url("/api/v3/movie/" + str(movie_id)),
            headers=self._headers(),
        )
        if not isinstance(payload, dict):
            raise ValueError("unexpected movie response")
        return payload

    def list_movie_files(self, movie_id=None):
        """List raw movie files, optionally filtered by movie."""

        query = None
        if movie_id is not None and str(movie_id).strip():
            query = {"movieId": str(movie_id)}
        payload = self.http.get(
            self._url("/api/v3/moviefile", query=query),
            headers=self._headers(),
        )
        if isinstance(payload, list):
            return payload
        return []

    def list_tags(self):
        """Return raw tags as an id to label map."""

        payload = self.http.get(
            self._url("/api/v3/tag"), headers=self._headers()
        )
        if not isinstance(payload, list):
            return {}
        tag_map = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            tag_id = item.get("id")
            label = item.get("label")
            if tag_id is None:
                continue
            try:
                numeric_id = int(tag_id)
            except (TypeError, ValueError):
                continue
            if isinstance(label, str) and label.strip():
                tag_map[numeric_id] = label.strip()
        return tag_map
