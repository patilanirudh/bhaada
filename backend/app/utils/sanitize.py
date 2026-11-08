import html

import nh3

ALLOWED_TAGS = {"p", "br", "b", "strong", "i", "em", "u", "ul", "ol", "li", "h3", "h4", "div", "span"}


def sanitize_html(value: str | None) -> str | None:
    if value is None:
        return None
    return nh3.clean(value, tags=ALLOWED_TAGS, attributes={})


def html_to_text(value: str | None) -> str:
    """Rough plain-text rendering of the rich text house rules."""
    if not value:
        return ""
    text = value
    for tag in ("<br>", "<br/>", "<br />", "</p>", "</div>", "</li>", "</h3>", "</h4>"):
        text = text.replace(tag, "\n")
    text = text.replace("<li>", "• ")
    text = nh3.clean(text, tags=set())
    lines = [html.unescape(line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
