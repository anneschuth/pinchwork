"""Markdown-to-HTML renderer for Pinchwork pages using mistune."""

from __future__ import annotations

import re

import mistune


def md_to_html(md: str, base_path: str = "") -> str:
    """Convert markdown text to HTML using mistune.

    Rewrites relative image paths to /docs-assets/ for serving from the web UI.
    """
    # Rewrite relative image paths like ../../docs/demo.gif → /docs-assets/demo.gif
    # and docs/demo.gif → /docs-assets/demo.gif
    md = re.sub(
        r"!\[([^\]]*)\]\((?:\.\./)*(?:docs/)?([^)]+\.(?:gif|png|jpg|jpeg|svg|webp))\)",
        r"![\1](/docs-assets/\2)",
        md,
    )
    return mistune.html(md)
