"""Turn the Terms text into the HTML customers see.

The text is written in a small, forgiving format:

    ## Heading            starts a section
    A line of text.       a paragraph (a blank line starts the next one)
    - A bullet            a list item
    **bold**  and  [link text](https://example.com)  or  [mail](mailto:a@b.com)

Everything typed is HTML-escaped first, so an edit can never inject scripts or markup
into the customer page. Only the pieces above are turned into tags, and links are
limited to http(s) and mailto addresses.
"""

from __future__ import annotations

import html
import re

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_SAFE_HREF = re.compile(r"^(https?://|mailto:)[^\s\"'<>]+$", re.IGNORECASE)


def _inline(text: str) -> str:
    out = html.escape(text, quote=False)

    def link(match: re.Match[str]) -> str:
        label, href = match.group(1), html.unescape(match.group(2))
        if not _SAFE_HREF.match(href):
            return match.group(0)  # not a safe address: leave it as plain text
        safe_href = html.escape(href, quote=True)
        return (
            f'<a href="{safe_href}" target="_blank" rel="noopener noreferrer">{label}</a>'
        )

    out = _LINK.sub(link, out)
    return _BOLD.sub(r"<strong>\1</strong>", out)


def render_terms_html(markdown: str) -> str:
    """HTML for the policy: one `<section class="policy-section">` per heading."""
    parts: list[str] = []
    paragraph: list[str] = []
    bullets: list[str] = []
    open_section = False

    def flush() -> None:
        nonlocal paragraph, bullets
        if paragraph:
            parts.append("<p>" + _inline(" ".join(paragraph)) + "</p>")
            paragraph = []
        if bullets:
            items = "".join(f"<li>{_inline(item)}</li>" for item in bullets)
            parts.append(f"<ul>{items}</ul>")
            bullets = []

    for raw in markdown.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            flush()
            continue
        heading = re.match(r"^#{1,3}\s+(.*\S)\s*$", line)
        if heading:
            flush()
            if open_section:
                parts.append("</section>")
            parts.append('<section class="policy-section">')
            parts.append(f"<h2>{_inline(heading.group(1))}</h2>")
            open_section = True
            continue
        bullet = re.match(r"^[-*]\s+(.*\S)\s*$", line)
        if bullet:
            if paragraph:
                flush()
            bullets.append(bullet.group(1))
            continue
        if bullets:
            flush()
        paragraph.append(line)
    flush()
    if open_section:
        parts.append("</section>")
    return "\n".join(parts)
