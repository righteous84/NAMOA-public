"""
Provider integration application service (Sprint 15).

Owns non-secret integration configuration, credential
handling through the platform SecretStore abstraction,
live connection tests, provider metadata synchronisation,
and explicit per-media association fetches.

Security rules enforced here:

- credential values live exclusively in the secret store
  (keyring-preferred backend) or the documented
  environment override; they are never written to the
  database, logs, reports, provenance, observations,
  snapshots, or Git
- connection tests and fetches use credentials in memory
  only; UIs and APIs report presence, never values
- header auth only (`X-Api-Key` for Servarr,
  `Authorization`/`X-Emby-Token` for Jellyfin via the
  adapter); secret-bearing URLs are never constructed
  and error messages never carry query strings
- a missing or failing integration degrades to status
  and review-state; it never breaks scanning or
  unrelated features

All network access uses the shared stdlib HTTP helper
(no third-party HTTP dependency). Timeouts are bounded.
"""

import re

from app.metadata_providers.association import (
    kinds_compatible,
    lineage_kind_hint,
    rank_associations,
)
from app.metadata_providers.canonical import (
    normalize_jellyfin_item,
    normalize_radarr_movie,
    normalize_radarr_movie_file,
    normalize_sonarr_episode,
    normalize_sonarr_episode_file,
    normalize_sonarr_series,
)
from app.metadata_providers.jellyfin import JellyfinAdapter
from app.metadata_providers.radarr import RadarrAdapter
from app.metadata_providers.sonarr import SonarrAdapter


PROVIDERS = ("jellyfin", "radarr", "sonarr")

ADAPTER_CLASSES = {
    "jellyfin": JellyfinAdapter,
    "radarr": RadarrAdapter,
    "sonarr": SonarrAdapter,
}

ENV_VAR_NAMES = {
    "jellyfin": "NAMOA_JELLYFIN_API_KEY",
    "radarr": "NAMOA_RADARR_API_KEY",
    "sonarr": "NAMOA_SONARR_API_KEY",
}


class IntegrationError(ValueError):
    """Raised for integration configuration or use errors."""


def normalise_base_url(raw) -> str:
    """Normalise a provider base URL deterministically.

    Rule: strip surrounding whitespace and trailing
    slashes; when no scheme is present prepend
    "http://"; parse with urllib.parse and require a
    scheme in (http, https) with a non-empty hostname,
    else raise IntegrationError naming the problem;
    reject embedded credentials (user:pass@) with a
    clear message; reject doubled schemes without ever
    producing "http://http://".
    """

    from urllib.parse import urlsplit

    if not isinstance(raw, str):
        raise IntegrationError(
            "base URL must be a string"
        )

    text = raw.strip()

    if not text:
        raise IntegrationError(
            "base URL must be a non-empty HTTP(S) URL"
        )

    if text.count("://") > 1:
        raise IntegrationError(
            "base URL has a doubled scheme; "
            "use one scheme only"
        )

    if "://" not in text:
        if re.match(r"(?i)^https?:", text):
            raise IntegrationError(
                "base URL has a malformed scheme; "
                "use http:// or https:// with a host"
            )
        text = "http://" + text
    else:
        remainder = text.split("://", 1)[1]
        if "://" in remainder:
            raise IntegrationError(
                "base URL has a doubled scheme; "
                "use one scheme only"
            )
        if not remainder.strip().strip("/"):
            raise IntegrationError(
                "base URL is missing a host; use an "
                "HTTP(S) URL with a host"
            )

    try:
        parts = urlsplit(text)
    except Exception:
        raise IntegrationError(
            "base URL could not be parsed; use an "
            "HTTP(S) URL with a host"
        )

    scheme = (parts.scheme or "").lower()

    if scheme not in ("http", "https"):
        raise IntegrationError(
            f"unsupported URL scheme '{parts.scheme}'; "
            "use http:// or https://"
        )

    try:
        hostname = parts.hostname
        username = parts.username
        password = parts.password
    except Exception:
        raise IntegrationError(
            "base URL could not be parsed; use an "
            "HTTP(S) URL with a host"
        )

    if not hostname:
        raise IntegrationError(
            "base URL is missing a host; use an "
            "HTTP(S) URL with a host"
        )

    if username or password:
        raise IntegrationError(
            "base URL must not embed credentials "
            "(user:pass@host is refused); put the API "
            "key in the credential field"
        )

    return text.strip().rstrip("/").strip()


