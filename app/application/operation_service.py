"""Executable-operation registry application service (Phase 6).

Application boundary over the closed operation registry. The GUI and
Advanced controls render operation capabilities ONLY from this service;
they never construct FFmpeg commands and never invent operations.

The registry (app/execution/operations.py) is the sole source of truth
for executable operations and their parameter schemas.
"""

from app.execution.operations import (
    EXECUTABLE_OPERATIONS,
    OPERATIONS,
    registry_policy_values,
)


class OperationService:
    """
    Application-facing operation registry workflows (read-only).
    """

    def __init__(self):

        self.registry_version = None

    def list_operations(self) -> list:
        """
        Every defined operation with its authoritative schema.
        Non-executable operations are clearly marked so the GUI never
        exposes a control for an operation that cannot execute.
        """

        return [
            definition.to_dict()
            for definition in OPERATIONS.values()
        ]

    def executable_operations(self) -> list:
        """
        The currently executable operations and their parameter
        schemas. This is the ONLY set Advanced controls may expose.
        """

        return [
            definition.to_dict()
            for definition in OPERATIONS.values()
            if definition.operation in EXECUTABLE_OPERATIONS
        ]

    def get_operation(self, operation: str) -> dict | None:
        """
        One operation definition, or None when unknown.
        """

        definition = OPERATIONS.get(operation)

        if definition is None:
            return None

        return definition.to_dict()

    def operation_schema(self, operation: str) -> dict:
        """
        The full authoritative schema for one operation. Raises
        ValueError for an unknown operation.
        """

        definition = OPERATIONS.get(operation)

        if definition is None:
            raise ValueError(
                f"operation '{operation}' is not registered"
            )

        return definition.to_dict()

    def policy_values(self) -> dict:
        """
        The attributable registry snapshot for execution provenance.
        """

        return registry_policy_values()