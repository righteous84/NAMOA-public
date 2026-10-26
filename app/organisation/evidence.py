"""
Organisation EVIDENCE (Sprint 13).

Evidence is derived ONLY from persisted filesystem observations
and media lineages. The builder never scans the filesystem,
never probes media, and never mutates anything.

Filename attribute parsing reuses the existing
ClassificationEvidenceBuilder (shared infrastructure, separate
semantics): organisation rules consume the distilled attributes
as facts about the NAME, never as optimisation conclusions.
"""

from dataclasses import dataclass

from app.analysis_engine.media_classifier.evidence_builder import (
    ClassificationEvidenceBuilder,
)


# Streaming chunk size for explicit content-hash acquisition
# (1 MiB).
HASH_CHUNK_SIZE = 1024 * 1024


def compute_content_hash(file_path):
    """
    Explicit content-hash ACQUISITION (Sprint 13 correction).

    Hashing is OPTIONAL EVIDENCE ACQUISITION, deliberately kept
    OUT of the normal scanner path: a normal media scan reads
    only filesystem metadata and never the complete contents of
    media files.

    This helper exists for explicit, on-demand acquisition only
    (an operator/application action over chosen lineages). It
    streams in chunks so large media files are never loaded into
    memory, and it performs a READ-ONLY open.

    A file that cannot be read yields None: absence of a hash is
    always honest, never fabricated.
    """

    import hashlib

    digest = hashlib.sha256()

    try:

        with open(file_path, "rb") as handle:

            while True:

                chunk = handle.read(HASH_CHUNK_SIZE)

                if not chunk:
                    break

                digest.update(chunk)

        return digest.hexdigest()

    except Exception:

        return None


def normalise_path(path: str) -> str:
    """
    Lexical path normalisation used ONLY for comparisons.
    Purely string-based; no filesystem access.
    """

    return str(path).replace("\\", "/").casefold().rstrip("/")


@dataclass(frozen=True, slots=True)
class LineageOrganisationEvidence:
    """
    One lineage's organisation evidence, derived from its
    current (highest-id) immutable observation.

    sha256_hash carries whatever the scanner recorded for THIS
    observation; absence stays None and is reported honestly
    (no fabrication, no backfill).
    """

    media_id: int

    path: str

    name: str | None

    extension: str | None

    size_bytes: int | None

    file_mtime_ns: int | None

    sha256_hash: str | None

    observation_id: int | None

    observed_at: str | None

    identity_match_method: str | None

    path_segments: tuple[str, ...]

    filename_attributes: dict


class OrganisationEvidenceBuilder:
    """
    Build per-lineage organisation evidence over the existing
    media repository reads.
    """

    def __init__(self):
        # Shared filename-evidence infrastructure (reuse, never
        # duplicated).
        self._filename_builder = (
            ClassificationEvidenceBuilder()
        )

    def build(
        self,
        lineage,
        observations,
        *,
        metadata_domains=None,
    ) -> LineageOrganisationEvidence:
        """
        lineage: a MediaLineage read model.
        observations: the lineage's observation history
        (ordered); the highest-id observation is the current
        filesystem state.
        metadata_domains: optional subset of the observed
        filename-attribute domains to distil. None (default)
        distils all current domains, preserving existing
        behaviour exactly.
        """

        current = None

        for observation in observations:

            if (
                current is None
                or observation.id > current.id
            ):
                current = observation

        if current is None:

            raise ValueError(
                f"media lineage {lineage.id} has no "
                f"filesystem observation to reason about"
            )

        return LineageOrganisationEvidence(
            media_id=lineage.id,
            path=current.file_path,
            name=current.file_name,
            extension=current.file_extension,
            size_bytes=current.size_bytes,
            file_mtime_ns=current.file_mtime_ns,
            sha256_hash=current.sha256_hash,
            observation_id=current.id,
            observed_at=current.observed_at,
            identity_match_method=(
                current.identity_match_method
            ),
            path_segments=self._path_segments(
                current.file_path
            ),
            filename_attributes=(
                self._filename_attributes(
                    current.file_name,
                    metadata_domains=metadata_domains,
                )
            ),
        )

    @staticmethod
    def _path_segments(path: str | None) -> tuple[str, ...]:

        if not path:
            return ()

        normalised = str(path).replace("\\", "/").strip("/")

        segments = [
            segment
            for segment in normalised.split("/")
            if segment
        ]

        if segments:

            segments = segments[:-1]

        return tuple(segments)

    def _filename_attributes(
        self,
        file_name: str | None,
        *,
        metadata_domains=None,
    ) -> dict:
        """
        Distil classification-domain filename evidence into
        plain facts (best-confidence value per domain).

        metadata_domains optionally narrows which observed
        domains participate. None distils all current domains.
        Unknown domains raise ValueError; nothing is invented.
        """

        if not file_name:
            return {}

        if metadata_domains is None:

            domains = (
                "source",
                "release",
                "resolution",
                "video_codec",
            )

        else:

            from app.organisation.preferences import (
                METADATA_DOMAINS,
            )

            unknown = [
                domain for domain in metadata_domains if (
                    domain not in METADATA_DOMAINS
                )
            ]

            if unknown:

                raise ValueError(
                    f"unknown metadata domains "
                    f"{sorted(unknown)}"
                )

            domains = tuple(metadata_domains)

        collection = self._filename_builder.build(file_name)

        attributes = {}

        for domain in domains:

            items = collection.by_domain(domain)

            if not items:
                continue

            best = max(
                items,
                key=lambda item: item.confidence,
            )

            attributes[domain] = {
                "value": best.value,
                "confidence": best.confidence,
            }

        return attributes
