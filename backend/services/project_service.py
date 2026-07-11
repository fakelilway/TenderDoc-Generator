"""Public facade for the project service.

The implementation lives in the :mod:`services.project` package, split by
responsibility (CRUD, parsing, outline, strategy, delivery). This module keeps
the historical import surface intact: every name that callers, routers,
``workflow_service`` and the test suite reach for via
``services.project_service`` is re-exported here.

This module is also the *patch surface*: tests monkeypatch
``project_service._connect`` / ``minio_client`` / ``parse_tender`` /
``_tender_object_name``. The submodules deliberately resolve those names from
this module at call time (see :mod:`services.project._runtime`), so patching
here takes effect everywhere.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from uuid import uuid4

import psycopg2

# --- Patchable infrastructure (the names tests monkeypatch on this module) ---
from agents.parser_agent import parse_tender
from core.config import settings
from core.db import get_db_connection
from utils.minio_client import minio_client

# --- Canonical exception identities (single definition, re-exported) ---
from services.project.errors import ProjectAccessError, ProjectNotFoundError

# --- Shared status tables/helpers kept importable from the facade ---
from services.project._helpers import (
    _RUNNING_STATUSES,
    _STATUS_ORDER,
    _fetch_project,
    _fetch_project_status,
    _hydrated_workflow_state,
    _parse_workflow_state,
    _project_markdown,
    _project_pricing_strategy,
    _project_requirements,
    _project_review_report,
    _project_summary,
    _resolve_project_status,
    _review_report_from_json,
    _safe_filename,
    _status_rank,
    _workflow_patch,
)

# --- Grouped public + private API surface ---
from services.project.crud import (
    authorize_project_access,
    create_project,
    delete_project,
    get_project,
    get_project_owner,
    get_project_status,
    list_projects,
)
from services.project.parsing import (
    confirm_parsed_result,
    get_project_result,
    parse_project,
    start_parse_project,
)
from services.project.outline import (
    _build_document_outline_for_saved_technical_outline,
    _clean_document_outline,
    _clean_manual_image_slots,
    build_project_outline,
    get_knowledge_references,
    save_draft_markdown,
    save_project_outline,
    save_selected_knowledge_chunks,
)
from services.project.strategy import (
    _attachment_list,
    _checklist_items,
    _matching_status,
    append_final_version,
    build_final_checklist,
    build_project_pricing_strategy,
    build_project_response_matrix,
    build_project_score_prediction,
)
from services.project.personnel import (
    get_selected_personnel,
    recommend_project_personnel,
    recommend_tech_director_personnel,
    save_selected_project_manager,
    save_selected_tech_director,
)
from services.project.performance import (
    get_evidence_page_options,
    get_selected_performance,
    get_selected_role_performance,
    recommend_project_performance,
    recommend_role_performance,
    save_evidence_page_selection,
    save_selected_performance,
    save_selected_role_performance,
)
from services.project.delivery import (
    _DELIVERY_FORMATS,
    _DELIVERY_VOLUME_LABELS,
    _DOWNLOAD_ARTIFACTS,
    _build_review_report_markdown,
    _delivery_markdown_source,
    _delivery_preview_cache,
    _delivery_preview_fingerprint,
    _delivery_volumes,
    _export_delivery_artifact,
    _export_review_report,
    _parse_delivery_artifact,
    get_project_delivery_preview,
    get_project_download_url,
    get_project_review_report,
    invalidate_delivery_preview_cache,
)


@contextmanager
def _connect() -> Iterator[psycopg2.extensions.connection]:
    """Yield a pooled connection that commits on success, rolls back on error.

    Wraps ``core.db.get_db_connection`` so every ``with _connect() as conn:``
    call site keeps the transactional semantics it had with a raw psycopg2
    connection used as a context manager, while reusing pooled connections.
    """
    with get_db_connection() as conn:
        with conn:
            yield conn


def _tender_object_name(project_id: int, filename: str) -> str:
    return f"projects/{project_id}/tender/{uuid4().hex}_{_safe_filename(filename)}"
