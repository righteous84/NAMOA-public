"""Jellyfin metadata provider adapter (Sprint 15).

Thin wrapper over the Jellyfin HTTP API. All methods return
raw dicts and lists. Normalisation lives in canonical.py.
"""

from urllib.parse import urlencode

from app.metadata_providers.http import HttpClient


LIBRARY_FIELDS = (
    "Path,ProviderIds,Genres,Tags,Studios,Overview,"
    "ProductionYear,OfficialRating,MediaSources,DateCreated,"
    "SortName,OriginalTitle,PremiereDate,CommunityRating"
)


class JellyfinAdapter:
    """Adapter for the Jellyfin API."""

    provider_name = "jellyfin"

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
        # Jellyfin accepts the API key in X-Emby-Token and in
        # the documented MediaBrowser Authorization scheme.
        # The bare key is never sent as a raw Authorization
        # value (Jellyfin rejects it) and never in a query
        # string.
        return {
            "Authorization": (
                'MediaBrowser Token="' + self.api_key + '"'
            ),
            "X-Emby-Token": self.api_key,
            "Accept": "application/json",
        }

    def _url(self, path, query=None):
        url = self.base_url + path
        if query:
            url = url + "?" + urlencode(query, doseq=True)
        return url

    def test_connection(self):
        """Check connectivity via GET /System/Info."""

        payload = self.http.get(
            self._url("/System/Info"), headers=self._headers()
        )
        if not isinstance(payload, dict):
            return {"ok": True, "version": None}
        version = (
            payload.get("Version")
            or payload.get("version")
        )
        return {"ok": True, "version": version}

    def resolve_user_id(self):
        """Resolve the library user id for sync queries.

        Preferred path is GET /Users/Me (works for
        user-scoped tokens). A bare dashboard API key has
        no user context, and Jellyfin answers /Users/Me
        with HTTP 400 in that case (verified against a
        live server: 400 with both raw-key and MediaBrowser
        Authorization values, while GET /Users with the
        same key returns 200). On any /Users/Me failure
        the adapter therefore falls back to GET /Users,
        which is key-scoped and supported:

        - exactly one user -> that user is used and the
          choice is deterministic
        - zero users -> actionable failure
        - several users -> actionable failure naming the
          count; the operator picks the library user in
          Settings / Integrations, which persists
          jellyfin_user_id and skips resolution entirely
        """

        try:
            payload = self.http.get(
                self._url("/Users/Me"), headers=self._headers()
            )
        except Exception:
            payload = None

        if isinstance(payload, dict):
            user_id = payload.get("Id") or payload.get("id")

            if user_id:
                return str(user_id)

        users = self.list_users()

        if len(users) == 1:
            only = users[0]
            user_id = only.get("Id") or only.get("id")

            if user_id:
                return str(user_id)

            raise ValueError(
                "the single Jellyfin user has no id; "
                "set the library user explicitly in "
                "Settings / Integrations"
            )

        if not users:
            raise ValueError(
                "Jellyfin /Users/Me has no user context "
                "for this API key and /Users lists no "
                "users; set the library user explicitly "
                "in Settings / Integrations"
            )

        raise ValueError(
            "Jellyfin /Users/Me has no user context for "
            f"this API key and the server has {len(users)} "
            "users; set the library user explicitly in "
            "Settings / Integrations"
        )

    def list_users(self):
        """List raw Jellyfin users (id and name).

        GET /Users is key-scoped, so it works with a bare
        dashboard API key where /Users/Me returns 400.
        Used for user resolution fallback and for the
        explicit user picker in Settings / Integrations.
        """

        payload = self.http.get(
            self._url("/Users"), headers=self._headers()
        )

        if isinstance(payload, list):
            return [
                item for item in payload
                if isinstance(item, dict)
            ]

        if isinstance(payload, dict):
            items = payload.get("Items", [])

            if isinstance(items, list):
                return [
                    item for item in items
                    if isinstance(item, dict)
                ]

        raise ValueError("unexpected /Users response")

    def _library_query(
        self, user_id, item_types, *, page_size=500
    ):
        if not user_id:
            raise ValueError("user_id must be a non-empty string")
        try:
            page_size = int(page_size)
        except (TypeError, ValueError):
            page_size = 500
        page_size = max(1, min(page_size, 1000))
        items = []
        start = 0
        pages = 0
        while True:
            pages += 1
            if pages > 200:
                break
            query = {
                "userId": str(user_id),
                "recursive": "true",
                "includeItemTypes": ",".join(item_types),
                "fields": LIBRARY_FIELDS,
                "startIndex": str(start),
                "limit": str(page_size),
            }
            payload = self.http.get(
                self._url("/Items", query=query),
                headers=self._headers(),
            )
            if isinstance(payload, dict):
                page = payload.get("Items", [])
                total = payload.get("TotalRecordCount")
            elif isinstance(payload, list):
                page = payload
                total = None
            else:
                page = []
                total = None
            if not isinstance(page, list):
                break
            items.extend(page)
            if len(page) < page_size:
                break
            start += len(page)
            if (
                isinstance(total, int)
                and not isinstance(total, bool)
                and start >= total
            ):
                break
        return items

    def list_movies(self, user_id):
        """List raw movie items for a user."""

        return self._library_query(user_id, ["Movie"])

    def list_series(self, user_id):
        """List raw series items for a user."""

        return self._library_query(user_id, ["Series"])

    def list_episode_items(self, user_id):
        """List raw episode items library-wide for a user.

        Episodes carry the actual media file paths, so
        TV content can be associated without per-series
        round trips.
        """

        return self._library_query(user_id, ["Episode"])

    def list_seasons(self, series_id):
        """List raw season items for a series."""

        if series_id is None or str(series_id).strip() == "":
            raise ValueError("series_id must be provided")
        payload = self.http.get(
            self._url("/Shows/" + str(series_id) + "/Seasons"),
            headers=self._headers(),
        )
        if isinstance(payload, dict):
            items = payload.get("Seasons", payload.get("Items", []))
            return list(items) if isinstance(items, list) else []
        if isinstance(payload, list):
            return payload
        return []

    def list_episodes(self, series_id, season_id=None):
        """List raw episode items for a series or season."""

        if series_id is None or str(series_id).strip() == "":
            raise ValueError("series_id must be provided")
        if season_id is not None and str(season_id).strip():
            query = {
                "parentId": str(season_id),
                "includeItemTypes": "Episode",
                "recursive": "true",
                "fields": LIBRARY_FIELDS,
            }
            payload = self.http.get(
                self._url("/Items", query=query),
                headers=self._headers(),
            )
            if isinstance(payload, dict):
                items = payload.get("Items", [])
                return (
                    list(items) if isinstance(items, list) else []
                )
            if isinstance(payload, list):
                return payload
            return []
        payload = self.http.get(
            self._url("/Shows/" + str(series_id) + "/Episodes"),
            headers=self._headers(),
        )
        if isinstance(payload, dict):
            items = payload.get("Episodes", payload.get("Items", []))
            return list(items) if isinstance(items, list) else []
        if isinstance(payload, list):
            return payload
        return []

    def search_items(self, term, user_id):
        """Search library items by text via /Items.

        Read-only lookup for identifying unseen local
        files across movies, series, and episodes in
        one call. Returns raw item dicts (same
        normalisation as the list_* methods); the
        association authority decides whether any
        candidate is strong enough, never this
        method. Capped to one page: lookup is
        identification evidence, not a sync.
        """

        if not isinstance(term, str) or not term.strip():
            raise ValueError("term must be a non-empty string")
        if not user_id:
            raise ValueError("user_id must be a non-empty string")
        query = {
            "userId": str(user_id),
            "recursive": "true",
            "searchTerm": term.strip(),
            "includeItemTypes": "Movie,Series,Episode",
            "fields": LIBRARY_FIELDS,
            "limit": "50",
        }
        payload = self.http.get(
            self._url("/Items", query=query),
            headers=self._headers(),
        )
        if isinstance(payload, dict):
            items = payload.get("Items", [])
        elif isinstance(payload, list):
            items = payload
        else:
            items = []
        return [item for item in items if isinstance(item, dict)][
            :50
        ]

    def get_item(self, item_id):
        """Fetch one raw item by id."""

        if item_id is None or str(item_id).strip() == "":
            raise ValueError("item_id must be provided")
        payload = self.http.get(
            self._url("/Items/" + str(item_id)),
            headers=self._headers(),
        )
        if not isinstance(payload, dict):
            raise ValueError("unexpected item response")
        return payload

    def list_collections(self, item_id):
        """List raw collection memberships for an item."""

        if item_id is None or str(item_id).strip() == "":
            raise ValueError("item_id must be provided")
        payload = self.http.get(
            self._url("/Items/" + str(item_id) + "/Collections"),
            headers=self._headers(),
        )
        if isinstance(payload, dict):
            items = payload.get("Items", [])
            return list(items) if isinstance(items, list) else []
        if isinstance(payload, list):
            return payload
        return []
