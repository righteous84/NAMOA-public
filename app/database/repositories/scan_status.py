from enum import Enum


class ScanStatus(Enum):
    """
    Result of MediaRepository.sync_media().

    Represents a persistence outcome, not a domain concept -
    lives in the repository layer rather than app/models.

    NEW       - no media_items row existed for this file_path; one was created.
    CHANGED   - a row existed but file_size_bytes differed from the scanner value.
    UNCHANGED - a row existed and file_size_bytes matched the scanner value.
    REAPPEARED - no active row existed, but a missing row at the same
        file_path matched the scanner fingerprint; that lineage was
        revived instead of forked.
    """
    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    REAPPEARED = "reappeared"