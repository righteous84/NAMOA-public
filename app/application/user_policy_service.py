from app.models.user_policy import UserPolicy


class UserPolicyService:
    """
    Application boundary for durable user policy.

    Persistence mechanics remain owned by UserPolicyRepository.
    Policy semantics remain owned by UserPolicy.

    When no durable profile exists, the current default policy is used.
    Creating a profile always records an immutable policy snapshot.
    """

    def __init__(self, *, user_policy_repository):
        self.user_policy_repository = user_policy_repository

    def get_current_profile(self):
        """
        Return the newest durable policy profile, or None when no
        profile has ever been stored.
        """
        return self.user_policy_repository.get_current_profile()

    def get_effective_policy(self) -> UserPolicy:
        """
        Return the policy currently governing application behaviour.

        Durable profile wins when present. Otherwise the existing
        standard default policy is returned.
        """
        profile = self.get_current_profile()

        if profile is None:
            return UserPolicy.default()

        return profile.policy

    def set_policy(
        self,
        policy: UserPolicy,
        *,
        actor: str,
        reason: str | None = None,
    ) -> int:
        """
        Persist a new durable policy snapshot.

        Every change is append-only. Restoring defaults is therefore
        represented by explicitly storing UserPolicy.default().
        """
        if not isinstance(policy, UserPolicy):
            raise TypeError("policy must be a UserPolicy")

        return self.user_policy_repository.create_profile(
            policy,
            actor=actor,
            reason=reason,
        )

    def reset_to_defaults(
        self,
        *,
        actor: str,
        reason: str | None = None,
    ) -> int:
        """
        Persist an explicit restoration of the default policy.
        """
        return self.set_policy(
            UserPolicy.default(),
            actor=actor,
            reason=reason,
        )

    def get_history(self):
        """
        Return durable policy-profile history, newest first.
        """
        return self.user_policy_repository.list_profiles()