"""Read-only local 对照表 view. Bind 127.0.0.1:1780 only — never 0.0.0.0 / 8080."""

from prd_ai_battle.web.board import (
    MATRIX_COLUMNS,
    board_payload,
    draft_payload,
    matrix_payload,
    timeline_payload,
)
from prd_ai_battle.web.server import MATRIX_HOST, MATRIX_PORT, MATRIX_URL, serve, validate_bind

__all__ = [
    "MATRIX_COLUMNS",
    "MATRIX_HOST",
    "MATRIX_PORT",
    "MATRIX_URL",
    "board_payload",
    "draft_payload",
    "matrix_payload",
    "serve",
    "timeline_payload",
    "validate_bind",
]
