class OrganisationService:
    """
    Application boundary for the Library Organisation domain
    (Sprint 13).

    Delegates to existing authorities; it never reimplements
    organisation intelligence, identity, or provenance logic:

        decision runs / proposals -> OrganisationIntelligenceService
                                      + OrganisationRepository

    Sprint 13 boundary: this service performs ZERO filesystem
    mutation. Generating and accepting proposals records durable,
    explainable intent only; actual organisation execution is the
    Sprint 14 boundary.
    """

    def __init__(
        self,
        *,
        organisation_intelligence_service,
        organisation_repository,
        default_policy=None,
        notification_service=None,
        media_repository=None,
        integration_service=None,
    ):

        self.organisation_intelligence_service = (
            organisation_intelligence_service
        )
        self.organisation_records = (
            organisation_repository
        )
        self.default_policy = default_policy
        self.notification_service = notification_service
        self.media_repository = media_repository
        self.integration_service = integration_service

    def _notify(
        self,
        category: str,
        title: str,
        message: str,
        *,
        media_id=None,
    ):
        """
        Best-effort notification emission. A notification write must
        never fail or alter the organisation decision workflow.
        """

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

    # ---------------------------------------------------------
    # decision runs / proposal generation
    # ---------------------------------------------------------

    def generate_proposals(self, policy=None, preferences=None):
        """
        Run one deterministic decision pass over the current
        library. Non-destructive by construction: it persists
        proposals and their provenance anchor, nothing else.

        `preferences` are operator-owned metadata/tag/naming/
        classification preferences resolved into the effective
        policy by the intelligence authority; their payload is
        snapshotted with the decision run for attribution.
        """

        return (
            self.organisation_intelligence_service
            .generate_proposals(
                policy=(
                    policy or self.default_policy
                ),
                preferences=preferences,
            )
        )

    def get_current_proposals(self):
        """
        The latest completed decision run with its proposals.

        Returns None when no decision run exists yet (fresh
        database honesty); callers render an empty state rather
        than inventing content.
        """

        decision_run = (
            self.organisation_records.latest_decision_run()
        )

        if decision_run is None:

            return None

        proposals = (
            self.organisation_records.list_by_decision_run(
                decision_run.id
            )
        )

        return {
            "decision_run": decision_run,
            "proposals": proposals,
        }

    def list_decision_runs(self):

        return (
            self.organisation_records.list_decision_runs()
        )

    def get_decision_run(self, decision_run_id: int):
        """
        One organisation decision-run anchor, or None when it
        does not exist.
        """

        return (
            self.organisation_records.get_decision_run(
                decision_run_id
            )
        )

    def get_proposal(self, proposal_id: int):
        """
        One durable organisation proposal with its lifecycle
        events. Raises ValueError when it does not exist.
        """

        proposal = self.organisation_records.get_proposal(
            proposal_id
        )

        if proposal is None:

            raise ValueError(
                f"organisation proposal {proposal_id} "
                f"not found"
            )

        return {
            "proposal": proposal,
            "events": (
                self.organisation_records.events_for(
                    proposal_id
                )
            ),
        }

    def list_proposals_by_media(self, media_id: int):

        return (
            self.organisation_records.list_by_media(
                media_id
            )
        )

    # ---------------------------------------------------------
    # explicit evidence acquisition
    # ---------------------------------------------------------

    def acquire_content_hashes(self, media_ids=None):
        """
        Explicit, on-demand sha256 acquisition for chosen
        lineages (default: all active lineages) as OPTIONAL
        evidence.

        Deliberately separate from normal scanning: a normal
        scan reads only filesystem metadata. Acquisition reads
        full file contents ONLY when explicitly requested here,
        and only after verifying the live size + mtime still
        match the lineage's current observation.

        EVIDENCE SEMANTICS: the digest is returned to the caller
        as forward-only, in-memory evidence. Acquisition creates
        NO file_observations row, mutates NO observation, and
        changes NO identity/currentness semantics. Persisting
        acquired hashes would require a future Architect-approved
        evidence mechanism.
        """

        return (
            self.organisation_intelligence_service
            .acquire_content_hashes(
                media_ids=media_ids
            )
        )

    # ---------------------------------------------------------
    # human decisions
    # ---------------------------------------------------------

    def accept_selected(
        self,
        proposal_ids,
        accepted_by: str = "human",
    ):
        """
        Record the durable acceptance of selected PROPOSED
        organisation proposals.

        Acceptance records approved INTENT only. It never moves,
        renames, or touches any file: NAMOA performs no
        filesystem operation in Sprint 13. Per-item results keep
        one refusal from affecting other selections.
        """

        accepted = []

        refused = []

        for proposal_id in proposal_ids:

            try:

                record = (
                    self.organisation_records.transition(
                        proposal_id,
                        new_state="accepted",
                        expected_current=("proposed",),
                        actor=accepted_by,
                        detail="accepted via organisation "
                        "workflow",
                    )
                )

            except ValueError as error:

                refused.append(
                    {
                        "proposal_id": proposal_id,
                        "reason": str(error),
                    }
                )

                continue

            accepted.append(
                {
                    "proposal_id": proposal_id,
                    "media_id": record.media_id,
                    "intent": record.intent,
                }
            )

            self._notify(
                "success",
                "Organisation improvement accepted",
                f"{record.intent} for media {record.media_id} · "
                "recorded as approved intent; no files were changed.",
                media_id=record.media_id,
            )

        return {
            "accepted": accepted,
            "refused": refused,
        }

    def reject_proposal(
        self,
        proposal_id: int,
        *,
        rejected_by: str = "human",
        reason: str | None = None,
    ):
        """
        Record a durable rejection of one proposed organisation
        proposal. Never deletes or rewrites it.
        """

        return self.organisation_records.transition(
            proposal_id,
            new_state="rejected",
            expected_current=("proposed",),
            actor=rejected_by,
            detail=reason,
        )

    # ---------------------------------------------------------
    # Sprint 15: profiles
    # ---------------------------------------------------------

    def _validated_payload(self, payload: dict) -> dict:
        """
        Shared validation for profile create/update:
        alias fill, structural validation, then the
        two environment requirements (a source to
        inspect, a destination to organise into).
        Returns the storable payload or raises
        ValueError with human-readable guidance.
        """

        from app.organisation.profiles import (
            fill_root_aliases,
            validate_profile,
        )

        payload = fill_root_aliases(dict(payload or {}))

        problems = validate_profile(payload)

        if problems:
            raise ValueError(
                "invalid organisation profile: "
                + "; ".join(problems)
            )

        categories = payload.get("categories") or {}

        for index, rule in enumerate(
            payload.get("organisation_rules") or []
        ):
            target = (
                rule.get("category")
                if isinstance(rule, dict)
                else ""
            )

            if target not in categories:
                raise ValueError(
                    f"Organisation rule {index + 1} "
                    f"references a category that no "
                    f"longer exists. Choose a category "
                    f"from the list above."
                )

        if not [
            source
            for source in (payload.get("sources") or [])
            if isinstance(source, str) and source.strip()
        ]:
            raise ValueError(
                "Library source required. Choose where "
                "NAMOA is allowed to look for media."
            )

        if not [
            root
            for root in (payload.get("roots") or [])
            if (
                root.get("path")
                if isinstance(root, dict)
                else root
            )
        ]:
            raise ValueError(
                "Organisation destination required. "
                "Choose where NAMOA should place organised "
                "media."
            )

        return payload

    def create_profile(self, payload: dict) -> dict:
        """
        Store one new organisation profile. Names are
        unique; duplicates are refused plainly.
        Commits. Returns the saved record view.
        """

        from app.organisation.profiles import (
            profile_digest,
        )

        payload = self._validated_payload(payload)

        profile_id = self.organisation_records.create_profile(
            name=str(payload.get("name")).strip(),
            payload=payload,
            digest=profile_digest(payload),
        )

        self.organisation_records.connection.commit()

        record = self.organisation_records.get_profile(
            profile_id
        )

        return {
            "id": record.id,
            "name": record.name,
            "digest": record.digest,
        }

    def save_profile(self, payload: dict) -> dict:
        """
        Backwards-compatible create path retained for
        existing callers (tests, compat routes):
        storing a new profile. Prefer
        create_profile for new code.
        """

        return self.create_profile(payload)

    def update_profile(
        self, profile_id: int, payload: dict
    ) -> dict:
        """
        Update one stored profile in place, including
        an optional rename (still unique). The profile
        keeps its identity; no new profile or version
        is created. Commits. Returns the record view.
        """

        from app.organisation.profiles import (
            profile_digest,
        )

        payload = self._validated_payload(payload)

        self.organisation_records.update_profile(
            int(profile_id),
            name=str(payload.get("name")).strip(),
            payload=payload,
            digest=profile_digest(payload),
        )

        self.organisation_records.connection.commit()

        record = self.organisation_records.get_profile(
            int(profile_id)
        )

        return {
            "id": record.id,
            "name": record.name,
            "digest": record.digest,
        }

    def get_profile(self, profile_id: int) -> dict:
        """
        One organisation profile with its full payload.
        Raises ValueError when it does not exist.
        """

        record = self.organisation_records.get_profile(
            int(profile_id)
        )

        if record is None:
            raise ValueError(
                f"organisation profile {profile_id} not found"
            )

        return {
            "id": record.id,
            "name": record.name,
            "digest": record.digest,
            "payload": dict(record.payload or {}),
            "created_at": record.created_at,
        }

    def list_profiles(self) -> list:
        return [
            {
                "id": record.id,
                "name": record.name,
                "digest": record.digest,
                "created_at": record.created_at,
            }
            for record in (
                self.organisation_records.list_profiles()
            )
        ]

    def builtin_templates(self) -> dict:
        from app.organisation.profiles import (
            builtin_templates,
        )

        return builtin_templates()

    def list_profile_presets(self) -> list:
        """
        Catalogue (key, name, description) of the
        built-in profile presets. Payloads stay behind
        get_profile_preset; the catalogue itself carries
        no configuration.
        """

        from app.organisation.profiles import (
            builtin_profile_presets,
        )

        return [
            {
                "key": preset.get("key"),
                "name": preset.get("name"),
                "description": preset.get("description"),
            }
            for preset in builtin_profile_presets()
        ]

    def get_profile_preset(self, key: str) -> dict | None:
        """
        One full preset (including its payload) by key,
        or None when unknown. The returned payload is a
        copy; presets themselves are never mutated.
        """

        from app.organisation.profiles import (
            get_profile_preset,
        )

        return get_profile_preset(key)

    def profile_completion(self, payload: dict) -> dict:
        """
        Guided-completion checklist for a candidate
        profile payload, derived from the real
        validation rules. Read-only.
        """

        from app.organisation.profiles import (
            profile_completion,
        )

        return profile_completion(payload)

    def normalise_filename_policy(self, value) -> dict:
        """
        Normalised filename policy through the
        application boundary (the web layer never
        imports the organisation domain directly).
        """

        from app.organisation.profiles import (
            normalise_filename_policy,
        )

        return normalise_filename_policy(value)

    def render_filename_example(
        self, pattern=None, separator=None
    ) -> dict:
        """
        Deterministic live example for the File
        Naming editor: the documented sample source
        (Show.Name.S03E07.1080p.WEB-DL.x265-GROUP.mkv)
        rendered through the real extended-naming
        renderer. Read-only.
        """

        from app.organisation.file_evidence import (
            extract_file_evidence,
        )
        from app.organisation.planning import (
            _render_extended_suffix,
        )

        source = "Show.Name.S03E07.1080p.WEB-DL.x265-GROUP.mkv"
        base = "Show Name S03E07"
        media_fields = {
            "title": "Show Name S03E07",
            "year": "",
            "series": "Show Name",
            "season": "3",
            "episode": "7",
            "episode_title": "",
        }
        file_fields = extract_file_evidence(source)

        if not (pattern or "").strip():
            return {
                "source": source,
                "base": base,
                "file_evidence": file_fields,
                "result": "",
                "missing": [],
                "error": None,
            }

        suffix, missing, error = _render_extended_suffix(
            pattern, media_fields, file_fields
        )

        if error is not None:
            return {
                "source": source,
                "base": base,
                "file_evidence": file_fields,
                "result": "",
                "missing": missing,
                "error": error,
            }

        stem = (
            f"{base}{separator or ' '}{suffix}".strip()
            if suffix
            else base
        )

        return {
            "source": source,
            "base": base,
            "file_evidence": file_fields,
            "result": f"{stem}.mkv",
            "missing": missing,
            "error": None,
        }

    def suggest_profile_name(self, base: str) -> str:
        """
        A free profile name derived from base
        ("X (copy)", then "X (copy 2)", ...).
        Read-only; used to prefill clone forms.
        """

        base = str(base or "Profile").strip() or "Profile"
        taken = {
            str(record.get("name") or "")
            for record in self.list_profiles()
        }

        candidate = f"{base} (copy)"

        if candidate not in taken:
            return candidate

        index = 2

        while f"{base} (copy {index})" in taken:
            index += 1

        return f"{base} (copy {index})"

    def delete_profile(self, profile_id: int) -> dict:
        """
        Delete exactly one stored user profile by id.
        Names are unique and preset origin is
        provenance only, so no other profile can be
        affected. Built-in preset definitions are
        never stored rows and cannot be reached here.
        Commits.
        """

        name = self.organisation_records.delete_profile(
            int(profile_id)
        )

        if name is None:
            raise ValueError(
                f"organisation profile {profile_id} not found"
            )

        self.organisation_records.connection.commit()

        return {"name": name, "removed_profiles": 1}

    def recommend_tag_mappings(
        self, payload: dict | None, *, limit: int = 20
    ) -> dict:
        """
        Recommend tag mappings from real observed data.
        Collects provider tag labels from persisted
        metadata observations (all lineages) plus the
        live tag maps of configured providers, then
        suggests single-label mappings not already
        covered by the profile. A label matching an
        existing category (case-insensitive) targets
        it; otherwise the label itself is suggested as
        a new category for operator review. Optional:
        standard presets already work without it.
        Read-only; nothing persisted.
        """

        payload = dict(payload or {})

        existing = set()
        categories = {
            str(name)
            for name in (payload.get("categories") or {})
        }
        categories_folded = {
            name.casefold(): name for name in categories
        }

        for mapping in payload.get("tag_mappings") or []:
            if not isinstance(mapping, dict):
                continue

            provider = str(
                mapping.get("provider") or "*"
            ).casefold()
            labels = tuple(
                sorted(
                    str(label).strip().casefold()
                    for label in (
                        mapping.get("labels") or []
                    )
                    if str(label).strip()
                )
            )

            if labels:
                existing.add((provider, labels))

        observed: dict = {}

        try:
            records = (
                self.organisation_records
                .recent_metadata_observations(limit=2000)
            )
        except Exception:
            records = []

        for record in records or []:
            relevant = getattr(record, "payload", None) or {}
            provider = str(
                getattr(record, "provider", "") or ""
            )

            if not provider:
                continue

            tags = relevant.get("tags") or []

            for tag in tags:
                label = str(tag or "").strip()

                if label:
                    observed.setdefault(
                        (provider.casefold(), label), set()
                    ).add(label)

        live: dict = {}

        if self.integration_service is not None:
            for provider in ("jellyfin", "radarr", "sonarr"):
                try:
                    labels = (
                        self.integration_service
                        .provider_tag_labels(provider)
                    )
                except Exception:
                    continue

                if isinstance(labels, dict):
                    for _tag_id, label in labels.items():
                        text = str(label or "").strip()

                        if text:
                            live.setdefault(
                                (provider, text), set()
                            ).add(text)

        suggestions = []
        seen = set()

        for source in (observed, live):
            for (provider, _label), texts in source.items():
                label = sorted(texts)[0]
                folded = label.casefold()
                key = (provider, (folded,))

                if key in existing or key in seen:
                    continue

                seen.add(key)

                if folded in categories_folded:
                    category = categories_folded[folded]
                    new_category = False
                    reason = (
                        f"observed '{label}' matches the "
                        f"existing '{category}' category"
                    )
                else:
                    category = label
                    new_category = True
                    reason = (
                        f"observed '{label}' has no "
                        f"category yet; review before "
                        f"saving"
                    )

                suggestions.append(
                    {
                        "provider": (
                            None
                            if provider == "*"
                            else provider
                        ),
                        "labels": [label],
                        "category": category,
                        "priority": 100,
                        "reason": reason,
                        "new_category": new_category,
                    }
                )

                if len(suggestions) >= limit:
                    break

            if len(suggestions) >= limit:
                break

        suggestions.sort(
            key=lambda item: (
                str(item["category"]),
                str(item["provider"] or ""),
                str(item["labels"]),
            )
        )

        return {
            "suggestions": suggestions[:limit],
            "truncated": len(suggestions) >= limit,
        }

    def normalise_provider_priority(self, raw) -> list | None:
        """
        Normalised provider priority order from the
        Advanced editor field (blank means the default
        Radarr > Sonarr > Jellyfin). Application-
        boundary helper so the web layer never imports
        the profiles domain directly. Raises
        ValueError with guidance on invalid input.
        """

        from app.organisation.profiles import (
            normalise_provider_priority,
        )

        text = str(raw or "").strip()

        if not text:
            return None

        return normalise_provider_priority(text)

    def profile_root_rows(self, roots) -> dict:
        """
        Editor/display rows and tokens for profile
        library roots: {rows: [{path, alias}], tokens:
        ["{root}", ...]} in order. Pure presentation
        helper so the web layer stays on the
        application boundary; never plans or persists.
        """

        from app.organisation.profiles import (
            assign_root_aliases,
            display_root_rows,
        )

        shown = display_root_rows(roots)

        tokens = [
            "{" + alias + "}"
            for _, alias in assign_root_aliases(roots)[0]
        ]

        return {"rows": shown, "tokens": tokens}

    def render_preview(
        self,
        template: dict,
        values: dict,
        *,
        root: str = "",
    ) -> dict:
        """
        Render one template pattern over sample values
        for the visual structure preview. Pure
        presentation helper; never plans or persists.
        """

        from app.organisation.profiles import (
            render_template,
        )

        destination, error = render_template(
            dict(template or {}),
            root=root or "",
            values=dict(values or {}),
        )

        return {
            "destination": destination,
            "error": error,
        }

    def _resolve_profile(
        self,
        profile=None,
    ) -> tuple:
        """
        Resolve a profile reference (id, payload dict, or
        None for an ad-hoc default) to
        (profile_id|None, payload dict, digest|None).
        """

        from app.organisation.profiles import (
            default_profile_payload,
            profile_digest,
            validate_profile,
        )

        if profile is None:
            payload = default_profile_payload()
            return None, payload, profile_digest(payload)

        if isinstance(profile, int):
            record = self.organisation_records.get_profile(
                profile
            )

            if record is None:
                raise ValueError(
                    f"organisation profile {profile} "
                    f"not found"
                )

            return (
                record.id,
                dict(record.payload or {}),
                record.digest,
            )

        if isinstance(profile, dict):
            payload = dict(profile)

            problems = validate_profile(payload)

            if problems:
                raise ValueError(
                    "invalid organisation profile: "
                    + "; ".join(problems)
                )

            return None, payload, profile_digest(payload)

        raise ValueError(
            "profile must be an id, a payload dict, or None"
        )

    # ---------------------------------------------------------
    # Sprint 15: planning (What-If, sampler, preflight)
    # ---------------------------------------------------------

    def _planner(self, live_fetcher=None):
        from app.organisation.planning import (
            OrganisationPlanner,
        )

        if self.media_repository is None:
            raise ValueError(
                "organisation planning requires a media "
                "repository; service is not wired for "
                "Sprint 15 planning"
            )

        return OrganisationPlanner(
            media_repository=self.media_repository,
            organisation_repository=self.organisation_records,
            metadata_fetcher=live_fetcher,
        )

    def _live_fetcher(self):
        """
        Build a fetcher closure over enabled providers for
        live metadata scope. Fetches each provider library
        once, matches items to NAMOA lineages by canonical
        path, and returns in-memory snapshot payloads
        (no observation ids, no persistence here).
        """

        if self.integration_service is None:
            return None

        cache = {}

        def fetch(media_id):
            lineage = self.media_repository.get_media_item(
                media_id
            )

            if lineage is None:
                return []

            snapshots = []

            for view in (
                self.integration_service.list_providers()
            ):
                provider = view["provider"]

                if not view["enabled"]:
                    continue

                if provider not in cache:
                    try:
                        cache[provider] = (
                            self.integration_service
                            .fetch_library_for_planning(
                                provider
                            )
                        )
                    except Exception as error:
                        cache[provider] = {
                            "error": (
                                f"{type(error).__name__}: "
                                f"{error}"
                            )
                        }

                library = cache[provider]

                if isinstance(library, dict):
                    continue

                for relevant in library:
                    path = (relevant.get("path") or "").strip()

                    if not path:
                        continue

                    from app.organisation.planning import (
                        canonical_path_key,
                    )

                    try:
                        match = canonical_path_key(
                            path
                        ) == canonical_path_key(
                            lineage.file_path or ""
                        ) and canonical_path_key(path) is not None
                    except (OSError, ValueError):
                        match = False

                    if not match:
                        continue

                    snapshots.append(
                        {
                            "provider": provider,
                            "provider_item_id": str(
                                relevant.get(
                                    "provider_item_id"
                                ) or ""
                            ),
                            "provider_item_kind": (
                                relevant.get("kind")
                                or "file"
                            ),
                            "relevant": dict(relevant),
                        }
                    )

            return snapshots

        return fetch

    def _apply_filename_mode(
        self, payload, filename_mode, filename_policy=None
    ):
        """
        Effective profile payload for one run. None/""
        keeps the profile's own filename policy; an
        explicit filename_policy dict replaces it
        wholesale for this preview after validation;
        otherwise keep/clean/extended/template select
        the behaviour (template falls back to the
        profile's stored custom pattern). Only the
        filename behaviour is overridden for the
        preview (folders, classification, and
        destinations are untouched). The effective
        mode is reported alongside the plan so
        What-If and reconciliation state it clearly.
        """

        from app.organisation.profiles import (
            FILENAME_CLEAN,
            FILENAME_EXTENDED,
            FILENAME_KEEP,
            FILENAME_TEMPLATE,
            normalise_filename_policy,
        )

        payload = dict(payload or {})

        if filename_policy is not None:
            policy = normalise_filename_policy(
                dict(filename_policy)
            )
            payload["filename_policy"] = policy
            return payload, policy["mode"], True

        if filename_mode in (None, ""):
            policy = payload.get("filename_policy") or {
                "mode": FILENAME_KEEP
            }
            return payload, policy.get("mode", FILENAME_KEEP), False

        wanted = str(filename_mode).strip().casefold()
        names = {
            "folders": FILENAME_KEEP,
            "keep": FILENAME_KEEP,
            "clean": FILENAME_CLEAN,
            "extended": FILENAME_EXTENDED,
            "template": FILENAME_TEMPLATE,
        }

        if wanted not in names:
            raise ValueError(
                "unknown run mode "
                f"'{filename_mode}' (expected folders, "
                "clean, extended, or template)"
            )

        mode = names[wanted]
        policy = dict(payload.get("filename_policy") or {})

        if mode == FILENAME_EXTENDED and not (
            policy.get("mode") == FILENAME_EXTENDED
            and (policy.get("pattern") or "").strip()
        ):
            raise ValueError(
                "extended run mode needs an extended "
                "naming pattern: configure one for this "
                "run or on the profile"
            )

        if mode == FILENAME_TEMPLATE and not (
            policy.get("mode") == FILENAME_TEMPLATE
            and (policy.get("pattern") or "").strip()
        ):
            raise ValueError(
                "template run mode needs a custom "
                "filename pattern: configure one for "
                "this run or on the profile"
            )

        policy["mode"] = mode
        payload["filename_policy"] = normalise_filename_policy(
            policy
        )

        return payload, mode, True

    def identify_and_plan(
        self,
        path: str,
        *,
        profile=None,
        preferences=None,
        providers=None,
        filename_mode=None,
        filename_policy=None,
    ) -> dict:
        """
        New/unseen media flow (§2): discover (stat),
        analyse (filename candidate), provider API
        lookup, conservative association, merged
        metadata, organisation planning, and What-If
        presentation, all without requiring a stored
        lineage. Read-only:
        no lineage, observation, or metadata row is
        created; provider lookups are GET requests
        only. Returns the plan plus the
        identification block (candidate, lookups,
        corroboration or review reason).
        """

        from app.application.filesystem_service import (
            scan_file_record,
        )

        scan = scan_file_record(path)

        _profile_id, payload, _digest = self._resolve_profile(
            profile
        )
        payload, effective_mode, overridden = (
            self._apply_filename_mode(
                payload, filename_mode, filename_policy
            )
        )

        identification = self.integration_service.identify_media(
            path=str(scan.get("path") or path),
            providers=providers,
        )

        plan = self._planner(None).plan_ephemeral(
            scan,
            profile=payload,
            preferences=preferences,
            snapshots=identification.get("snapshots") or [],
        )

        result = plan.to_dict()
        result["ephemeral"] = True
        result["identification"] = {
            "candidate": identification.get("candidate"),
            "lookups": identification.get("lookups"),
            "ranked": identification.get("ranked"),
            "conflicts": identification.get("conflicts"),
            "snapshots": identification.get("snapshots") or [],
            "outcome": identification.get("outcome"),
            "reason": identification.get("reason"),
        }
        result["filename_mode"] = effective_mode
        result["filename_mode_override"] = overridden

        if identification.get("outcome") == "conflict":
            # Competing provider works for one file:
            # the calculated destination stays visible
            # as the candidate, but the plan is review,
            # never a silent baseline association.
            result["review_state"] = "conflict"
            result["mutation"] = {
                "strategy": "requires review",
                "operation_count": 0,
            }
            result["reasoning"] = list(
                result.get("reasoning") or []
            ) + [identification.get("reason") or ""]

        return result

    def plan_ephemeral_file(
        self,
        path: str,
        *,
        profile=None,
        preferences=None,
        snapshots: list | None = None,
        filename_mode=None,
        filename_policy=None,
    ) -> dict:
        """
        Read-only What-If for a file NAMOA may never
        have seen (a USB import, a new download). Stats
        the file and plans through the shared planning
        semantics without creating any lineage,
        observation, or other persisted row: What-If
        never mutates anything.
        """

        from app.application.filesystem_service import (
            scan_file_record,
        )

        scan = scan_file_record(path)

        _profile_id, payload, _digest = self._resolve_profile(
            profile
        )
        payload, effective_mode, overridden = (
            self._apply_filename_mode(
                payload, filename_mode, filename_policy
            )
        )

        plan = self._planner(None).plan_ephemeral(
            scan,
            profile=payload,
            preferences=preferences,
            snapshots=snapshots,
        )

        result = plan.to_dict()
        result["ephemeral"] = True
        result["filename_mode"] = effective_mode
        result["filename_mode_override"] = overridden

        return result

    def plan_file(
        self,
        media_id: int,
        *,
        profile=None,
        preferences=None,
        metadata_scope="cached",
        filename_mode=None,
        filename_policy=None,
    ) -> dict:
        """
        Single-file What-If over the shared planning
        semantics. No persistence, no mutation.
        `filename_mode` optionally overrides the run
        intent for this preview (folders/keep,
        clean, extended); the effective mode is
        reported on the result.
        """

        _profile_id, payload, _digest = self._resolve_profile(
            profile
        )
        payload, effective_mode, overridden = (
            self._apply_filename_mode(
                payload, filename_mode, filename_policy
            )
        )

        fetcher = (
            self._live_fetcher()
            if metadata_scope == "live"
            else None
        )

        plan = self._planner(fetcher).plan_file(
            int(media_id),
            profile=payload,
            preferences=preferences,
            metadata_scope=metadata_scope,
        )

        result = plan.to_dict()
        result["filename_mode"] = effective_mode
        result["filename_mode_override"] = overridden

        return result

    def plan_scope(
        self,
        scope,
        *,
        profile=None,
        preferences=None,
        metadata_scope="cached",
    ) -> dict:
        """
        Scope planning over the shared planning semantics.
        No persistence, no mutation.
        """

        _profile_id, payload, _digest = self._resolve_profile(
            profile
        )

        fetcher = (
            self._live_fetcher()
            if metadata_scope == "live"
            else None
        )

        plan = self._planner(fetcher).plan_scope(
            scope,
            profile=payload,
            preferences=preferences,
            metadata_scope=metadata_scope,
        )

        return plan.to_dict()

    def sample_what_if(
        self,
        directory: str,
        *,
        limit: int = 10,
        seed=None,
        profile=None,
        preferences=None,
        metadata_scope="cached",
    ) -> dict:
        """
        Random directory sampler: up to `limit` eligible
        files, each rendered through the shared scope
        planning semantics. "Test Again" is a fresh call
        with a new seed. No persistence, no mutation.
        """

        _profile_id, payload, _digest = self._resolve_profile(
            profile
        )

        planner = self._planner(
            self._live_fetcher()
            if metadata_scope == "live"
            else None
        )

        sample = planner.sample_directory(
            directory,
            limit=limit,
            seed=seed,
        )

        if sample.get("error") is not None:
            return {**sample, "rows": []}

        media_ids = self._media_ids_for_paths(
            sample["sampled_paths"]
        )

        scope = planner.plan_scope(
            {
                "path": directory,
                "media_ids": sorted(
                    {
                        media_id
                        for media_id in media_ids.values()
                        if media_id is not None
                    }
                ),
            },
            profile=payload,
            preferences=preferences,
            metadata_scope=metadata_scope,
        ).to_dict()

        rows_by_media = {
            row["media_id"]: row
            for row in scope["file_plans"]
        }

        rows = []

        for path in sample["sampled_paths"]:
            media_id = media_ids.get(path)

            if media_id is None:
                try:
                    from app.application.filesystem_service import (
                        scan_file_record,
                    )

                    limited = self._planner(None).plan_ephemeral(
                        scan_file_record(path),
                        profile=payload,
                        preferences=preferences,
                        snapshots=[],
                    )
                    rows.append(
                        {
                            "path": path,
                            "media_id": None,
                            "plan": limited.to_dict(),
                            "limited": True,
                            "reason": None,
                        }
                    )
                except (OSError, ValueError):
                    rows.append(
                        {
                            "path": path,
                            "media_id": None,
                            "plan": None,
                            "limited": True,
                            "reason": (
                                "file could not be read; "
                                "review required"
                            ),
                        }
                    )
                continue

            rows.append(
                {
                    "path": path,
                    "media_id": media_id,
                    "plan": rows_by_media.get(media_id),
                    "reason": None,
                }
            )

        return {
            "seed": sample["seed"],
            "directory": directory,
            "eligible_count": sample["eligible_count"],
            "strategy": scope["strategy"],
            "operation_count": scope["operation_count"],
            "scope_reasoning": scope["reasoning"],
            "structural_actions": scope[
                "structural_actions"
            ],
            "review_conditions": scope["review_conditions"],
            "rows": rows,
            "error": None,
        }

    def _media_ids_for_paths(self, paths: list) -> dict:
        from app.organisation.planning import (
            canonical_path_key,
            index_lineages_by_path,
        )

        try:
            lineages = (
                self.media_repository.get_active_lineages()
            )
        except Exception:
            return {}

        index = index_lineages_by_path(lineages)

        resolved = {}

        for path in paths or []:
            resolved[path] = index.get(
                canonical_path_key(path)
            )

        return resolved

    def preflight(
        self,
        profile=None,
        *,
        roots: list | None = None,
        provider_paths: list | None = None,
    ) -> dict:
        """
        Advisory Organisation Preflight over the
        configured setup. Read-only; creates no probe
        artifacts. Invalid configuration is reported,
        never raised: preflight exists to surface
        problems. Execution-time validation remains
        authoritative.
        """

        try:
            _profile_id, payload, _digest = (
                self._resolve_profile(profile)
            )
        except ValueError as error:
            return {
                "ok": False,
                "checks": [
                    {
                        "name": "profile configuration valid",
                        "ok": False,
                        "level": "error",
                        "message": str(error),
                    }
                ],
            }

        if provider_paths is None:
            provider_paths = []

            try:
                recent = (
                    self.organisation_records
                    .recent_metadata_observations(limit=500)
                )
            except Exception:
                recent = []

            for record in recent:
                for key in (
                    "root_folder_path",
                    "provider_path",
                    "series_path",
                ):
                    value = (record.payload or {}).get(key)

                    if value:
                        provider_paths.append(value)

        return self._planner().preflight(
            payload,
            roots=roots,
            provider_paths=provider_paths,
        )

    # ---------------------------------------------------------
    # Sprint 15: reconciliation persistence
    # ---------------------------------------------------------

    def generate_reconciliation(
        self,
        *,
        profile=None,
        preferences=None,
        metadata_scope="cached",
        scope=None,
    ) -> dict:
        """
        Plan a scope (or the whole active library when
        scope is None) and persist the decision run,
        per-file proposals, and scope actions atomically.
        Only actionable plans persist; review-only
        outcomes stay in the preview. Supersedes older
        proposed rows for covered lineages. Returns an
        honest summary.
        """

        from app.organisation.policy import (
            OrganisationPolicy,
            organisation_identity_digest,
            rule_manifest,
        )
        from app.organisation.preferences import (
            resolve_effective_policy,
        )
        from app.versioning.registry import get_git_revision

        profile_id, payload, digest = self._resolve_profile(
            profile
        )

        fetcher = (
            self._live_fetcher()
            if metadata_scope == "live"
            else None
        )

        planner = self._planner(fetcher)

        effective_scope = scope

        if effective_scope is None:
            effective_scope = {
                "path": "",
                "media_ids": [
                    lineage.id
                    for lineage in (
                        self.media_repository
                        .get_active_lineages()
                    )
                ],
            }

        plan = planner.plan_scope(
            effective_scope,
            profile=payload,
            preferences=preferences,
            metadata_scope=metadata_scope,
        )

        from app.organisation.paths import root_path_list

        # The authorised boundary covers destination
        # roots AND declared source locations: a source
        # may live on another filesystem (a USB stick),
        # and the operator explicitly granted NAMOA
        # access by listing it in the profile. Both
        # lists are user-explicit; nothing is inferred.
        boundary_roots = root_path_list(
            payload.get("roots")
        ) + [
            source
            for source in (payload.get("sources") or [])
            if isinstance(source, str) and source.strip()
        ]

        base_policy = OrganisationPolicy(
            library_roots=tuple(boundary_roots)
        )

        effective_policy = resolve_effective_policy(
            base_policy, preferences
        )

        rule_versions = rule_manifest(
            effective_policy.enabled_rules
        )

        policy_values = effective_policy.policy_values()

        if preferences is not None:
            policy_values = {
                **policy_values,
                "preferences": (
                    preferences.to_preference_payload()
                ),
            }

        policy_values = {
            **policy_values,
            "profile": {
                "id": profile_id,
                "digest": digest,
            },
        }

        fingerprints = sorted(
            {
                plan.metadata_cited.get("fingerprint")
                for plan in plan.file_plans
                if plan.metadata_cited.get("fingerprint")
            }
        )

        metadata_rollup = (
            self.organisation_records.metadata_fingerprint(
                {"cited": fingerprints}
            )
            if fingerprints
            else None
        )

        policy_values = {
            **policy_values,
            "metadata_fingerprint": metadata_rollup,
        }

        identity_digest = organisation_identity_digest(
            rule_versions,
            policy_values,
        )

        connection = self.organisation_records.connection

        try:
            decision_run_id = (
                self.organisation_records.create_decision_run(
                    library_roots=list(
                        effective_policy.library_roots
                    ),
                    rule_versions=rule_versions,
                    policy_values=policy_values,
                    git_revision=get_git_revision(),
                    identity_digest=identity_digest,
                    lineages_considered=len(plan.file_plans),
                    proposals_created=0,
                    hash_coverage_total=0,
                    hash_coverage_hashed=0,
                    profile_id=profile_id,
                    profile_digest=digest,
                    metadata_fingerprint=metadata_rollup,
                    mutation_strategy=plan.strategy,
                    operation_count=plan.operation_count,
                    strategy_reasoning=list(plan.reasoning),
                )
            )

            proposal_ids = []
            proposal_by_media = {}
            covered_media = set()

            actionable = [
                plan
                for plan in plan.file_plans
                if plan.review_state == "ready"
                and plan.mutation.get("strategy", "")
                in ("move file", "rename file")
            ]

            for file_plan in actionable:
                strategy = file_plan.mutation.get(
                    "strategy", ""
                )

                if strategy == "move file":
                    intent = "move_destination"
                    destination = (
                        file_plan.expected_destination
                    )
                    name = None
                else:
                    intent = "rename"
                    destination = None

                    from pathlib import Path as _Path

                    name = _Path(
                        file_plan.expected_destination or ""
                    ).name or None

                rationale = [
                    f"rule:{rule}"
                    for rule in file_plan.rules_applied
                ] + list(file_plan.reasoning)

                for mapping in file_plan.mappings_applied:
                    rationale.append(f"tagmap:{mapping}")

                evidence = {
                    "observation_id": (
                        file_plan.source_observation_id
                    ),
                    "current_path": file_plan.current_path,
                    "classification": (
                        file_plan.classification
                    ),
                    "category": file_plan.category,
                    "matched_rule": (
                        file_plan.matched_rule
                        if isinstance(
                            file_plan.matched_rule, dict
                        )
                        else None
                    ),
                    "provider_review": bool(
                        file_plan.provider_review
                    ),
                    "association": dict(
                        file_plan.association or {}
                    ),
                    "mutation_strategy": strategy,
                    "metadata_citations": [
                        {
                            "observation_id": observation_id,
                            "fingerprint": (
                                file_plan.metadata_cited.get(
                                    "fingerprint"
                                )
                            ),
                        }
                        for observation_id in (
                            file_plan.metadata_cited.get(
                                "observation_ids", []
                            )
                        )
                    ],
                }

                proposal_ids.append(
                    self.organisation_records.create_proposed(
                        decision_run_id=decision_run_id,
                        media_id=file_plan.media_id,
                        intent=intent,
                        related_media_id=None,
                        proposed_destination=destination,
                        proposed_name=name,
                        confidence=file_plan.confidence,
                        risk="low",
                        rationale=rationale,
                        evidence=evidence,
                        intelligence_identity=(
                            identity_digest
                        ),
                    )
                )

                proposal_by_media[file_plan.media_id] = (
                    proposal_ids[-1]
                )

                covered_media.add(file_plan.media_id)

            scope_action_ids = []

            for structural in plan.structural_actions:
                descendant_proposals = [
                    proposal_by_media[media_id]
                    for media_id in (
                        structural.descendant_media_ids
                    )
                    if media_id in proposal_by_media
                ]

                scope_action_ids.append(
                    self.organisation_records
                    .create_scope_action(
                        decision_run_id=decision_run_id,
                        scope_path=structural.source_path,
                        action_type=(
                            structural.action_type
                        ),
                        source_path=structural.source_path,
                        destination_path=(
                            structural.destination_path
                        ),
                        descendant_manifest=[
                            dict(item)
                            for item in (
                                structural.descendants
                            )
                        ],
                        strategy=structural.strategy,
                        operation_count=(
                            structural.operation_count
                        ),
                        reasoning=list(
                            structural.reasoning
                        ),
                        review_conditions=list(
                            structural.review_conditions
                        ),
                        descendant_proposal_ids=(
                            descendant_proposals
                        ),
                        intelligence_identity=(
                            identity_digest
                        ),
                    )
                )

                covered_media.update(
                    structural.descendant_media_ids
                )

            stale_proposals = [
                record.id
                for record in (
                    self.organisation_records
                    .list_by_states(("proposed",))
                )
                if record.decision_run_id < decision_run_id
                and record.media_id in covered_media
            ]

            superseded_proposals = (
                self.organisation_records.supersede_proposals(
                    stale_proposals,
                    new_decision_run_id=decision_run_id,
                )
            )

            stale_scopes = [
                record.id
                for record in (
                    self.organisation_records
                    .list_scope_actions_by_states(
                        ("proposed",)
                    )
                )
                if record.decision_run_id < decision_run_id
            ]

            superseded_scopes = (
                self.organisation_records
                .supersede_scope_actions(
                    stale_scopes,
                    new_decision_run_id=decision_run_id,
                )
            )

            cursor = connection.cursor()

            cursor.execute(
                """
                UPDATE organisation_decision_runs
                SET proposals_created = ?
                WHERE id = ?
                """,
                (len(proposal_ids), decision_run_id),
            )

            connection.commit()

        except Exception:
            connection.rollback()
            raise

        self._notify(
            "information",
            "Reconciliation planned",
            f"decision run {decision_run_id} · "
            f"{len(proposal_ids)} proposals · "
            f"{len(scope_action_ids)} scope actions · "
            f"strategy: {plan.strategy}",
        )

        return {
            "decision_run_id": decision_run_id,
            "identity_digest": identity_digest,
            "strategy": plan.strategy,
            "operation_count": plan.operation_count,
            "proposal_ids": proposal_ids,
            "scope_action_ids": scope_action_ids,
            "superseded_proposals": superseded_proposals,
            "superseded_scope_actions": superseded_scopes,
            "review_conditions": list(
                plan.to_dict()["review_conditions"]
            ),
        }

    # ---------------------------------------------------------
    # Sprint 15: scope action acceptance
    # ---------------------------------------------------------

    def accept_scope_action(
        self,
        scope_action_id: int,
        accepted_by: str = "human",
    ) -> dict:
        """
        Approve one scope action and atomically accept
        its covered descendant proposals. Returns the
        accepted scope action view.
        """

        record = (
            self.organisation_records.accept_scope_action(
                int(scope_action_id),
                actor=accepted_by,
            )
        )

        self._notify(
            "success",
            "Organisation scope action accepted",
            f"{record.action_type} "
            f"{record.source_path} -> "
            f"{record.destination_path} · recorded as "
            f"approved intent; no files were changed.",
        )

        return {
            "id": record.id,
            "action_type": record.action_type,
            "state": record.state,
            "descendant_proposal_ids": list(
                record.descendant_proposal_ids or []
            ),
        }

    def reject_scope_action(
        self,
        scope_action_id: int,
        *,
        rejected_by: str = "human",
        reason: str | None = None,
    ) -> dict:
        record = (
            self.organisation_records.transition_scope_action(
                int(scope_action_id),
                new_state="rejected",
                expected_current=("proposed",),
                actor=rejected_by,
                detail=reason,
            )
        )

        return {
            "id": record.id,
            "action_type": record.action_type,
            "state": record.state,
        }

    def get_scope_action(self, scope_action_id: int) -> dict:
        record = (
            self.organisation_records.get_scope_action(
                int(scope_action_id)
            )
        )

        if record is None:
            raise ValueError(
                f"organisation scope action "
                f"{scope_action_id} not found"
            )

        return {
            "action": record,
            "events": (
                self.organisation_records.scope_events_for(
                    record.id
                )
            ),
        }

    def list_scope_actions(self, decision_run_id=None) -> list:
        if decision_run_id is None:
            current = self.get_current_proposals()

            if current is None:
                return []

            decision_run_id = current[
                "decision_run"
            ].id

        return (
            self.organisation_records
            .list_scope_actions_by_run(int(decision_run_id))
        )
