"""Scope-safe conversation export with an injectable PDF renderer."""
import html
import base64

import requests

try:
    from .policy_audit import scope_safe_export
except ImportError:  # pragma: no cover
    from policy_audit import scope_safe_export


class SmartBrowzPdfRenderer:
    """Render verified HTML through Catalyst SmartBrowz PDF & Screenshot."""

    def __init__(self, endpoint, token, timeout=30, transport=None):
        self.endpoint = endpoint
        self.token = token
        self.timeout = timeout
        self.transport = transport or requests

    def render(self, html_document):
        if not self.endpoint or not self.token:
            raise ValueError("SmartBrowz export is not configured")
        encoded = base64.b64encode(html_document.encode("utf-8")).decode("ascii")
        payload = {
            "url": "data:text/html;base64," + encoded,
            "output_options": {"output_type": "pdf"},
            "pdf_options": {
                "format": "A4",
                "print_background": True,
                "margin": {"top": "1cm", "bottom": "1cm", "left": "1cm", "right": "1cm"},
            },
        }
        response = self.transport.post(
            self.endpoint,
            headers={
                "Authorization": "Zoho-oauthtoken " + self.token,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        body = response.content
        if not body.startswith(b"%PDF"):
            raise ValueError("SmartBrowz did not return a PDF")
        return body


def render_conversation_html(rows):
    parts = ["<html><body><main><h1>KSP Crime Copilot conversation</h1>"]
    for row in rows:
        question = html.escape(str(row.get("question", "")))
        answer = html.escape(str(row.get("answer", "")))
        citations = ", ".join(html.escape(str(value)) for value in row.get("citations", ()))
        parts.append("<section><p><strong>Question:</strong> {}</p><p>{}</p><p><small>Citations: {}</small></p></section>".format(
            question, answer, citations,
        ))
    parts.append("</main></body></html>")
    return "".join(parts)


def export_conversation(context, session_id, owner_employee_id, rows, renderer=None):
    safe = scope_safe_export(context, session_id, owner_employee_id, rows)
    if safe.code != "OK":
        return {"code": safe.code, "content_type": "text/plain", "body": ""}
    html_document = render_conversation_html(safe.rows)
    if renderer is None:
        return {"code": "OK", "content_type": "text/html", "body": html_document}
    try:
        pdf = renderer.render(html_document)
    except Exception:
        return {"code": "EXPORT_UNAVAILABLE", "content_type": "text/plain", "body": ""}
    return {"code": "OK", "content_type": "application/pdf", "body": pdf}
