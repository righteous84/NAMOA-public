import json

from app.knowledge.knowledge_entry import KnowledgeEntry


class KnowledgeRepository:
    """
    Persistence boundary for versioned knowledge.

    Owns:

        knowledge_sets
        knowledge_entries

    This repository only performs persistence.

    It does not:

        - choose knowledge versions
        - interpret knowledge
        - implement business rules
    """

    def __init__(
        self,
        connection,
    ):
        self.connection = connection


    def get_entry(
        self,
        *,
        set_name: str,
        domain: str,
        key: str,
    ) -> tuple[int, KnowledgeEntry] | None:
        """
        Retrieve a knowledge entry from the newest version
        of the requested knowledge set.
        """

        cursor = self.connection.execute(
            """
            SELECT
                ks.id,
                ks.version,
                ke.value_json
            FROM knowledge_entries ke
            JOIN knowledge_sets ks
                ON ks.id = ke.knowledge_set_id
            WHERE
                ks.name = ?
                AND ke.domain = ?
                AND ke.knowledge_key = ?
            ORDER BY ks.id DESC
            LIMIT 1
            """,
            (
                set_name,
                domain,
                key,
            ),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        knowledge_set_id, version, value_json = row

        return (
            knowledge_set_id,
            KnowledgeEntry(
                domain=domain,
                key=key,
                value=json.loads(value_json),
                version=version,
            ),
        )

    def get_newest_set_version(
        self,
        set_name: str,
    ) -> tuple[int, str] | None:
        """
        Return (id, version) of the newest knowledge-set row for a
        name, or None when the set does not exist.

        Resolution mirrors get_entry: newest insertion id wins.
        Used by applicability evaluation to compare the set version a
        historical run consulted against the currently resolvable one.
        """

        cursor = self.connection.execute(
            """
            SELECT
                id,
                version
            FROM knowledge_sets
            WHERE name = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                set_name,
            ),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return (
            row[0],
            row[1],
        )

    def get_set_name_and_version(
        self,
        knowledge_set_id: int,
    ) -> tuple[str, str] | None:
        """
        Return (name, version) for a knowledge-set row id, or None.
        """

        cursor = self.connection.execute(
            """
            SELECT
                name,
                version
            FROM knowledge_sets
            WHERE id = ?
            """,
            (
                knowledge_set_id,
            ),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return (
            row[0],
            row[1],
        )