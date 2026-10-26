import json

from app.models.user_policy import (
    USER_POLICY_VERSION,
    UserPolicy,
)
from app.models.user_policy_profile import (
    UserPolicyProfile,
)


class UserPolicyRepository:
    """
    Persistence boundary for durable user-policy profiles.

    This repository stores immutable policy snapshots and returns the
    latest snapshot when requested.

    Policy meaning remains owned by UserPolicy. This class does not
    calculate effective policy values or introduce a second policy
    representation.

    Transaction ownership remains with the caller.
    """

    def __init__(self, connection):
        self.connection = connection

    def create_profile(
        self,
        policy: UserPolicy,
        *,
        actor: str,
        reason: str | None = None,
    ) -> int:
        """
        Persist one immutable policy-profile snapshot.

        Every profile change creates a new row. Nothing is updated or
        deleted.
        """

        if not isinstance(policy, UserPolicy):
            raise TypeError("policy must be a UserPolicy")

        actor = str(actor or "").strip()
        if not actor:
            raise ValueError("actor is required")

        if policy.semantic_version != USER_POLICY_VERSION:
            raise ValueError(
                "policy semantic version is not compatible with "
                f"the current UserPolicy version {USER_POLICY_VERSION}"
            )

        payload = policy.to_policy_payload()

        cursor = self.connection.execute(
            """
            INSERT INTO user_policy_profiles (
                policy_json,
                semantic_version,
                actor,
                reason
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                policy.semantic_version,
                actor,
                reason,
            ),
        )

        return cursor.lastrowid

    def get_current_profile(self) -> UserPolicyProfile | None:
        """
        Return the newest durable profile.

        Ordering is deterministic: newest created_at first, then highest
        id as the tie-breaker.

        Absence is represented by None. Default-policy fallback belongs
        to the application/policy service, not the repository.
        """

        row = self.connection.execute(
            """
            SELECT
                id,
                policy_json,
                semantic_version,
                actor,
                reason,
                created_at
            FROM user_policy_profiles
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()

        if row is None:
            return None

        return self._profile_from_row(row)

    def list_profiles(self) -> list[UserPolicyProfile]:
        """
        Return immutable profile history, newest first.
        """

        rows = self.connection.execute(
            """
            SELECT
                id,
                policy_json,
                semantic_version,
                actor,
                reason,
                created_at
            FROM user_policy_profiles
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()

        return [
            self._profile_from_row(row)
            for row in rows
        ]

    @staticmethod
    def _profile_from_row(row) -> UserPolicyProfile:
        try:
            payload = json.loads(row[1])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"invalid policy profile JSON for row {row[0]}"
            ) from exc

        if not isinstance(payload, dict):
            raise ValueError(
                f"invalid policy profile payload for row {row[0]}"
            )

        semantic_version = row[2]

        if semantic_version != USER_POLICY_VERSION:
            raise ValueError(
                "stored policy semantic version "
                f"{semantic_version!r} is incompatible with current "
                f"UserPolicy version {USER_POLICY_VERSION}"
            )

        # Persisted policy payload contains both explicit policy fields
        # and derived/effective values. Only actual UserPolicy dataclass
        # fields are reconstructed.
        field_names = UserPolicy.__dataclass_fields__.keys()

        policy_kwargs = {
            name: payload[name]
            for name in field_names
            if name in payload
        }

        policy = UserPolicy(**policy_kwargs)

        return UserPolicyProfile(
            id=row[0],
            policy=policy,
            semantic_version=semantic_version,
            actor=row[3],
            reason=row[4],
            created_at=row[5],
        )