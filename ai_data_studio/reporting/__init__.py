# -*- coding: utf-8 -*-
"""Reporting package for AI Synthetic Data Studio."""
from .pdf_report import generate_pdf_report, is_pdf_available

__all__ = [
    "generate_pdf_report",
    "is_pdf_available",
]
