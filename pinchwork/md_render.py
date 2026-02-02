"""Lightweight Markdown-to-HTML renderer for Pinchwork pages."""

from __future__ import annotations

import html
import re


def md_to_html(md: str) -> str:
    """Convert markdown text to HTML. Handles headings, lists, code blocks, bold, italic, links."""
    lines = md.split("\n")
    out: list[str] = []
    in_code = False
    in_list = False
    in_ol = False

    for line in lines:
        # Code blocks
        if line.startswith("```"):
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                out.append("<pre><code>")
                in_code = True
            continue
        if in_code:
            out.append(html.escape(line))
            continue

        stripped = line.strip()

        # Close lists if needed
        if in_list and not stripped.startswith("- "):
            out.append("</ul>")
            in_list = False
        if in_ol and not re.match(r"^\d+\.\s", stripped):
            out.append("</ol>")
            in_ol = False

        # Headings
        if stripped.startswith("### "):
            out.append(f"<h3>{_inline(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            out.append(f"<h2>{_inline(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            out.append(f"<h1>{_inline(stripped[2:])}</h1>")
        elif stripped.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(stripped[2:])}</li>")
        elif re.match(r"^\d+\.\s", stripped):
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            text = re.sub(r"^\d+\.\s", "", stripped)
            out.append(f"<li>{_inline(text)}</li>")
        elif stripped == "---":
            out.append("<hr>")
        elif stripped == "":
            out.append("")
        else:
            out.append(f"<p>{_inline(stripped)}</p>")

    if in_list:
        out.append("</ul>")
    if in_ol:
        out.append("</ol>")
    return "\n".join(out)


def _inline(text: str) -> str:
    """Inline markdown: bold, italic, code, links."""
    text = html.escape(text)
    # Code spans
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # Bold
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    # Italic (underscores)
    text = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"<em>\1</em>", text)
    # Italic (single asterisks)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    # Links [text](url)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2">\1</a>',
        text,
    )
    return text
