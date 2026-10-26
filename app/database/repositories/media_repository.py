import json
import os

from pathlib import Path

from typing import Iterable, Tuple

from app.models.media_context import MediaContext
from app.models.file_observation import FileObservation
from app.models.observation_history import MediaLineage
from app.database.repositories.scan_status import ScanStatus


# Canonical representation of an unavailable/unknown filesystem
# modification timestamp.
#
# file_observations.file_mtime_ns is INTEGER NOT NULL, so an unknown
# mtime can never be persisted as NULL. 0 is therefore the single
# sentinel for "unknown mtime" at this boundary, and it is applied
# identically to media_items and file_observations so the persisted
# fingerprint (size_bytes + file_mtime_ns) always compares
# consistently between the two tables.
#
# The scanner contract guarantees an int (stat.st_mtime_ns); files
# whose stat fails are skipped entirely, so this sentinel exists for
# defensive MediaContext construction and legacy rows only.
UNKNOWN_FILE_MTIME_NS = 0


class MediaRepository:
    """
    Persistence boundary for media library ownership and
    filesystem observation lineage.

    Responsibilities:

    - Create media_items records
    - Retrieve existing media_items records
    - Synchronise scanner state with media_items
    - Detect physical file-state changes
    - Record immutable filesystem observations

    File change detection currently uses:

        size_bytes
        file_mtime_ns

    An unknown mtime is persisted as UNKNOWN_FILE_MTIME_NS (0)
    identically on media_items and file_observations; NULL is never
    written to either column by this repository.

    This repository does not:

    - analyse media
    - store analysis results
    - run pipeline logic
    - make analysis decisions
    - manage AnalysisRun lifecycle

    Transaction/commit lifecycle remains owned by the caller.
    """

    def __init__(self, connection):
        self.connection = connection

    def sync_media(
        self,
        context: MediaContext,
    ) -> Tuple[int, ScanStatus, int]:

        cursor = self.connection.cursor()

        # --------------------------------------------------
        # Canonicalise the fingerprint mtime.
        #
        # media_items and file_observations must carry the SAME
        # value for the same scan so the persisted fingerprint
        # compares consistently. An unknown mtime is persisted as
        # UNKNOWN_FILE_MTIME_NS everywhere - never as NULL here
        # and 0 there.
        # --------------------------------------------------

        file_mtime_ns = (
            context.file_mtime_ns
            if context.file_mtime_ns is not None
            else UNKNOWN_FILE_MTIME_NS
        )

        # --------------------------------------------------
        # Locate existing current media item
        # --------------------------------------------------

        cursor.execute(
            """
            SELECT
                id,
                file_size_bytes,
                file_mtime_ns
            FROM media_items
            WHERE file_path = ?
              AND COALESCE(status, 'active') <> 'missing'
            """,
            (
                context.path,
            ),
        )

        row = cursor.fetchone()

        # --------------------------------------------------
        # New media item
        # --------------------------------------------------

        if row is None:

            # --------------------------------------------------
            # Reappearance: a missing lineage at this same path
            # with a matching fingerprint continues instead of
            # forking. Path continuity plus fingerprint match is
            # the existing path_and_fingerprint standard; a
            # fingerprint mismatch falls through to new-lineage
            # creation (replacement), leaving the missing row
            # intact. Unknown mtimes never revive (size alone is
            # too weak to prove continuity).
            # --------------------------------------------------

            revived_id = self._find_reappearance(
                cursor,
                context.path,
                context.size_bytes or 0,
                file_mtime_ns,
            )

            if revived_id is not None:

                cursor.execute(
                    """
                    UPDATE media_items
                    SET
                        status = 'active',
                        file_size_bytes = ?,
                        file_mtime_ns = ?,
                        updated_at = CURRENT_TIMESTAMP,
                        last_scanned_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        context.size_bytes or 0,
                        file_mtime_ns,
                        revived_id,
                    ),
                )

                observation_id = self._create_file_observation(
                    media_id=revived_id,
                    context=context,
                    identity_match_method="reappearance",
                    identity_evidence={
                        "matched_media_id": revived_id,
                        "match_fields": [
                            "file_path",
                            "size_bytes",
                            "file_mtime_ns",
                        ],
                        "previous_status": "missing",
                        "reason": "reappearance",
                    },
                )

                return (
                    revived_id,
                    ScanStatus.REAPPEARED,
                    observation_id,
                )

            cursor.execute(
                """
                INSERT INTO media_items (
                    file_path,
                    file_name,
                    file_size_bytes,
                    file_mtime_ns,
                    media_type,
                    last_scanned_at
                )
                VALUES (?, ?, ?, ?, 'unknown', CURRENT_TIMESTAMP)
                """,
                (
                    context.path,
                    context.name,
                    context.size_bytes or 0,
                    file_mtime_ns,
                ),
            )

            media_id = cursor.lastrowid

            # A new physical object is the first observation
            # associated with this stable media lineage. When its
            # fingerprint matches missing lineages at other paths,
            # record the candidate link explicitly without merging:
            # size+mtime alone cannot prove a cross-path move.
            move_link_evidence = self._find_move_link(
                cursor,
                context.path,
                context.size_bytes or 0,
                file_mtime_ns,
            )

            # A new physical object is the first observation
            # associated with this stable media lineage.
            observation_id = self._create_file_observation(
                media_id=media_id,
                context=context,
                identity_match_method="initial_discovery",
                identity_evidence={
                    "reason": "new_media_item",
                    **move_link_evidence,
                },
            )

            return (
                media_id,
                ScanStatus.NEW,
                observation_id,
            )

        # --------------------------------------------------
        # Existing media item
        # --------------------------------------------------

        media_id = row[0]

        stored_size_bytes = row[1]
        stored_file_mtime_ns = row[2]

        # --------------------------------------------------
        # Determine physical state
        # --------------------------------------------------

        unchanged = (
            stored_size_bytes == context.size_bytes
            and
            stored_file_mtime_ns == file_mtime_ns
        )

        # --------------------------------------------------
        # File unchanged
        # --------------------------------------------------

        if unchanged:

            cursor.execute(
                """
                UPDATE media_items
                SET last_scanned_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    media_id,
                ),
            )

            observation_id = self._create_file_observation(
                media_id=media_id,
                context=context,
                identity_match_method="path_and_fingerprint",
                identity_evidence={
                    "matched_media_id": media_id,
                    "match_fields": [
                        "file_path",
                        "size_bytes",
                        "file_mtime_ns",
                    ],
                },
            )

            return (
                media_id,
                ScanStatus.UNCHANGED,
                observation_id,
            )

        # --------------------------------------------------
        # File changed
        # --------------------------------------------------

        previous_state = {
            "size_bytes": stored_size_bytes,
            "file_mtime_ns": stored_file_mtime_ns,
        }

        cursor.execute(
            """
            UPDATE media_items
            SET
                file_size_bytes = ?,
                file_mtime_ns = ?,
                updated_at = CURRENT_TIMESTAMP,
                last_scanned_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                context.size_bytes,
                file_mtime_ns,
                media_id,
            ),
        )

        observation_id = self._create_file_observation(
            media_id=media_id,
            context=context,
            identity_match_method="path_continuity",
            identity_evidence={
                "matched_media_id": media_id,
                "previous_state": previous_state,
                "current_state": {
                    "size_bytes": context.size_bytes,
                    "file_mtime_ns": file_mtime_ns,
                },
                "reason": "existing_path_changed",
            },
        )

        return (
            media_id,
            ScanStatus.CHANGED,
            observation_id,
        )

    def _create_file_observation(
        self,
        *,
        media_id: int,
        context: MediaContext,
        identity_match_method: str,
        identity_evidence: dict,
    ) -> int:
        """
        Create one immutable filesystem observation.

        The observation records exactly what the scanner knew
        about the filesystem object at this point in time.
        """

        scanner = context.raw_scanner or {}

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO file_observations (
                media_id,
                file_path,
                file_name,
                file_extension,
                size_bytes,
                file_mtime_ns,
                filesystem_device,
                filesystem_inode,
                sha256_hash,
                identity_match_method,
                identity_evidence_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                media_id,
                context.path,
                context.name,
                context.extension,
                context.size_bytes or 0,
                (
                    context.file_mtime_ns
                    if context.file_mtime_ns is not None
                    else UNKNOWN_FILE_MTIME_NS
                ),
                scanner.get("filesystem_device"),
                scanner.get("filesystem_inode"),
                scanner.get("file_hash"),
                identity_match_method,
                json.dumps(
                    identity_evidence
                ),
            ),
        )

        return cursor.lastrowid

    def record_organisation_execution_observation(
        self,
        *,
        media_id: int,
        path: str,
        source_observation_id: int | None,
        execution_id: int | None,
        identity_method: str = (
            'organisation_execution_continuity'
        ),
        authority: str = "organisation_execution",
    ) -> int:
        """
        Record the resulting filesystem observation after an
        authorised organisation execution (Sprint 14).

        This is the explicit execution-authorised identity-continuity
        observation: it attaches the NEW filesystem state at `path` to
        the SAME known media_id, and does NOT invoke normal scanner
        identity matching, filename/path similarity, duplicate
        detection, or hash matching. The identity evidence names the
        authorised organisation execution as the authority for the
        continuity.

        The original observation(s) remain historical and immutable;
        this appends a new observation and updates the lineage's
        current path/fingerprint.

        Transaction/commit lifecycle remains owned by the caller.
        """

        stat = Path(path).stat()

        name = os.path.basename(path)

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO file_observations (
                media_id,
                file_path,
                file_name,
                file_extension,
                size_bytes,
                file_mtime_ns,
                filesystem_device,
                filesystem_inode,
                sha256_hash,
                identity_match_method,
                identity_evidence_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                media_id,
                str(path),
                name,
                os.path.splitext(name)[1].lower(),
                stat.st_size,
                stat.st_mtime_ns,
                str(stat.st_dev),
                stat.st_ino,
                identity_method,
                json.dumps(
                    {
                        "authority": authority,
                        "execution_id": execution_id,
                        "source_observation_id": (
                            source_observation_id
                        ),
                    }
                ),
            ),
        )

        observation_id = cursor.lastrowid

        cursor.execute(
            """
            UPDATE media_items
            SET
                file_path = ?,
                file_name = ?,
                file_size_bytes = ?,
                file_mtime_ns = ?,
                status = 'active',
                updated_at = CURRENT_TIMESTAMP,
                last_scanned_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                str(path),
                name,
                stat.st_size,
                stat.st_mtime_ns,
                media_id,
            ),
        )

        return observation_id

    def find_execution_authorised_observation(
        self,
        *,
        media_id: int,
        path: str,
        execution_id: int,
        identity_method: str = (
            'organisation_execution_continuity'
        ),
    ) -> int | None:
        """
        Return the id of an existing execution-authorised resulting
        observation for `media_id` at `path` recorded by the named
        organisation execution, or None.

        Used by execution recovery for idempotency: a partial run that
        already recorded the resulting observation must not create a
        duplicate. Only rows whose identity method is the
        execution-authorised continuity method and whose evidence names
        this execution are matched. Scope executions pass their own
        continuity method so per-file and scope observations never
        cross-match.
        """

        target = self._normalized_path(path)

        for observation in self.get_file_observations(media_id):

            if (
                observation.identity_match_method
                != identity_method
            ):

                continue

            if self._normalized_path(
                observation.file_path or ""
            ) != target:

                continue

            if (
                observation.identity_evidence or {}
            ).get("execution_id") != execution_id:

                continue

            return observation.id

        return None

    def _find_reappearance(
        self,
        cursor,
        path: str,
        size_bytes: int,
        file_mtime_ns: int,
    ) -> int | None:
        """
        The missing lineage id at `path` whose stored fingerprint
        matches the scanned fingerprint, or None.

        Reappearance requires both path continuity and a fingerprint
        match (the existing path_and_fingerprint standard). An
        unknown mtime never revives: size alone is too weak to
        prove continuity, so that case falls through to normal
        new-lineage creation. The latest matching row wins when
        several missing rows share the path.
        """

        if not file_mtime_ns or file_mtime_ns == UNKNOWN_FILE_MTIME_NS:
            return None

        row = cursor.execute(
            """
            SELECT id
            FROM media_items
            WHERE file_path = ?
              AND COALESCE(status, 'active') = 'missing'
              AND file_size_bytes = ?
              AND file_mtime_ns = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                path,
                size_bytes,
                file_mtime_ns,
            ),
        ).fetchone()

        return row[0] if row is not None else None

    def _find_move_link(
        self,
        cursor,
        path: str,
        size_bytes: int,
        file_mtime_ns: int,
    ) -> dict:
        """
        Explicit move-candidate evidence for a newly created lineage,
        without merging anything.

        When a new path's fingerprint matches missing lineages at
        other paths, size+mtime alone cannot prove a cross-path move
        (the identity constraint), so the missing rows are left
        untouched and the candidate link is recorded on the new
        observation instead. Unknown mtimes and empty files never
        link. A single candidate is named; several candidates are
        listed without choosing; no candidate means no keys.
        """

        if not size_bytes or not file_mtime_ns:
            return {}

        if file_mtime_ns == UNKNOWN_FILE_MTIME_NS:
            return {}

        rows = cursor.execute(
            """
            SELECT id
            FROM media_items
            WHERE file_path <> ?
              AND COALESCE(status, 'active') = 'missing'
              AND file_size_bytes = ?
              AND file_mtime_ns = ?
            ORDER BY id DESC
            """,
            (
                path,
                size_bytes,
                file_mtime_ns,
            ),
        ).fetchall()

        if not rows:
            return {}

        if len(rows) == 1:
            return {
                "possible_move_from": {
                    "media_id": rows[0][0],
                    "match_fields": [
                        "file_size_bytes",
                        "file_mtime_ns",
                    ],
                },
                "merged": False,
                "link_basis": (
                    "single fingerprint match among "
                    "missing lineages"
                ),
            }

        return {
            "possible_move_candidates": [
                {"media_id": row[0]} for row in rows
            ],
            "merged": False,
            "link_basis": (
                "ambiguous fingerprint matches among "
                "missing lineages"
            ),
        }

    def reconcile_existing_paths(
        self,
        scan_root: str,
        seen_paths: Iterable[str],
        excluded_paths: Iterable[str] = (),
    ) -> int:
        """
        Transition active media lineages under scan_root to
        status='missing' when their path was absent from the
        authoritative scan result.

        Existence is the only concern here:

        - Only status='active' lineages are candidates.
        - Only lineages whose path lies under scan_root are candidates.
        - A candidate whose path was NOT present in seen_paths and is
          not excluded from scanning becomes 'missing'.
        - updated_at records the transition using the repository's
          existing timestamp convention (CURRENT_TIMESTAMP).
        - No file_observation is created and no analysis / provenance
          row is created or modified.

        Path scoping uses pathlib normalisation (resolve) and a
        true path-boundary comparison, so /media/movies2 is never
        treated as being under /media/movies.

        Excluded paths use the same prefix semantics as the scanner
        (app/scanner/scanner.py) and are exempt from missing marking.

        Transaction/commit lifecycle remains owned by the caller.

        Returns the number of lineages transitioned to missing.
        """

        root = self._normalized_path(scan_root)

        excluded = [
            self._normalized_path(path)
            for path in excluded_paths
        ]

        normalized_seen = {
            self._normalized_path(path)
            for path in seen_paths
        }

        rows = self.connection.execute(
            """
            SELECT
                id,
                file_path
            FROM media_items
            WHERE COALESCE(status, 'active') = 'active'
            """
        ).fetchall()

        missing_ids = []

        for media_id, file_path in rows:

            normalized_path = self._normalized_path(file_path)

            # Only paths under the scanned root are candidates.
            if not Path(normalized_path).is_relative_to(root):
                continue

            # Excluded paths must not be interpreted as missing.
            if any(
                normalized_path.startswith(ex)
                for ex in excluded
            ):
                continue

            # Present in the scan result -> remains active.
            if normalized_path in normalized_seen:
                continue

            missing_ids.append(media_id)

        for media_id in missing_ids:

            self.connection.execute(
                """
                UPDATE media_items
                SET
                    status = 'missing',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (media_id,),
            )

        return len(missing_ids)

    def record_confirmed_deletion(
        self,
        *,
        media_id: int,
        execution_job_id: int,
        source_observation_id: int | None,
        deleted_path: str,
        detail: str | None = None,
    ) -> int:
        """
        Append a lineage-level confirmed-deletion event.

        Records that explicitly verified destruction of preserved
        bytes occurred for this lineage's history (currently: the
        post-success execution deletion of a staging backup). The
        lineage row itself is NOT modified: the lineage continues
        with its verified result, so marking it deleted would
        corrupt truth. Observed disappearance without verified
        destruction must never call this method (that stays
        status='missing').

        Pure history append. No filesystem interaction. The caller
        (today: only the verified-success branch of the explicit
        execution deletion path) owns transaction commit.
        """

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO lineage_confirmed_deletions (
                media_id,
                execution_job_id,
                source_observation_id,
                deleted_path,
                detail
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                media_id,
                execution_job_id,
                source_observation_id,
                deleted_path,
                detail,
            ),
        )

        return cursor.lastrowid

    def get_confirmed_deletions(
        self,
        media_id: int,
    ) -> list:
        """
        Append-only confirmed-destruction history for one lineage,
        oldest first. Empty when nothing was deliberately destroyed
        (in particular: disappearance and failed deletions leave no
        rows here).
        """

        return self.connection.execute(
            """
            SELECT
                id,
                media_id,
                execution_job_id,
                source_observation_id,
                deleted_path,
                deleted_at,
                detail
            FROM lineage_confirmed_deletions
            WHERE media_id = ?
            ORDER BY id ASC
            """,
            (media_id,),
        ).fetchall()

    @staticmethod
    def _normalized_path(path: str) -> str:
        """
        Normalise a filesystem path for scoping/exclusion comparison.
        """
        return str(Path(path).resolve())

    def get_media_item(
        self,
        media_id: int,
    ) -> MediaLineage | None:
        """
        Retrieve the stable media lineage identity including the
        current fingerprint stored on the active lineage.
        """

        row = self.connection.execute(
            """
            SELECT
                id,
                file_path,
                file_name,
                status,
                file_size_bytes,
                file_mtime_ns
            FROM media_items
            WHERE id = ?
            """,
            (
                media_id,
            ),
        ).fetchone()

        if row is None:
            return None

        return MediaLineage(
            id=row[0],
            file_path=row[1],
            file_name=row[2],
            status=row[3],
            file_size_bytes=row[4],
            file_mtime_ns=row[5],
        )

    def get_active_lineage_by_path(
        self,
        path: str,
    ) -> MediaLineage | None:
        """
        Retrieve the current active lineage for an exact path.

        Used by the analysis pipeline's content-identity preflight.
        This is a read-only lookup; identity resolution and scan
        reconciliation remain owned by sync_media().
        """

        row = self.connection.execute(
            """
            SELECT
                id,
                file_path,
                file_name,
                status,
                file_size_bytes,
                file_mtime_ns
            FROM media_items
            WHERE file_path = ?
              AND COALESCE(status, 'active') = 'active'
            ORDER BY id DESC
            LIMIT 1
            """,
            (path,),
        ).fetchone()

        if row is None:
            return None

        return MediaLineage(
            id=row[0],
            file_path=row[1],
            file_name=row[2],
            status=row[3],
            file_size_bytes=row[4],
            file_mtime_ns=row[5],
        )

    def get_latest_content_identity(
        self,
        media_id: int,
        *,
        size_bytes: int,
        file_mtime_ns: int,
    ) -> tuple[str, int] | None:
        """
        Return (sha256, observation_id) for the highest-id observation
        of this lineage whose fingerprint matches and which carries a
        content hash.
        """

        row = self.connection.execute(
            """
            SELECT id, sha256_hash
            FROM file_observations
            WHERE media_id = ?
              AND size_bytes = ?
              AND file_mtime_ns = ?
              AND sha256_hash IS NOT NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                media_id,
                size_bytes,
                file_mtime_ns,
            ),
        ).fetchone()

        if row is None:
            return None

        return row[1], row[0]

    def get_active_lineages(
        self,
    ) -> list[MediaLineage]:
        """
        Retrieve the stable lineage identities of all current
        (non-missing) media items in deterministic order.

        This is the existence-authoritative lineage enumeration used
        by read models such as the opportunity queue. Currentness is
        then derived per lineage through AnalysisValidityService.
        """

        rows = self.connection.execute(
            """
            SELECT
                id,
                file_path,
                file_name,
                status,
                file_size_bytes,
                file_mtime_ns
            FROM media_items
            WHERE COALESCE(status, 'active') = 'active'
            ORDER BY id
            """
        ).fetchall()

        return [
            MediaLineage(
                id=row[0],
                file_path=row[1],
                file_name=row[2],
                status=row[3],
                file_size_bytes=row[4],
                file_mtime_ns=row[5],
            )
            for row in rows
        ]

    def get_missing_lineages(
        self,
    ) -> list[MediaLineage]:
        """
        Retrieve the stable lineage identities of all missing media
        items in deterministic order.

        Mirrors get_active_lineages for status='missing'; existence
        state remains authoritative at the persistence boundary.
        """

        rows = self.connection.execute(
            """
            SELECT
                id,
                file_path,
                file_name,
                status,
                file_size_bytes,
                file_mtime_ns
            FROM media_items
            WHERE COALESCE(status, 'active') = 'missing'
            ORDER BY id
            """
        ).fetchall()

        return [
            MediaLineage(
                id=row[0],
                file_path=row[1],
                file_name=row[2],
                status=row[3],
                file_size_bytes=row[4],
                file_mtime_ns=row[5],
            )
            for row in rows
        ]

    def get_last_scanned_at(
        self,
    ) -> str | None:
        """
        Retrieve the most recent scan timestamp recorded on any
        media lineage.

        Returns None when no lineage has ever been scanned. There is
        no scan-history table in the current architecture, so this is
        the only persisted scan fact. Missing lineages are included:
        an item that was scanned and later reconciled as missing was
        still scanned.
        """

        row = self.connection.execute(
            """
            SELECT MAX(last_scanned_at)
            FROM media_items
            WHERE last_scanned_at IS NOT NULL
            """
        ).fetchone()

        if row is None or row[0] is None:
            return None

        return row[0]

    def get_file_observations(
        self,
        media_id: int,
    ) -> list[FileObservation]:
        """
        Retrieve the immutable observation history for a media
        lineage in deterministic observation order.
        """

        rows = self.connection.execute(
            """
            SELECT
                id,
                media_id,
                observed_at,
                file_path,
                file_name,
                file_extension,
                size_bytes,
                file_mtime_ns,
                filesystem_device,
                filesystem_inode,
                sha256_hash,
                identity_match_method,
                identity_evidence_json,
                created_at
            FROM file_observations
            WHERE media_id = ?
            ORDER BY id
            """,
            (
                media_id,
            ),
        ).fetchall()

        return [
            self._file_observation_from_row(row)
            for row in rows
        ]

    def get_observation_by_id(
        self,
        observation_id: int,
    ) -> FileObservation | None:
        """
        Retrieve a single immutable file observation by id.

        Used by execution boundaries to re-read the exact
        observation context an authorised operation cites.
        """

        row = self.connection.execute(
            """
            SELECT
                id,
                media_id,
                observed_at,
                file_path,
                file_name,
                file_extension,
                size_bytes,
                file_mtime_ns,
                filesystem_device,
                filesystem_inode,
                sha256_hash,
                identity_match_method,
                identity_evidence_json,
                created_at
            FROM file_observations
            WHERE id = ?
            """,
            (observation_id,),
        ).fetchone()

        if row is None:

            return None

        return self._file_observation_from_row(row)

    @staticmethod
    def _file_observation_from_row(
        row,
    ) -> FileObservation:

        return FileObservation(
            id=row[0],
            media_id=row[1],
            observed_at=row[2],
            file_path=row[3],
            file_name=row[4],
            file_extension=row[5],
            size_bytes=row[6],
            file_mtime_ns=row[7],
            filesystem_device=row[8],
            filesystem_inode=row[9],
            sha256_hash=row[10],
            identity_match_method=row[11],
            identity_evidence=json.loads(
                row[12] or "{}"
            ),
            created_at=row[13],
        )