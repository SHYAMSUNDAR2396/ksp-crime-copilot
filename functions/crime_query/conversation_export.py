"""Scope-safe conversation export with an injectable PDF renderer."""
import html

try:
    from .policy_audit import scope_safe_export
except ImportError:  # pragma: no cover
    from policy_audit import scope_safe_export


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
