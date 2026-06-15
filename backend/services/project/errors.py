from __future__ import annotations


class ProjectNotFoundError(Exception):
    """Raised when a project id is not present in the database."""


class ProjectAccessError(Exception):
    """Raised when a user tries to access a project they do not own."""
