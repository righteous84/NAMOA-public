from dataclasses import dataclass

from app.models.user_policy import UserPolicy


@dataclass(frozen=True, slots=True)
class UserPolicyProfile:
    """
    Durable user-policy profile record.

    The policy itself remains owned by UserPolicy. This model only
    carries persistence metadata and the reconstructed policy value.
    """

    id: int
    policy: UserPolicy
    semantic_version: str
    actor: str
    reason: str | None
    created_at: str