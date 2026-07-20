"""Geometry helpers for overlay rectangles."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF


def normalize_rect(start: QPointF, end: QPointF) -> QRectF:
    """Create a normalized rectangle from two points.

    :param start: First point.
    :param end: Second point.
    :return: Normalized rectangle in scene coordinates.
    """
    return QRectF(start, end).normalized()
