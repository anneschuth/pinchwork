"""Markdown-to-HTML renderer for Pinchwork pages using mistune."""

from __future__ import annotations

import mistune


def md_to_html(md: str) -> str:
    """Convert markdown text to HTML using mistune.

    Supports headings, lists, code blocks, tables, images, links, and inline formatting.
    """
    return mistune.html(md)
