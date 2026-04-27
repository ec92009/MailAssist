from __future__ import annotations

import html
import re


_ALLOWED_TAGS = {
    "a",
    "b",
    "br",
    "blockquote",
    "div",
    "em",
    "i",
    "li",
    "ol",
    "p",
    "strong",
    "hr",
    "u",
    "ul",
}


def sanitize_html_fragment(value: str) -> str:
    """Keep a small email-safe HTML subset for signatures and draft bodies."""
    text = (value or "").strip()
    if not text:
        return ""
    text = re.sub(r"(?is)<\s*(script|style)[^>]*>.*?<\s*/\s*\1\s*>", "", text)
    text = re.sub(r"(?is)\s+on[a-z]+\s*=\s*(['\"]).*?\1", "", text)
    text = re.sub(r"(?is)\s+on[a-z]+\s*=\s*[^\s>]+", "", text)
    text = re.sub(r"(?is)\s+style\s*=\s*(['\"]).*?\1", "", text)
    text = re.sub(r"(?is)\s+style\s*=\s*[^\s>]+", "", text)

    def replace_tag(match: re.Match[str]) -> str:
        slash, tag_name, raw_attrs = match.group(1), match.group(2).lower(), match.group(3) or ""
        if tag_name not in _ALLOWED_TAGS:
            return ""
        if slash:
            return f"</{tag_name}>"
        if tag_name == "a":
            href_match = re.search(r"""(?is)\bhref\s*=\s*(['"])(.*?)\1""", raw_attrs)
            href = href_match.group(2).strip() if href_match else ""
            if href and re.match(r"(?i)^(https?:|mailto:)", href):
                return f'<a href="{html.escape(href, quote=True)}">'
            return "<a>"
        if tag_name == "br":
            return "<br>"
        return f"<{tag_name}>"

    return re.sub(r"(?is)<\s*(/?)\s*([a-z0-9]+)([^>]*)>", replace_tag, text).strip()


def html_to_plain_text(value: str) -> str:
    text = sanitize_html_fragment(value)
    if not text:
        return ""
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", text)
    text = re.sub(r"(?i)</\s*(p|div|li|tr|h[1-6])\s*>", "\n", text)
    text = re.sub(r"(?i)<\s*li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    collapsed: list[str] = []
    for line in lines:
        if line or (collapsed and collapsed[-1]):
            collapsed.append(line)
    return "\n".join(collapsed).strip()


def plain_text_to_html(value: str) -> str:
    paragraphs = []
    for block in re.split(r"\n{2,}", (value or "").strip()):
        lines = [html.escape(line) for line in block.splitlines()]
        paragraphs.append("<p>" + "<br>".join(lines) + "</p>")
    return "".join(paragraphs)


def attribution_text(model: str) -> str:
    cleaned_model = (model or "local model").strip()
    return f"Draft prepared by MailAssist using Ollama model {cleaned_model}."


def attribution_html(model: str) -> str:
    return f"<p><em>{html.escape(attribution_text(model))}</em></p>"
