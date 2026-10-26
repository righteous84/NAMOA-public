"""Notification application service (GUI/UX Phase 4).

Application boundary for the persistent user-notification system.

Notifications are derived presentation of authoritative moments
(state transitions already recorded by the existing authorities).
They are best-effort: the application services that emit them must
never fail an operation because notification writing failed. The
notification system is never read back into any decision or state
machine, and it never replaces the domain audit ledgers.
"""

from app.models.notification import Notification


class NotificationService:
    """
    Application-facing notification workflows.
    """

    def __init__(
        self,
        *,
        notification_repository,
    ):

        self.notifications = notification_repository

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
        Create one notification. Callers treat this as best-effort:
        a failure here must never fail the triggering operation.
        """

        return self.notifications.create(
            category=category,
            title=title,
            message=message,
            media_id=media_id,
            execution_job_id=execution_job_id,
            recommendation_id=recommendation_id,
            scan_id=scan_id,
        )

    def list_active(self) -> list[Notification]:
        """
        The active (undismissed) notifications, newest first.
        """

        return self.notifications.list_active()

    def dismiss(self, notification_id: int) -> None:
        """
        Dismiss one notification.
        """

        self.notifications.dismiss(notification_id)

    def dismiss_all(self) -> int:
        """
        Dismiss every active notification. Returns the count.
        """

        return self.notifications.dismiss_all()