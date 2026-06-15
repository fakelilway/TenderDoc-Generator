"""Indirection layer for runtime-patchable infrastructure.

The public facade ``services.project_service`` owns the canonical bindings for
``_connect``, ``minio_client``, ``parse_tender`` and ``_tender_object_name``.
Tests monkeypatch those names *on the facade module*
(``monkeypatch.setattr(project_service, "_connect", ...)``). For the patch to
take effect inside the extracted submodules, the submodules must resolve those
names from the facade at call time rather than binding their own module-level
copies at import time. This module provides that call-time lookup.

The facade is imported lazily (inside each accessor) to avoid an import cycle:
the facade imports the submodules at module load, so the submodules cannot
import the facade at their own load time.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator


def _facade() -> Any:
    from services import project_service

    return project_service


@contextmanager
def connect() -> Iterator[Any]:
    """Yield a connection via the facade's (patchable) ``_connect``."""
    with _facade()._connect() as conn:
        yield conn


def minio() -> Any:
    """Return the facade's (patchable) ``minio_client``."""
    return _facade().minio_client


def parse_tender(text: str) -> Any:
    """Call the facade's (patchable) ``parse_tender``."""
    return _facade().parse_tender(text)


def tender_object_name(project_id: int, filename: str) -> str:
    """Call the facade's (patchable) ``_tender_object_name``."""
    return _facade()._tender_object_name(project_id, filename)


def get_project_owner(project_id: int) -> int | None:
    """Call the facade's ``get_project_owner``.

    ``authorize_project_access`` resolves the owner lookup through the facade so
    that tests which monkeypatch ``project_service.get_project_owner`` (e.g. the
    project-access dependency tests) still affect authorization, exactly as when
    both functions lived in the same module.
    """
    return _facade().get_project_owner(project_id)
