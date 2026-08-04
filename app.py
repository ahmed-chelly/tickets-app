"""
Databricks App: Lakebase-backed internal support ticket system.

The tickets/ticket_messages schema is created once by schema.sql, not by this
app - the app's Postgres role only needs DML rights, not table ownership.

Routes:
    GET   /                           - ticket UI
    GET   /healthz                    - health check
    GET   /api/tickets                - list tickets, optionally ?status=<status>
    GET   /api/tickets/stats          - ticket counts per status
    POST  /api/tickets                - create a ticket plus its opening message
    GET   /api/tickets/<id>/messages  - list messages for a ticket
    POST  /api/tickets/<id>/messages  - add a message to a ticket
    PATCH /api/tickets/<id>/status    - update a ticket's status

Run locally:
    python app.py
Deploy as a Databricks App using app.yaml.
"""

import logging
import os
import re

from flask import Flask, abort, jsonify, render_template, request

import lakebase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tickets-app")

app = Flask(__name__)

ALLOWED_STATUSES = ("open", "in_progress", "resolved")

# Deliberately stricter than the browser's type="email", which accepts
# things like "a@b". Requires a dotted domain with a 2+ letter suffix.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)*\.[A-Za-z]{2,}$")

TICKET_COLUMNS = "ticket_id, title, status, created_by, created_at"
MESSAGE_COLUMNS = "message_id, ticket_id, message_text, author, created_at"


def _is_email(value: str) -> bool:
    return bool(_EMAIL_RE.match(value))


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.errorhandler(Exception)
def handle_exception(err):
    """Ensure all unhandled errors return JSON (not an HTML error page),
    so the frontend's resp.json() call never chokes on HTML."""
    logger.exception("Unhandled exception while processing request")
    status_code = getattr(err, "code", 500)
    if not isinstance(status_code, int):
        status_code = 500
    return jsonify({"error": str(err)}), status_code


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/tickets", methods=["GET"])
def list_tickets():
    """List tickets, newest first. Filtering happens in SQL, not the browser."""
    status = request.args.get("status")

    if status and status not in ALLOWED_STATUSES:
        return jsonify({"error": f"status must be one of {ALLOWED_STATUSES}"}), 400

    if status:
        rows = lakebase.run_query(
            f"SELECT {TICKET_COLUMNS} FROM tickets WHERE status = %s "
            f"ORDER BY created_at DESC",
            (status,),
        )
    else:
        rows = lakebase.run_query(
            f"SELECT {TICKET_COLUMNS} FROM tickets ORDER BY created_at DESC"
        )
    return jsonify(rows)


@app.route("/api/tickets/stats", methods=["GET"])
def ticket_stats():
    """Counts per status, used for the filter bar."""
    rows = lakebase.run_query(
        "SELECT status, COUNT(*) AS count FROM tickets GROUP BY status"
    )
    counts = {row["status"]: row["count"] for row in rows}
    by_status = {status: counts.get(status, 0) for status in ALLOWED_STATUSES}
    return jsonify({"total": sum(by_status.values()), "by_status": by_status})


@app.route("/api/tickets", methods=["POST"])
def create_ticket():
    """Create a ticket together with its opening message.

    Both inserts share one transaction so a ticket can never be left
    without the message that describes it.
    """
    data = request.get_json(force=True, silent=True) or {}

    title = (data.get("title") or "").strip()
    created_by = (data.get("created_by") or "").strip()
    status = (data.get("status") or "open").strip()
    first_message = (data.get("first_message") or "").strip()

    if not title:
        return jsonify({"error": "title is required"}), 400
    if not _is_email(created_by):
        return jsonify({"error": "created_by must be a valid email address"}), 400
    if not first_message:
        return jsonify({"error": "first_message is required"}), 400
    if status not in ALLOWED_STATUSES:
        return jsonify({"error": f"status must be one of {ALLOWED_STATUSES}"}), 400

    with lakebase.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO tickets (title, status, created_by)
                VALUES (%s, %s, %s)
                RETURNING {TICKET_COLUMNS}
                """,
                (title, status, created_by),
            )
            ticket = cur.fetchone()
            cur.execute(
                """
                INSERT INTO ticket_messages (ticket_id, message_text, author)
                VALUES (%s, %s, %s)
                """,
                (ticket["ticket_id"], first_message, created_by),
            )
            conn.commit()

    return jsonify(ticket), 201


@app.route("/api/tickets/<int:ticket_id>/messages", methods=["GET"])
def list_messages(ticket_id):
    ticket = lakebase.run_query(
        "SELECT ticket_id FROM tickets WHERE ticket_id = %s", (ticket_id,)
    )
    if not ticket:
        abort(404, description=f"Ticket {ticket_id} not found")

    rows = lakebase.run_query(
        f"SELECT {MESSAGE_COLUMNS} FROM ticket_messages WHERE ticket_id = %s "
        f"ORDER BY created_at ASC",
        (ticket_id,),
    )
    return jsonify(rows)


@app.route("/api/tickets/<int:ticket_id>/messages", methods=["POST"])
def add_message(ticket_id):
    data = request.get_json(force=True, silent=True) or {}

    message_text = (data.get("message_text") or "").strip()
    author = (data.get("author") or "").strip()

    if not message_text:
        return jsonify({"error": "message_text is required"}), 400
    if not _is_email(author):
        return jsonify({"error": "author must be a valid email address"}), 400

    ticket = lakebase.run_query(
        "SELECT ticket_id FROM tickets WHERE ticket_id = %s", (ticket_id,)
    )
    if not ticket:
        abort(404, description=f"Ticket {ticket_id} not found")

    rows = lakebase.run_write_returning(
        f"""
        INSERT INTO ticket_messages (ticket_id, message_text, author)
        VALUES (%s, %s, %s)
        RETURNING {MESSAGE_COLUMNS}
        """,
        (ticket_id, message_text, author),
    )
    return jsonify(rows[0]), 201


@app.route("/api/tickets/<int:ticket_id>/status", methods=["PATCH"])
def update_status(ticket_id):
    data = request.get_json(force=True, silent=True) or {}
    status = (data.get("status") or "").strip()

    if status not in ALLOWED_STATUSES:
        return jsonify({"error": f"status must be one of {ALLOWED_STATUSES}"}), 400

    rows = lakebase.run_write_returning(
        f"""
        UPDATE tickets SET status = %s
        WHERE ticket_id = %s
        RETURNING {TICKET_COLUMNS}
        """,
        (status, ticket_id),
    )
    if not rows:
        abort(404, description=f"Ticket {ticket_id} not found")

    return jsonify(rows[0])


if __name__ == '__main__':
    host = os.getenv('FLASK_RUN_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_RUN_PORT', 8000))
    app.run(debug=True, host=host, port=port)