class IntegrationService:
    """
    Application boundary for Jellyfin/Radarr/Sonarr
    integrations.
    """

    def __init__(
        self,
        *,
        organisation_repository,
        media_repository,
        secret_store=None,
        notification_service=None,
    ):
        self.organisation_records = organisation_repository
        self.media_repository = media_repository
        self.secret_store = secret_store
        self.notification_service = notification_service

    # ---------------------------------------------------------
    # configuration (non-secret)
    # ---------------------------------------------------------

    def configure_provider(
        self,
        provider: str,
        *,
        enabled: bool = True,
        base_url: str = "",
        api_key: str | None = None,
    ) -> dict:
        """
        Store non-secret configuration and, when supplied,
        the credential (into the secret store only).
        Returns the public settings view (presence, never
        the value). Commits.
        """

        self._require_provider(provider)

        secret_ref = ""

        base_url_text = str(base_url or "").strip()

        if base_url_text:
            base_url_text = normalise_base_url(base_url_text)
        else:
            base_url_text = ""

        if api_key is not None:
            if not str(api_key).strip():
                raise IntegrationError(
                    "API key must be non-empty when supplied"
                )
            try:
                self._store().store(
                    f"namoa/{provider}", "api_key", str(api_key)
                )
            except Exception as error:
                raise IntegrationError(str(error)) from error
            secret_ref = ENV_VAR_NAMES[provider]

        self.organisation_records.save_integration(
            provider=provider,
            enabled=bool(enabled),
            base_url=base_url_text,
            jellyfin_user_id=self._existing_user_id(provider),
            secret_ref=secret_ref,
        )

        self.organisation_records.connection.commit()

        record = self.organisation_records.get_integration(
            provider
        )

        return self._public_view(record)

    def remove_credential(self, provider: str) -> dict:
        """
        Delete the stored credential. Configuration row is
        kept (disabling is a separate explicit action).
        Returns the public settings view with a removal
        flag. The environment override, when set by the
        operator outside NAMOA, is left untouched and
        reported as still present.
        """

        self._require_provider(provider)

        store = self._store()

        removed = False

        if hasattr(store, "delete"):
            try:
                store.delete(
                    f"namoa/{provider}", "api_key"
                )
                removed = True
            except Exception:
                removed = False

        record = self.organisation_records.get_integration(
            provider
        )

        view = (
            self._public_view(record)
            if record is not None
            else self._public_view(None, provider=provider)
        )

        view["credential_removed"] = removed

        return view

    def credential_status(self, provider: str) -> dict:
        """
        Presence and source of the credential without ever
        exposing the value.
        """

        self._require_provider(provider)

        value, source = self._resolve_secret(provider)

        return {
            "provider": provider,
            "present": value is not None,
            "source": source or None,
        }

    def list_providers(self) -> list:
        """
        Public settings views for all three providers
        (configured or not). No network access.
        """

        configured = {
            record.provider: record
            for record in (
                self.organisation_records.list_integrations()
            )
        }

        return [
            self._public_view(
                configured.get(provider), provider=provider
            )
            for provider in PROVIDERS
        ]

    def get_provider(self, provider: str) -> dict:
        self._require_provider(provider)

        record = self.organisation_records.get_integration(
            provider
        )

        return self._public_view(
            record, provider=provider
        )

    # ---------------------------------------------------------
    # live connection (in-memory credentials only)
    # ---------------------------------------------------------

    def test_connection(self, provider: str) -> dict:
        """
        Live connection test using the resolved credential
        in memory only. On success for Jellyfin, persists
        the resolved user id (non-secret configuration).
        Never persists, logs, or echoes the credential.
        """

        self._require_provider(provider)

        secret, source = self._resolve_secret(provider)

        if not secret:
            return {
                "provider": provider,
                "ok": False,
                "version": None,
                "error": (
                    "no credential configured; enter an "
                    "API key or set "
                    f"{ENV_VAR_NAMES[provider]}"
                ),
                "credential_source": None,
            }

        record = self.organisation_records.get_integration(
            provider
        )

        base_url = (record.base_url if record else "") or ""

        if not base_url:
            return {
                "provider": provider,
                "ok": False,
                "version": None,
                "error": (
                    "no base URL configured for provider "
                    f"'{provider}'"
                ),
                "credential_source": source,
            }

        try:
            adapter = ADAPTER_CLASSES[provider](
                base_url, secret
            )
            result = adapter.test_connection()
        except Exception as error:
            return {
                "provider": provider,
                "ok": False,
                "version": None,
                "error": (
                    f"{type(error).__name__}: {error}"
                ),
                "credential_source": source,
            }

        if not isinstance(result, dict):
            result = {"ok": bool(result)}

        result.setdefault("provider", provider)

        if provider == "jellyfin" and result.get("ok"):
            try:
                user_id = adapter.resolve_user_id()
            except Exception:
                user_id = None

            if user_id:
                self.organisation_records.save_integration(
                    provider=provider,
                    enabled=(
                        bool(record.enabled)
                        if record
                        else False
                    ),
                    base_url=base_url,
                    jellyfin_user_id=str(user_id),
                    secret_ref=(
                        record.secret_ref if record else ""
                    ),
                )
                self.organisation_records.connection.commit()

                result["jellyfin_user_id"] = str(user_id)

        result["credential_source"] = source

        return result

    # ---------------------------------------------------------
    # metadata synchronisation (explicit operator action)
    # ---------------------------------------------------------

    def sync_provider(
        self, provider: str, *, progress=None
    ) -> dict:
        """
        Fetch the provider library and persist metadata
        observations for NAMOA lineages matched by exact
        canonical path. Explicit operator action only;
        never part of normal scanning. Returns an honest
        summary with full counters (total, inspected,
        matched, updated, unchanged, unmatched, errors).
        Each run is recorded in the sync run ledger so
        the latest known status survives refreshes. An
        optional progress callback receives honest
        snapshots (fetching phase, then per-item syncing
        counts); with no callback the behaviour is
        identical to a plain call. Raises
        IntegrationError when unconfigured or unreachable
        (callers surface status, never mutate the
        filesystem).
        """

        self._require_provider(provider)

        adapter = self._live_adapter(provider)[0]

        def _emit(snapshot):
            if progress is not None:
                progress(dict(snapshot))

        run_id = (
            self.organisation_records
            .record_metadata_sync_start(provider)
        )
        self.organisation_records.connection.commit()

        _emit(
            {
                "provider": provider,
                "run_id": run_id,
                "phase": "fetching",
                "total_items": 0,
                "inspected": 0,
                "matched": 0,
                "updated": 0,
                "unchanged": 0,
                "unmatched": 0,
                "error_count": 0,
            }
        )

        try:
            items = self._fetch_library(adapter, provider)
        except Exception as error:
            # Total fetch failure degrades to an honest
            # failed summary; it never mutates anything
            # and never masks the cause.
            failure = f"{type(error).__name__}: {error}"

            self.organisation_records.finish_metadata_sync_run(
                run_id,
                state="failed",
                error_count=1,
                error_text=failure,
            )
            self.organisation_records.connection.commit()

            summary = {
                "provider": provider,
                "run_id": run_id,
                "state": "failed",
                "items_seen": 0,
                "total_items": 0,
                "inspected": 0,
                "matched": 0,
                "observed": 0,
                "updated": 0,
                "unchanged": 0,
                "unmatched": 0,
                "skipped_no_path_match": 0,
                "errors": [failure],
            }

            _emit({**summary, "phase": "done"})

            return summary

        tag_map = self._tag_map(adapter, provider)

        lineages_by_path = self._lineage_path_index()

        self._lineage_reverse = {
            media_id: key
            for key, media_id in lineages_by_path.items()
        }

        # Association context for this run: explicit root
        # mappings for this provider plus the
        # cross-provider external-id evidence observed so
        # far. Both are read-only snapshots; neither is
        # consulted outside _match_lineage.
        self._mapping_cache = {
            provider: self.list_path_mappings(provider)
        }
        self._known_id_cache = (
            self._known_external_id_index()
        )

        total = len(items)
        inspected = 0
        matched = 0
        updated = 0
        unchanged = 0
        unmatched = 0
        needs_review = 0
        review_examples = []
        errors = []
        current_item = ""

        _MATCH_BASIS = {
            "exact": (
                "library sync; exact canonical path match"
            ),
            "mapped": (
                "library sync; explicit provider-root to "
                "local-root mapped path match"
            ),
            "directory": (
                "library sync; explicit mapped directory "
                "holds exactly one lineage file"
            ),
            "cross_id": (
                "library sync; strong external id "
                "(tmdb/tvdb/imdb) already observed for "
                "one lineage"
            ),
        }

        def _snapshot(phase):
            return {
                "provider": provider,
                "run_id": run_id,
                "phase": phase,
                "total_items": total,
                "inspected": inspected,
                "matched": matched,
                "updated": updated,
                "unchanged": unchanged,
                "unmatched": unmatched,
                "needs_review": needs_review,
                "error_count": len(errors),
                "current_item": current_item,
            }

        for kind, raw in items:
            try:
                relevant = self._relevant_subset(
                    provider, kind, raw, tag_map
                )
            except Exception as error:
                inspected += 1
                unmatched += 1
                errors.append(
                    f"unreadable provider record: "
                    f"{type(error).__name__}"
                )
                _emit(_snapshot("syncing"))
                continue

            path = (relevant.get("path") or "").strip()
            current_item = path or (
                relevant.get("title") or ""
            )
            inspected += 1

            relevant["_provider"] = provider

            outcome, media_id = self._match_lineage(
                relevant, lineages_by_path
            )

            if outcome == "none":
                unmatched += 1
            elif outcome in ("ambiguous", "review"):
                needs_review += 1

                if len(review_examples) < 5:
                    review_examples.append(
                        path or current_item
                    )
            else:
                matched += 1

                basis = _MATCH_BASIS.get(
                    outcome,
                    "library sync; exact canonical "
                    "path match",
                )

                try:
                    if self._observation_unchanged(
                        provider, media_id, relevant
                    ):
                        unchanged += 1
                    else:
                        self._persist_relevant(
                            provider,
                            media_id,
                            relevant,
                            basis=basis,
                            match_outcome=outcome,
                        )
                        updated += 1
                except Exception as error:
                    errors.append(
                        f"{path}: {type(error).__name__}"
                    )

            _emit(_snapshot("syncing"))

        self.organisation_records.connection.commit()

        summary = {
            "provider": provider,
            "run_id": run_id,
            "state": "succeeded",
            "items_seen": total,
            "total_items": total,
            "inspected": inspected,
            "matched": matched,
            "observed": matched,
            "updated": updated,
            "unchanged": unchanged,
            "unmatched": unmatched,
            "needs_review": needs_review,
            "review_examples": list(review_examples),
            "skipped_no_path_match": unmatched,
            "errors": errors,
        }

        self.organisation_records.finish_metadata_sync_run(
            run_id,
            state="succeeded",
            total_items=total,
            inspected=inspected,
            matched=matched,
            updated=updated,
            unchanged=unchanged,
            unmatched=unmatched,
            needs_review=needs_review,
            error_count=len(errors),
            error_text=(
                "; ".join(errors[:3]) if errors else ""
            ),
        )
        self.organisation_records.connection.commit()

        _emit({**summary, "phase": "done"})

        return summary

    def _observation_unchanged(
        self, provider: str, media_id: int, relevant: dict
    ) -> bool:
        """
        True when the newest stored observation for this
        provider item already carries the incoming
        fingerprint, so persisting would change nothing.
        Read-only; introduces no new persistence.
        """

        latest = (
            self.organisation_records
            .latest_metadata_observation(
                media_id,
                provider,
                str(relevant.get("provider_item_id") or ""),
            )
        )

        if latest is None:
            return False

        return latest.source_fingerprint == (
            self.organisation_records
            .metadata_fingerprint(relevant)
        )

    def last_sync_summaries(self) -> dict:
        """
        Latest ledger sync state per provider for status
        surfaces. Read-only; values are counts only,
        never credentials.
        """

        return {
            provider: (
                self.organisation_records
                .latest_sync_run(provider)
            )
            for provider in PROVIDERS
        }

    def fetch_for_media(
        self,
        provider: str,
        media_id: int,
        provider_item_id: str,
        *,
        item_kind: str = "file",
    ) -> dict:
        """
        Fetch one provider item and persist a metadata
        observation for one lineage (explicit association
        support, including setups where provider paths
        are not visible to the NAMOA host). Commits.
        Returns the persisted observation view.
        """

        self._require_provider(provider)

        lineage = self.media_repository.get_media_item(
            media_id
        )

        if lineage is None:
            raise IntegrationError(
                f"media lineage {media_id} not found"
            )

        adapter = self._live_adapter(provider)[0]

        raw = self._fetch_one(
            adapter, provider, str(provider_item_id),
            item_kind,
        )

        tag_map = self._tag_map(adapter, provider)

        kind = self._kind_for(provider, item_kind, raw)

        relevant = self._relevant_subset(
            provider, kind, raw, tag_map
        )

        candidates = [self._candidate(provider, relevant)]

        ranked = rank_associations(
            lineage.file_path or "", candidates
        )

        strength = ranked[0]["strength"] if ranked else (
            "fuzzy_ambiguous"
        )
        basis = ranked[0]["basis"] if ranked else (
            "no corroborating match"
        )

        full_basis = f"explicit operator link; {basis}"

        observation_id = (
            self.organisation_records
            .record_metadata_observation(
                media_id=media_id,
                provider=provider,
                provider_item_id=str(provider_item_id),
                provider_item_kind=kind,
                source_fingerprint=(
                    self.organisation_records
                    .metadata_fingerprint(relevant)
                ),
                association_strength=strength,
                association_basis=full_basis,
                payload=relevant,
            )
        )

        self.organisation_records.connection.commit()

        return {
            "observation_id": observation_id,
            "media_id": media_id,
            "provider": provider,
            "provider_item_id": str(provider_item_id),
            "association_strength": strength,
            "association_basis": full_basis,
            "source_fingerprint": (
                self.organisation_records
                .metadata_fingerprint(relevant)
            ),
            "payload": dict(relevant),
        }

    def provider_tag_labels(self, provider: str) -> dict:
        """
        Live tag id-to-label map for tag-mapping UI
        pickers. In-memory only; nothing persisted.
        Jellyfin tags are inline strings, so its map is
        empty by design.
        """

        self._require_provider(provider)

        if provider == "jellyfin":
            return {}

        adapter = self._live_adapter(provider)[0]

        labels = adapter.list_tags()

        if isinstance(labels, dict):
            return {
                str(key): str(value)
                for key, value in labels.items()
            }

        return {}

    def fetch_library_for_planning(
        self,
        provider: str,
    ) -> list:
        """
        Fetch one provider library as relevant metadata
        subsets for planning-time matching. In-memory
        only; nothing persisted here. Callers persist
        what they cite through record_metadata_observation.
        Raises IntegrationError when the provider is
        unusable (callers degrade to review-state).
        """

        self._require_provider(provider)

        adapter = self._live_adapter(provider)[0]

        tag_map = self._tag_map(adapter, provider)

        subsets = []

        for kind, raw in self._fetch_library(
            adapter, provider
        ):
            try:
                subsets.append(
                    self._relevant_subset(
                        provider, kind, raw, tag_map
                    )
                )
            except Exception:
                continue

        return subsets

    def identify_media(
        self,
        *,
        path=None,
        candidate=None,
        providers=None,
        limit_per_provider=10,
    ) -> dict:
        """
        Identify one local file through provider API
        lookups without requiring a stored lineage.
        Read-only: no observations persisted, no
        filesystem mutation.

        Either `path` (a local file; the candidate
        identity comes from filename analysis) or an
        explicit `candidate` mapping (title, year,
        kind, season_number, episode_number) is
        required. Enabled providers are queried
        (Radarr movie lookup, Sonarr series lookup,
        Jellyfin item search); results normalise
        through the same canonical layer as sync and
        rank through the existing association
        authority. A single corroborated work yields
        planning snapshots; zero or competing works
        yield review reasons instead of guesses.
        """

        from app.metadata_providers.association import (
            detect_conflicts,
        )
        from app.organisation.planning import (
            _split_title_parts,
        )

        local = self._identification_candidate(
            path, candidate, _split_title_parts
        )

        wanted = (
            list(providers)
            if providers
            else ["radarr", "sonarr", "jellyfin"]
        )

        lookups: dict = {}
        raws: list = []

        for provider in wanted:
            try:
                self._require_provider(provider)
            except IntegrationError as error:
                lookups[provider] = {
                    "count": 0,
                    "error": str(error),
                }
                continue

            try:
                found, term = self._lookup_provider(
                    provider,
                    local,
                    limit=limit_per_provider,
                )
            except IntegrationError as error:
                lookups[provider] = {
                    "count": 0,
                    "error": str(error),
                }
                continue
            except Exception as error:
                lookups[provider] = {
                    "count": 0,
                    "error": (
                        f"{type(error).__name__}: {error}"
                    ),
                }
                continue

            lookups[provider] = {
                "count": len(found),
                "term": term,
            }

            for kind, raw in found:
                raws.append((provider, kind, raw))

        if not raws:
            return {
                "candidate": local,
                "lookups": lookups,
                "ranked": [],
                "conflicts": [],
                "snapshots": [],
                "outcome": "no_match",
                "reason": (
                    "provider lookup returned no "
                    "candidate records; review required"
                ),
            }

        aspirants = []

        for provider, kind, raw in raws:
            try:
                adapter = self._live_adapter(provider)[0]
                tag_map = self._tag_map(adapter, provider)
                relevant = self._relevant_subset(
                    provider, kind, raw, tag_map
                )
            except Exception:
                continue

            aspirants.append(
                {
                    "provider": provider,
                    "provider_item_id": str(
                        relevant.get("provider_item_id") or ""
                    ),
                    "kind": relevant.get("kind") or kind,
                    "path": relevant.get("path"),
                    "provider_ids": relevant.get(
                        "provider_ids", {}
                    ),
                    "parent_provider_id": relevant.get(
                        "parent_provider_id"
                    ),
                    "title": relevant.get("title"),
                    "year": relevant.get("year"),
                    "season_number": relevant.get(
                        "season_number"
                    ),
                    "episode_number": relevant.get(
                        "episode_number"
                    ),
                    "relevant": relevant,
                }
            )

        aspirants = [
            item
            for item in aspirants
            if item["provider_item_id"]
        ]

        ranked = rank_associations(
            str((path or "")),
            [
                {
                    key: item[key]
                    for key in (
                        "provider",
                        "provider_item_id",
                        "kind",
                        "path",
                        "provider_ids",
                        "parent_provider_id",
                        "title",
                        "year",
                        "season_number",
                        "episode_number",
                    )
                }
                for item in aspirants
            ],
        )

        conflicts = detect_conflicts(ranked)

        by_item = {
            (
                item["provider"],
                str(item["provider_item_id"]),
            ): item
            for item in aspirants
        }

        if conflicts:
            return {
                "candidate": local,
                "lookups": lookups,
                "ranked": ranked,
                "conflicts": conflicts,
                "snapshots": [],
                "outcome": "conflict",
                "reason": (
                    f"conflicting association: "
                    f"{conflicts[0]}; review required"
                ),
            }

        if not ranked or ranked[0]["strength"] in (
            "fuzzy_ambiguous",
        ):
            return {
                "candidate": local,
                "lookups": lookups,
                "ranked": ranked,
                "conflicts": [],
                "snapshots": [],
                "outcome": "weak",
                "reason": (
                    "provider lookup found only weak "
                    "matches; review required"
                ),
            }

        winner = ranked[0]
        matched = by_item.get(
            (
                winner["provider"],
                str(winner["provider_item_id"]),
            )
        )

        snapshots = []

        if matched is not None:
            relevant = dict(matched["relevant"] or {})
            snapshots.append(
                {
                    "provider": matched["provider"],
                    "provider_item_id": str(
                        matched["provider_item_id"]
                    ),
                    "provider_item_kind": matched["kind"],
                    "relevant": relevant,
                }
            )

        return {
            "candidate": local,
            "lookups": lookups,
            "ranked": ranked,
            "conflicts": [],
            "snapshots": snapshots,
            "outcome": "match" if snapshots else "weak",
            "reason": (
                f"provider {winner['provider']} record "
                f"{winner['provider_item_id']} "
                f"({winner['strength']}: "
                f"{winner['basis']})"
                if snapshots
                else "no usable provider record; "
                "review required"
            ),
        }

    @staticmethod
    def _identification_candidate(path, candidate, splitter):
        """Local candidate identity for provider lookup."""

        if isinstance(candidate, dict) and (
            candidate.get("title")
        ):
            title = str(candidate.get("title")).strip()
            year = candidate.get("year")
            kind = str(
                candidate.get("kind") or ""
            ).strip().lower()
            season = candidate.get("season_number")
            episode = candidate.get("episode_number")
        elif path:
            import os as _os

            title, year_text, season_text, episode_text = (
                splitter(_os.path.basename(str(path)))
            )
            title = str(title or "").strip()

            try:
                year = (
                    int(str(year_text).strip())
                    if str(year_text or "").strip()
                    else None
                )
            except (TypeError, ValueError):
                year = None

            try:
                season = (
                    int(str(season_text).strip())
                    if str(season_text or "").strip()
                    else None
                )
            except (TypeError, ValueError):
                season = None

            try:
                episode = (
                    int(str(episode_text).strip())
                    if str(episode_text or "").strip()
                    else None
                )
            except (TypeError, ValueError):
                episode = None

            kind = (
                "episode"
                if season is not None
                else "movie"
            )
        else:
            raise IntegrationError(
                "identify_media needs a file path or "
                "an explicit candidate identity"
            )

        if not title:
            raise IntegrationError(
                "local analysis found no usable title; "
                "review required"
            )

        return {
            "title": title,
            "year": year,
            "kind": kind or "movie",
            "season_number": season,
            "episode_number": episode,
        }

    @staticmethod
    def _lookup_terms(title: str) -> list:
        """
        Ordered lookup terms from a filename-derived
        title: the full title first, then
        progressively shorter trailing trims (release
        suffixes fall away) down to two tokens. The
        provider API does the matching heavy lift;
        NAMOA only trims. Bounded and deterministic.
        """

        words = str(title or "").split()
        terms = []

        while len(words) >= 2 and len(terms) < 6:
            term = " ".join(words).strip()

            if len(term) >= 4:
                terms.append(term)

            words = words[:-1]

        return terms or [str(title or "").strip()]

    def _lookup_provider(self, provider, local, limit=10):
        """
        (kind, raw) lookup hits for one provider.
        Raises IntegrationError when unusable; empty
        list when the provider has no candidates.
        Read-only.
        """

        adapter = self._live_adapter(provider)[0]
        title = local["title"]
        kind = local.get("kind") or "movie"
        hits: list = []
        seen: set = set()

        terms = self._lookup_terms(title)
        used = terms[0] if terms else title

        if provider == "radarr":
            for term in terms:
                for raw in (
                    adapter.lookup_movies(term) or []
                ):
                    if (
                        isinstance(raw, dict)
                        and str(raw.get("id")) not in seen
                    ):
                        seen.add(str(raw.get("id")))
                        hits.append(("movie", raw))

                if hits:
                    used = term
                    break
        elif provider == "sonarr":
            for term in terms:
                for raw in (
                    adapter.lookup_series(term) or []
                ):
                    if (
                        isinstance(raw, dict)
                        and str(raw.get("id")) not in seen
                    ):
                        seen.add(str(raw.get("id")))
                        hits.append(("series", raw))

                if hits:
                    used = term
                    break
        elif provider == "jellyfin":
            user_id = self._jellyfin_user_id(adapter)
            for term in terms:
                for raw in (
                    adapter.search_items(term, user_id) or []
                ):
                    if not isinstance(raw, dict):
                        continue
                    item_id = str(
                        raw.get("Id") or raw.get("id") or ""
                    )

                    if not item_id or item_id in seen:
                        continue

                    seen.add(item_id)
                    item_type = str(
                        raw.get("Type") or ""
                    ).strip().lower()
                    mapped = {
                        "movie": "movie",
                        "series": "series",
                        "season": "season",
                        "episode": "episode",
                    }.get(item_type, "file")
                    hits.append((mapped, raw))

                if hits:
                    used = term
                    break

        _ = kind

        return hits[: max(int(limit or 10), 1)], used

    # ---------------------------------------------------------
    # internals
    # ---------------------------------------------------------

    @staticmethod
    def _require_provider(provider: str) -> None:
        if provider not in PROVIDERS:
            raise IntegrationError(
                f"unknown provider '{provider}' "
                f"(expected one of {list(PROVIDERS)})"
            )

    def _store(self):
        if self.secret_store is not None:
            return self.secret_store

        from app.security.secret_store import (
            CompositeSecretStore,
            EnvSecretStore,
            KeyringSecretStore,
            LocalAppSecretStore,
        )

        return CompositeSecretStore(
            [
                EnvSecretStore(),
                KeyringSecretStore(),
                LocalAppSecretStore(),
            ]
        )

    def _resolve_secret(self, provider: str) -> tuple:
        from app.security.secret_store import (
            CompositeSecretStore,
            resolve_secret,
        )

        store = self._store()

        if isinstance(store, CompositeSecretStore):
            return resolve_secret(
                list(store._stores),
                f"namoa/{provider}",
                "api_key",
            )

        return resolve_secret(
            [store],
            f"namoa/{provider}",
            "api_key",
        )

    def _existing_user_id(self, provider: str):
        record = self.organisation_records.get_integration(
            provider
        )

        if record is None:
            return None

        return record.jellyfin_user_id

    def _public_view(
        self, record, *, provider: str | None = None
    ) -> dict:
        name = (
            record.provider
            if record is not None
            else provider
        )

        if name in PROVIDERS:
            status = self.credential_status(name)
        else:
            status = {"present": False, "source": None}

        return {
            "provider": name,
            "enabled": (
                bool(record.enabled)
                if record is not None
                else False
            ),
            "base_url": (
                record.base_url
                if record is not None
                else ""
            ),
            "jellyfin_user_id": (
                record.jellyfin_user_id
                if record is not None
                else None
            ),
            "credential_present": status["present"],
            "credential_source": status["source"],
            "storage_mode": _storage_mode(status["source"]),
            "path_mappings": (
                self.organisation_records.list_path_mappings(
                    name
                )
                if name in PROVIDERS
                else []
            ),
            "last_sync": (
                self.organisation_records.latest_sync_run(
                    name
                )
                if name in PROVIDERS
                else None
            ),
        }

    def _live_adapter(self, provider: str):
        record = self.organisation_records.get_integration(
            provider
        )

        if record is None or not record.enabled:
            raise IntegrationError(
                f"provider '{provider}' is not enabled; "
                f"configure and enable it first"
            )

        if not record.base_url:
            raise IntegrationError(
                f"provider '{provider}' has no base URL "
                f"configured"
            )

        secret, source = self._resolve_secret(provider)

        if not secret:
            raise IntegrationError(
                f"no credential available for provider "
                f"'{provider}'; enter an API key or set "
                f"{ENV_VAR_NAMES[provider]}"
            )

        return ADAPTER_CLASSES[provider](
            record.base_url, secret
        ), source

    # ---------------------------------------------------------
    # explicit provider-root / local-root mappings
    # ---------------------------------------------------------

    def list_path_mappings(
        self, provider: str | None = None
    ) -> list:
        """
        Explicit deterministic root relationships for
        association across container/host namespaces.
        Read-only; reviewable configuration.
        """

        if provider is not None:
            self._require_provider(provider)

        return (
            self.organisation_records
            .list_path_mappings(provider)
        )

    def save_path_mapping(
        self,
        provider: str,
        *,
        provider_root: str,
        local_root: str,
    ) -> dict:
        """
        Record one explicit provider-root to local-root
        relationship. Commits. Raises IntegrationError for
        unusable shapes; the repository refuses relative
        roots and unknown providers.
        """

        self._require_provider(provider)

        try:
            saved = (
                self.organisation_records
                .save_path_mapping(
                    provider=provider,
                    provider_root=provider_root,
                    local_root=local_root,
                )
            )
        except Exception as error:
            raise IntegrationError(str(error)) from error

        self.organisation_records.connection.commit()

        return saved

    def delete_path_mapping(self, mapping_id: int) -> bool:
        """Delete one explicit root mapping. Commits."""

        removed = (
            self.organisation_records
            .delete_path_mapping(mapping_id)
        )

        self.organisation_records.connection.commit()

        return removed

    def assess_observation_compatibility(
        self, provider: str | None = None
    ) -> dict:
        """
        Kind-compatibility assessment over persisted
        metadata observations. Compares each observation's
        stored provider kind against its lineage path
        hint through the association authority. Withdrawn
        rows are reported separately and never
        reassessed. Read-only.
        """

        if provider is not None:
            self._require_provider(provider)

        rows = (
            self.organisation_records
            .observations_with_lineage_paths(provider)
        )

        compatible = 0
        incompatible = []
        withdrawn = 0
        withdrawn_keys = set()
        unknown = 0

        for entry in rows:
            observation = entry["observation"]

            if (
                isinstance(
                    observation.payload, dict
                )
                and observation.payload.get("withdrawn")
            ):
                withdrawn += 1
                withdrawn_keys.add(
                    (
                        observation.media_id,
                        observation.provider,
                        observation.provider_item_id,
                    )
                )
                continue

            if not kinds_compatible(
                observation.provider_item_kind,
                observation.provider,
                entry["file_path"] or "",
            ):
                incompatible.append(
                    {
                        "observation_id": observation.id,
                        "media_id": observation.media_id,
                        "provider": observation.provider,
                        "provider_item_id": (
                            observation.provider_item_id
                        ),
                        "provider_item_kind": (
                            observation.provider_item_kind
                        ),
                        "association_strength": (
                            observation.association_strength
                        ),
                        "file_path": entry["file_path"],
                    }
                )
            elif (
                lineage_kind_hint(
                    entry["file_path"] or ""
                )
                == "unknown"
            ):
                unknown += 1
            else:
                compatible += 1

        media_ids = sorted(
            {
                item["media_id"]
                for item in incompatible
            }
        )

        return {
            "provider": provider,
            "compatible": compatible,
            "incompatible": incompatible,
            "incompatible_count": len(incompatible),
            "affected_media_ids": media_ids,
            "withdrawn": withdrawn,
            "withdrawn_keys": sorted(withdrawn_keys),
            "unknown_kind": unknown,
        }

    def withdraw_incompatible_observations(
        self,
        provider: str | None = None,
        *,
        reason: str = "",
    ) -> dict:
        """
        Append-only correction for observations attached
        to a provably incompatible lineage kind (for
        example Sonarr TV records on movie lineages via
        a shared TMDB id). One withdrawal row is
        appended per distinct (lineage, provider, item);
        planning skips withdrawn snapshots while the
        original rows stay untouched as provenance.
        Commits. Never deletes or rewrites history.
        """

        assessment = self.assess_observation_compatibility(
            provider
        )

        already = set(assessment["withdrawn_keys"])
        seen = set()
        withdrawn_ids = []

        for item in assessment["incompatible"]:
            key = (
                item["media_id"],
                item["provider"],
                item["provider_item_id"],
            )

            if key in seen or key in already:
                continue

            seen.add(key)

            payload = {
                "withdrawn": True,
                "reason": reason
                or (
                    "provider record kind "
                    f'{item["provider_item_kind"]!r} is '
                    "incompatible with the lineage media "
                    "kind; attached via an unsafe "
                    "cross-kind external-id match"
                ),
                "provider_item_id": (
                    item["provider_item_id"]
                ),
                "kind": item["provider_item_kind"],
            }

            self.organisation_records.record_metadata_observation(
                media_id=item["media_id"],
                provider=item["provider"],
                provider_item_id=item["provider_item_id"],
                provider_item_kind=(
                    item["provider_item_kind"]
                ),
                source_fingerprint=(
                    self.organisation_records
                    .metadata_fingerprint(payload)
                ),
                # fuzzy_ambiguous is the weakest
                # authority strength (never
                # authoritative, ignored by conflict
                # and duplicate-claim detection);
                # the payload withdrawn flag is what
                # excludes the snapshot from
                # planning. No schema change needed:
                # association_strength has a CHECK
                # constraint over the four authority
                # strengths.
                association_strength="fuzzy_ambiguous",
                association_basis=(
                    "withdrawn: "
                    + str(payload["reason"])
                ),
                payload=payload,
            )

            withdrawn_ids.append(item["observation_id"])

        self.organisation_records.connection.commit()

        pending = set()
        for item in assessment["incompatible"]:
            key = (
                item["media_id"],
                item["provider"],
                item["provider_item_id"],
            )
            if key not in seen and key not in already:
                pending.add(key)

        return {
            "provider": provider,
            "withdrawn": len(seen),
            "withdrawn_observation_ids": withdrawn_ids,
            "affected_media_ids": (
                assessment["affected_media_ids"]
            ),
            "remaining_incompatible": len(pending),
        }

    def jellyfin_users(self) -> list:
        """
        Live Jellyfin user list (id and name) for the
        explicit library-user picker. In-memory only;
        nothing persisted. Raises IntegrationError when
        unreachable.
        """

        adapter = self._live_adapter("jellyfin")[0]

        try:
            users = adapter.list_users()
        except Exception as error:
            raise IntegrationError(
                f"could not list Jellyfin users "
                f"({type(error).__name__}: {error})"
            ) from error

        return [
            {
                "id": str(item.get("Id") or item.get("id") or ""),
                "name": str(
                    item.get("Name") or item.get("name") or ""
                ),
            }
            for item in users
            if isinstance(item, dict)
        ]

    def save_jellyfin_user(self, user_id: str) -> dict:
        """
        Persist the explicit Jellyfin library user id
        (non-secret configuration). Required when the
        server holds several users, because a bare API
        key carries no user context and /Users/Me
        answers 400. Commits.
        """

        self._require_provider("jellyfin")

        cleaned = str(user_id or "").strip()

        if not cleaned:
            raise IntegrationError(
                "Jellyfin user id must be non-empty"
            )

        record = self.organisation_records.get_integration(
            "jellyfin"
        )

        self.organisation_records.save_integration(
            provider="jellyfin",
            enabled=bool(record.enabled) if record else False,
            base_url=record.base_url if record else "",
            jellyfin_user_id=cleaned,
            secret_ref=record.secret_ref if record else "",
        )

        self.organisation_records.connection.commit()

        return self.get_provider("jellyfin")

    @staticmethod
    def _mapping_prefix_key(root: str) -> str | None:
        """Normalised prefix form of a configured root."""

        import os as _os

        text = str(root or "").strip().replace("\\", "/")

        if not text.startswith("/"):
            return None

        cleaned = text.rstrip("/") or "/"

        try:
            key = _os.path.normcase(cleaned)
        except (OSError, ValueError):
            return None

        return key.replace("\\", "/")

    def _mapped_candidates(
        self, provider: str, path: str
    ) -> list:
        """
        Deterministic provider-path to local-path
        candidates through explicit mappings only.

        Every mapping registered for this provider whose
        provider_root prefixes the provider path yields
        exactly one candidate (local_root + remainder).
        No guessing: unmapped paths yield no candidates,
        and similarly named roots are never equated
        without a registered relationship.
        """

        import os as _os

        text = str(path or "").strip().replace("\\", "/")

        if not text:
            return []

        try:
            path_key = _os.path.normcase(text).replace(
                "\\", "/"
            )
        except (OSError, ValueError):
            return []

        candidates = []

        cache = getattr(self, "_mapping_cache", None) or {}

        for mapping in cache.get(provider, []):
            prefix = self._mapping_prefix_key(
                mapping.get("provider_root")
            )
            local = self._mapping_prefix_key(
                mapping.get("local_root")
            )

            if not prefix or not local:
                continue

            if prefix == "/":
                continue

            if not (
                path_key == prefix
                or path_key.startswith(prefix + "/")
            ):
                continue

            remainder = path_key[len(prefix):]

            candidate = (
                local + remainder if local != "/"
                else remainder or "/"
            )

            if candidate not in candidates:
                candidates.append(candidate)

        return candidates

    @staticmethod
    def _external_id_pairs(source: dict) -> dict:
        """
        Normalised tmdb/tvdb/imdb pairs from a relevant
        subset (own provider_ids plus parent ids).
        """

        pairs = {}

        for container in (
            source.get("provider_ids"),
            source.get("parent_provider_ids"),
        ):
            if not isinstance(container, dict):
                continue

            for raw_key, raw_value in container.items():
                if not isinstance(raw_key, str):
                    continue

                key = raw_key.strip().lower()

                if key in (
                    "tmdbid", "tmdb",
                ):
                    key = "tmdb"
                elif key in ("tvdbid", "tvdb"):
                    key = "tvdb"
                elif key in ("imdbid", "imdb"):
                    key = "imdb"
                else:
                    continue

                if raw_value is None or isinstance(
                    raw_value, bool
                ):
                    continue

                text = str(raw_value).strip().lower()

                if text and text != "0":
                    pairs[key] = text

        return pairs

    def _known_external_id_index(self) -> dict:
        """
        Map (id-key, id-value) to lineage ids from every
        previously persisted metadata observation payload.
        This is the cross-provider evidence that lets a
        Radarr tmdb id meet a Jellyfin tmdb id for the
        same file without inventing identity.
        """

        index = {}

        try:
            rows = self.organisation_records.connection.execute(
                """
                SELECT media_id, payload_json
                FROM metadata_observations
                """
            ).fetchall()
        except Exception:
            return index

        import json as _json

        for row in rows:
            try:
                media_id = int(row[0])
            except (TypeError, ValueError):
                continue

            try:
                payload = _json.loads(row[1] or "{}")
            except (TypeError, ValueError):
                continue

            if not isinstance(payload, dict):
                continue

            for key, value in (
                self._external_id_pairs(payload).items()
            ):
                index.setdefault(
                    (key, value), set()
                ).add(media_id)

        return {
            key: sorted(media_ids)
            for key, media_ids in index.items()
        }

    def _match_lineage(
        self, relevant, lineages_by_path
    ):
        """
        Conservative lineage association for one
        provider record, decided through the existing
        association authority vocabulary.

        Evidence order, strongest first:

        1. exact: canonical provider path equals a
           lineage path (association strength
           exact_path).
        2. mapped: an explicit provider-root to
           local-root relationship maps the provider
           path onto exactly one lineage path
           (strength exact_path on the mapped path).
           Zero mapped hits mean no match; several
           mapped hits mean ambiguous (needs review),
           never a guess.
        3. directory: the mapped provider directory
           holds exactly one lineage video file, so the
           record attaches at directory level (a
           directory-rename style consolidation; still
           deterministic). Several files mean
           ambiguous.
        4. cross_id: a strong external id (tmdb, tvdb,
           imdb, own or parent record) agrees with ids
           already observed for exactly one lineage
           from any provider (strength
           cross_provider_id). Several lineages mean
           ambiguous.
        5. title: title/year (movies) or
           title/season/episode (episodes) corroborated
           by the filename is recorded as review-only
           evidence (strength single_id_title in the
           authority, but sync never auto-attaches on
           title evidence alone). Several or zero
           filename-corroborated lineages mean no
           match.

        Returns (outcome, media_id) with outcome in
        exact, mapped, directory, cross_id, review,
        ambiguous or none. Only the first four attach
        observations; review and ambiguous feed the
        needs-review counter; none feeds unmatched.
        Title-only similarity without filename
        corroboration never attaches and never
        reviews: it is simply unmatched.
        """

        path = (relevant.get("path") or "").strip()

        if not path:
            return ("none", None)

        media_id = lineages_by_path.get(
            _canonical_key(path)
        )

        if media_id is not None:
            return ("exact", media_id)

        provider = str(relevant.get("_provider") or "").strip()

        provider_kind = relevant.get("kind")

        mapped_hits = []

        for candidate in self._mapped_candidates(
            provider, path
        ):
            key = _canonical_key(candidate)

            if key is None:
                continue

            if not kinds_compatible(
                provider_kind, provider, key
            ):
                continue

            hit = lineages_by_path.get(key)

            if hit is not None and hit not in mapped_hits:
                mapped_hits.append(hit)

        if len(mapped_hits) == 1:
            return ("mapped", mapped_hits[0])

        if len(mapped_hits) > 1:
            return ("ambiguous", None)

        directory_hits = self._mapped_directory_hits(
            provider, path, lineages_by_path,
            relevant=relevant,
        )

        if len(directory_hits) == 1:
            return ("directory", directory_hits[0])

        if len(directory_hits) > 1:
            return ("ambiguous", None)

        cross_hits = [
            media_id
            for media_id in self._cross_provider_id_hits(
                relevant
            )
            if kinds_compatible(
                provider_kind,
                provider,
                self._lineage_path_of(media_id),
            )
        ]

        if len(cross_hits) == 1:
            return ("cross_id", cross_hits[0])

        if len(cross_hits) > 1:
            return ("ambiguous", None)

        if self._title_evidence_hit(
            relevant,
            lineages_by_path,
            provider_kind=provider_kind,
            provider=provider,
        ):
            return ("review", None)

        return ("none", None)

    def _lineage_path_of(self, media_id):
        """Lineage path key for one media id, or None."""

        reverse = getattr(self, "_lineage_reverse", None) or {}

        return reverse.get(media_id)

    def _mapped_directory_hits(
        self, provider, path, lineages_by_path,
        *, relevant=None, kind="",
    ) -> list:
        """
        Lineage ids holding exactly the mapped provider
        directory. File records (movie files, episode
        files, media items) match lineages inside the
        mapped containing directory; folder records
        (movies, series, seasons) match lineages inside
        the mapped directory itself. Pure path arithmetic
        over the lineage index; no filesystem access.
        """

        import os as _os

        folder_kinds = {"movie", "series", "season"}

        if isinstance(relevant, dict):
            provider_kind = relevant.get("kind")
        else:
            provider_kind = kind

        hits = []

        for candidate in self._mapped_candidates(
            provider, path
        ):
            key = _canonical_key(candidate)

            if key is None:
                continue

            if (
                str(provider_kind or "").strip().lower()
                in folder_kinds
            ):
                wanted = key
            else:
                wanted = _os.path.dirname(key)

            for lineage_key, media_id in (
                lineages_by_path.items()
            ):
                if (
                    _os.path.dirname(lineage_key or "")
                    == wanted
                    and media_id not in hits
                    and kinds_compatible(
                        provider_kind, provider, lineage_key
                    )
                ):
                    hits.append(media_id)

        return hits

    def _sibling_candidates(
        self, media_id, provider, relevant
    ) -> list:
        """
        Stored observation rows for one lineage as
        ranking candidates (provider, item, kind and ids
        exactly as persisted). Gives rank_associations
        the second provider it needs to confirm a
        cross_provider_id strength honestly.
        """

        siblings = []

        try:
            stored = (
                self.organisation_records
                .list_metadata_observations(media_id)
            )
        except Exception:
            return siblings

        for observation in stored or []:
            payload = getattr(
                observation, "payload", None
            )

            if not isinstance(payload, dict):
                continue

            item_id = getattr(
                observation, "provider_item_id", ""
            )
            kind = getattr(
                observation, "provider_item_kind", ""
            )

            if not str(item_id).strip() or not str(
                kind
            ).strip():
                continue

            siblings.append(
                {
                    "provider": getattr(
                        observation, "provider", provider
                    ),
                    "provider_item_id": str(item_id),
                    "kind": str(kind),
                    "path": payload.get("path"),
                    "provider_ids": (
                        payload.get("provider_ids", {})
                    ),
                    "title": payload.get("title"),
                    "year": payload.get("year"),
                    "season_number": payload.get(
                        "season_number"
                    ),
                    "episode_number": payload.get(
                        "episode_number"
                    ),
                }
            )

        return siblings

    def _cross_provider_id_hits(self, relevant) -> list:
        """Lineage ids sharing a strong external id."""

        pairs = self._external_id_pairs(relevant)

        if not pairs:
            return []

        index = getattr(self, "_known_id_cache", None)

        if index is None:
            index = self._known_external_id_index()

        hits = []

        for key, value in pairs.items():
            for media_id in index.get((key, value), []):
                if media_id not in hits:
                    hits.append(media_id)

        return hits

    @staticmethod
    def _title_evidence_hit(
        relevant,
        lineages_by_path,
        *,
        provider_kind=None,
        provider="",
    ) -> bool:
        """
        True when title/year (or title/season/episode)
        evidence is corroborated by some kind-compatible
        lineage filename. Review-only signal; never
        attaches. Mirrors the authority's single_id_title
        corroboration rule without auto-matching.
        """

        import os as _os
        import re as _re

        title = relevant.get("title")

        if not isinstance(title, str) or not title.strip():
            return False

        title_tokens = set(
            _re.findall(r"[a-z0-9]+", title.lower())
        )

        if not title_tokens:
            return False

        kind = str(
            relevant.get("kind") or ""
        ).strip().lower()

        if kind == "episode":
            if (
                relevant.get("season_number") is None
                or relevant.get("episode_number") is None
            ):
                return False
        elif relevant.get("year") is None:
            return False

        for lineage_key in lineages_by_path:
            if not kinds_compatible(
                provider_kind
                if provider_kind is not None
                else relevant.get("kind"),
                provider,
                lineage_key,
            ):
                continue

            basename_tokens = set(
                _re.findall(
                    r"[a-z0-9]+",
                    _os.path.basename(
                        lineage_key or ""
                    ).lower(),
                )
            )

            if title_tokens & basename_tokens:
                return True

        return False

    def _lineage_path_index(self) -> dict:
        index = {}

        for lineage in (
            self.media_repository.get_active_lineages()
        ):
            path = lineage.file_path or ""

            if not path:
                continue

            key = _canonical_key(path)

            if key is not None:
                index[key] = lineage.id

        return index

    def _tag_map(self, adapter, provider: str) -> dict:
        if provider == "jellyfin":
            return {}

        try:
            labels = adapter.list_tags()
        except Exception:
            return {}

        if isinstance(labels, dict):
            return labels

        return {}

    def _fetch_library(self, adapter, provider: str) -> list:
        """
        Raw (kind, item) pairs across the provider
        library. Servarr file rows carry their parent
        movie/series context for association.
        """

        if provider == "jellyfin":
            try:
                user_id = self._jellyfin_user_id(adapter)
            except IntegrationError:
                raise
            except Exception as error:
                raise IntegrationError(
                    "Jellyfin user lookup failed "
                    f"({type(error).__name__}: {error}); "
                    "the API key may lack a user context "
                    "or the server may be unreachable. "
                    "Test the connection, then sync again."
                )

            items = []

            for kind, method in (
                ("movie", adapter.list_movies),
                ("series", adapter.list_series),
                ("episode", adapter.list_episode_items),
            ):
                try:
                    rows = method(user_id)
                except Exception:
                    rows = []

                for row in rows or []:
                    if isinstance(row, dict):
                        items.append((kind, row))

            return items

        if provider == "radarr":
            tag_map = self._tag_map(adapter, provider)

            items = []

            for movie in adapter.list_movies() or []:
                if not isinstance(movie, dict):
                    continue

                items.append(("movie", movie))

                for entry in (
                    movie.get("movieFile")
                    and [movie.get("movieFile")]
                    or []
                ):
                    if isinstance(entry, dict):
                        row = dict(entry)
                        row["_movie"] = movie
                        row["_tag_map"] = tag_map
                        items.append(("file", row))

            try:
                loose = adapter.list_movie_files() or []
            except Exception:
                loose = []

            seen = {
                str(
                    (entry.get("id") if isinstance(
                        entry, dict) else None)
                )
                for _, entry in items
                if isinstance(entry, dict)
            }

            for entry in loose:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("id")) in seen:
                    continue
                row = dict(entry)
                row["_tag_map"] = tag_map
                items.append(("file", row))

            return items

        items = []

        for series in adapter.list_series() or []:
            if not isinstance(series, dict):
                continue

            items.append(("series", series))

            series_id = series.get("id")

            try:
                files = (
                    adapter.list_episode_files(series_id)
                    if series_id is not None
                    else []
                )
            except Exception:
                files = []

            for entry in files or []:
                if not isinstance(entry, dict):
                    continue
                row = dict(entry)
                row["_series"] = series
                items.append(("file", row))

        return items

    def _fetch_one(
        self, adapter, provider, item_id, item_kind
    ) -> dict:
        kind = (item_kind or "file").strip().lower()

        if provider == "jellyfin":
            return adapter.get_item(item_id)

        if provider == "radarr":
            if kind in ("movie",):
                return adapter.get_movie(item_id)
            for _, entry in self._fetch_library(
                adapter, provider
            ):
                if str(entry.get("id")) == str(item_id):
                    return entry
            raise IntegrationError(
                f"radarr item '{item_id}' not found"
            )

        if kind in ("series",):
            return adapter.get_series(item_id)

        for _, entry in self._fetch_library(
            adapter, provider
        ):
            if str(entry.get("id")) == str(item_id):
                return entry

        raise IntegrationError(
            f"sonarr item '{item_id}' not found"
        )

    @staticmethod
    def _kind_for(provider, item_kind, raw) -> str:
        kind = (item_kind or "").strip().lower()

        if provider == "jellyfin":
            item_type = str(
                (raw or {}).get("Type") or ""
            ).strip().lower()
            return {
                "movie": "movie",
                "series": "series",
                "season": "season",
                "episode": "episode",
            }.get(item_type, kind or "file")

        return kind or "file"

    def _relevant_subset(
        self, provider, kind, raw, tag_map
    ) -> dict:
        """
        Normalise one raw provider item into the relevant
        metadata subset persisted in metadata
        observations. Unknown fields are ignored; missing
        data stays explicit; root folder paths are
        retained for provider-managed overlap detection.
        """

        raw = dict(raw or {})

        if provider == "jellyfin":
            record = (
                normalize_jellyfin_item(raw)
            )
        elif provider == "radarr":
            if kind == "file":
                record = (normalize_radarr_movie_file(raw))
            else:
                record = (
                    normalize_radarr_movie(
                        raw, tag_map or {}
                    )
                )
        else:
            if kind == "file":
                record = (normalize_sonarr_episode_file(raw))
            elif kind in ("series",):
                record = (
                    normalize_sonarr_series(
                        raw, tag_map or {}
                    )
                )
            else:
                record = (normalize_sonarr_episode(raw))

        relevant = {
            "provider_item_id": record.provider_item_id,
            "kind": record.kind,
            "title": record.title,
            "year": record.year,
            "season_number": record.season_number,
            "episode_number": record.episode_number,
            "path": record.path,
            "root_folder_path": raw.get("rootFolderPath"),
            "parent_provider_id": (
                record.parent_provider_id
            ),
            "provider_ids": dict(record.provider_ids or {}),
            "genres": list(record.genres or []),
            "tags": list(record.tags or []),
            "certification": record.certification,
            "collections": list(record.collections or []),
            "ratings": dict(record.ratings or {}),
            "monitored": bool(record.monitored),
            "has_file": bool(record.has_file),
        }

        parent = raw.get("_movie") or raw.get("_series")

        if isinstance(parent, dict):
            relevant["parent_title"] = parent.get("title")
            relevant["parent_path"] = parent.get("path")
            relevant["parent_provider_ids"] = dict(
                self._parent_ids(provider, parent)
            )

            if (
                provider in ("radarr", "sonarr")
                and not relevant["root_folder_path"]
            ):
                relevant["root_folder_path"] = (
                    parent.get("rootFolderPath")
                )

            if kind == "file":
                # File rows carry the path but no
                # descriptive fields of their own
                # (Sonarr episode-file lists embed no
                # episodes array, so episode numbers
                # stay None as genuine provider data).
                # Inherit title/year/tags from the
                # parent movie/series so persisted
                # evidence is honest instead of blank.
                # Parentage never changes the file's
                # own semantic kind.
                if not relevant["title"]:
                    parent_title = parent.get("title")

                    if isinstance(
                        parent_title, str
                    ) and parent_title.strip():
                        relevant["title"] = (
                            parent_title.strip()
                        )

                if relevant["year"] is None:
                    relevant["year"] = _clean_year(
                        parent.get("year")
                    )

                if not relevant["tags"]:
                    relevant["tags"] = (
                        _resolve_parent_tag_labels(
                            parent.get("tags"),
                            tag_map or {},
                        )
                    )

                if not relevant["genres"]:
                    genres = parent.get("genres")

                    if isinstance(genres, list):
                        relevant["genres"] = [
                            str(item).strip()
                            for item in genres
                            if isinstance(item, str)
                            and item.strip()
                        ]

                if not relevant.get("certification"):
                    parent_cert = parent.get(
                        "certification"
                    )

                    if (
                        isinstance(parent_cert, str)
                        and parent_cert.strip()
                    ):
                        relevant["certification"] = (
                            parent_cert.strip()
                        )

                if not relevant["collections"]:
                    collections = parent.get(
                        "collections"
                    )

                    inherited = []

                    if isinstance(collections, list):
                        inherited = [
                            str(item).strip()
                            for item in collections
                            if isinstance(item, str)
                            and item.strip()
                        ]

                    # Radarr movies carry a singular
                    # {"collection": {"title": ...}} shape.
                    singular = parent.get("collection")

                    if isinstance(singular, dict):
                        title = singular.get("title")

                        if (
                            isinstance(title, str)
                            and title.strip()
                            and title.strip() not in inherited
                        ):
                            inherited.append(title.strip())

                    if inherited:
                        relevant["collections"] = inherited

                if not relevant.get("ratings"):
                    ratings = parent.get("ratings")

                    if isinstance(ratings, dict):
                        relevant["ratings"] = dict(
                            ratings
                        )

        return relevant

    @staticmethod
    def _parent_ids(provider, parent: dict) -> dict:
        ids = {}

        for key in (
            "tmdbId", "tvdbId", "imdbId", "tvMazeId"
        ):
            value = parent.get(key)

            if value is not None:
                ids[key] = value

        return ids

    def _candidate(
        self, provider, relevant: dict, *, path_override=None
    ) -> dict:
        return {
            "provider": provider,
            "provider_item_id": relevant.get(
                "provider_item_id"
            ),
            "kind": relevant.get("kind"),
            "path": (
                path_override
                if path_override is not None
                else relevant.get("path")
            ),
            "provider_ids": relevant.get(
                "provider_ids", {}
            ),
            "title": relevant.get("title"),
            "year": relevant.get("year"),
            "season_number": relevant.get("season_number"),
            "episode_number": relevant.get(
                "episode_number"
            ),
        }

    def _persist_relevant(
        self,
        provider: str,
        media_id: int,
        relevant: dict,
        *,
        basis: str,
        match_outcome: str = "exact",
    ) -> None:
        # The association decision itself is made by
        # _match_lineage; the existing association
        # authority (rank_associations) independently
        # confirms the strength so persisted rows carry
        # authority vocabulary, never a parallel claim.
        # For mapped/directory matches the candidate
        # path handed to the ranker is the matched
        # lineage path itself, so an exact_path strength
        # is honest rather than a relabelled guess.
        lineage = self.media_repository.get_media_item(
            media_id
        )

        candidate_path = relevant.get("path")

        if match_outcome in ("mapped", "directory"):
            candidate_path = (
                lineage.file_path
                if lineage is not None
                else candidate_path
            )

        candidate = self._candidate(
            provider, relevant, path_override=candidate_path
        )

        candidates = [candidate]

        if match_outcome == "cross_id":
            # Cross-provider strength needs at least two
            # providers sharing the id in one ranking, so
            # the already-persisted sibling observations
            # for this lineage join as real evidence (same
            # provider/item/kind/ids they were stored
            # with). Nothing is invented: every sibling is
            # a stored row.
            candidates.extend(
                self._sibling_candidates(
                    media_id, provider, relevant
                )
            )

        ranked = rank_associations(
            lineage.file_path or "", candidates
        )

        strength = ranked[0]["strength"] if ranked else (
            "fuzzy_ambiguous"
        )

        self.organisation_records.record_metadata_observation(
            media_id=media_id,
            provider=provider,
            provider_item_id=str(
                relevant.get("provider_item_id") or ""
            ),
            provider_item_kind=str(
                relevant.get("kind") or "file"
            ),
            source_fingerprint=(
                self.organisation_records
                .metadata_fingerprint(relevant)
            ),
            association_strength=strength,
            association_basis=(
                f"{basis}; "
                f"{ranked[0]['basis'] if ranked else 'no match'}"
            ),
            payload=relevant,
        )

    def _jellyfin_user_id(self, adapter) -> str:
        record = self.organisation_records.get_integration(
            "jellyfin"
        )

        if record is not None and record.jellyfin_user_id:
            return str(record.jellyfin_user_id)

        user_id = adapter.resolve_user_id()

        self.organisation_records.save_integration(
            provider="jellyfin",
            enabled=bool(record.enabled) if record else False,
            base_url=record.base_url if record else "",
            jellyfin_user_id=str(user_id),
            secret_ref=record.secret_ref if record else "",
        )

        self.organisation_records.connection.commit()

        return str(user_id)

    def _notify(self, category, title, message, media_id=None):
        if self.notification_service is None:
            return

        try:
            self.notification_service.create(
                category=category,
                title=title,
                message=message,
                media_id=media_id,
            )
        except Exception:
            from app.utils.logger import logger

            logger.warning(
                "notification write skipped (best-effort): "
                f"{category} {title}"
            )


def _storage_mode(source) -> str | None:
    """Map a resolve_secret source label to a UI storage mode.

    Keyring resolves report "secure-os", the local file
    fallback reports "local-app", environment overrides
    report "environment", and any other held source keeps
    its own label (for example "memory" in tests).
    Absent credentials report None.
    """

    if not source:
        return None

    label = str(source)

    if label == "keyring":
        return "secure-os"

    return label


def _canonical_key(path: str) -> str | None:
    from app.organisation.planning import (
        canonical_path_key,
    )

    return canonical_path_key(path)


def _clean_year(value):
    """Best-effort year int for parent context fill."""

    if value is None or isinstance(value, bool):
        return None

    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None

    return number if 1800 <= number <= 2200 else None


def _resolve_parent_tag_labels(tag_ids, tag_map) -> list:
    """Resolve parent tag ids through the live tag map."""

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
        if isinstance(item, bool):
            continue
        try:
            numeric = int(item)
        except (TypeError, ValueError):
            continue
        label = (tag_map or {}).get(numeric)

        if isinstance(label, str) and label.strip():
            labels.append(label.strip())

    return labels
