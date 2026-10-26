"""Notification persistence (GUI/UX Phase 4).

Thin repository over the notifications table (migration 031). The
notification system is a separate presentation capability: it never
replaces, duplicates, or reads back the domain audit ledgers
(recommendation_events, organisation_proposal_events,
organisation_execution_events, the media_executions state machine).

Database connection lifecycle is owned by the caller.
"""

from app.models.notification import Notification


class NotificationRepository:

    def __init__(self, connection):
        self.connection = connection

    def create(
        self,
        *,
        category: str,
        title: str,
        message: str | None = None,
        media_id: int | None = None,
        execution_job_id: int | None = None,
        recommendation_id: int | None = None,
        scan_id: int | None = None,
    ) -> int:
        """
        Create one notification in the active (undismissed) state and
        return its durable id. The caller is responsible for
        committing; a best-effort notification write must never
        corrupt the triggering operation's transaction.
        """

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO notifications (
                category,
                title,
                message,
                media_id,
                execution_job_id,
                recommendation_id,
                scan_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                category,
                title,
                message,
                media_id,
                execution_job_id,
                recommendation_id,
                scan_id,
            ),
        )

        # The notification system uses its own dedicated connection,
        # so committing here is safe and never interferes with an
        # in-flight scan/execution transaction on another connection.
        self.connection.commit()

        return cursor.lastrowid

    def list_active(self) -> list[Notification]:
        """
        All active (undismissed) notifications, newest first.
        """

        rows = self.connection.execute(
            """
            SELECT
                id,
                category,
                title,
                message,
                media_id,
                execution_job_id,
                recommendation_id,
                scan_id,
                created_at,
                dismissed_at
            FROM notifications
            WHERE dismissed_at IS NULL
            ORDER BY id DESC
            """
        ).fetchall()

        return [self._from_row(row) for row in rows]

    def dismiss(self, notification_id: int) -> None:
        """
        Dismiss one active notification. Dismissing an already
        dismissed notification is a no-op.
        """

        self.connection.execute(
            """
            UPDATE notifications
            SET dismissed_at = CURRENT_TIMESTAMP
            WHERE id = ? AND dismissed_at IS NULL
            """,
            (notification_id,),
        )

        self.connection.commit()

    def dismiss_all(self) -> int:
        """
        Dismiss every active notification. Returns the number of
        notifications dismissed.
        """

        cursor = self.connection.execute(
            """
            UPDATE notifications
            SET dismissed_at = CURRENT_TIMESTAMP
            WHERE dismissed_at IS NULL
            """
        )

        self.connection.commit()

        return cursor.rowcount

    @staticmethod
    def _from_row(row) -> Notification:
        return Notification(
            id=row[0],
            category=row[1],
            title=row[2],
            message=row[3],
            media_id=row[4],
            execution_job_id=row[5],
            recommendation_id=row[6],
            scan_id=row[7],
            created_at=row[8],
            dismissed_at=row[9],
        )