"""Safe Markdown → HTML rendering pipeline."""
import bleach
from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])

_ALLOWED_TAGS = [
    "p", "br", "h1", "h2", "h3", "h4", "h5", "h6",
    "strong", "em", "del", "code", "pre", "blockquote",
    "ul", "ol", "li", "a", "img", "table", "thead",
    "tbody", "tr", "th", "td", "hr", "span", "div",
    "input",  # for GFM task lists
]
_ALLOWED_ATTRS = {
    "a": ["href", "title", "rel"],
    "img": ["src", "alt", "title"],
    "code": ["class"],
    "input": ["type", "checked", "disabled"],
}


def render_markdown(md_text: str) -> str:
    """Convert Markdown to sanitized HTML."""
    if not md_text:
        return ""
    raw_html = _md.render(md_text)
    return bleach.clean(raw_html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS)
