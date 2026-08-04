"""
Databricks App: Lakebase-backed internal support ticket system.

Routes:
    GET   /                          - ticket UI
    GET   /healthz                   - health check
    GET   /api/tickets                - list all tickets
    POST  /api/tickets                - create a ticket
    GET   /api/tickets/<id>/messages  - list messages for a ticket
    POST  /api/tickets/<id>/messages  - add a message to a ticket
    PATCH /api/tickets/<id>/status    - update a ticket's status

Run locally:
    python app.py
Deploy as a Databricks App using app.yaml.
"""

import logging
import os

from flask import Flask, abort, jsonify, render_template, request

import lakebase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tickets-app")

app = Flask(__name__)

ALLOWED_STATUSES = ("open", "in_progress", "resolved")


def ensure_schema():
    """Create the tickets/ticket_messages tables if they don't exist yet."""
    lakebase.run_write(
        """
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            title       TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'in_progress', 'resolved')),
            created_by  TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    lakebase.run_write(
        """
        CREATE TABLE IF NOT EXISTS ticket_messages (
            message_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            ticket_id     BIGINT NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
            message_text  TEXT NOT NULL,
            author        TEXT NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    lakebase.run_write(
        "CREATE INDEX IF NOT EXISTS idx_ticket_messages_ticket_id ON ticket_messages(ticket_id)"
    )


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
    ensure_schema()
    rows = lakebase.run_query(
        "SELECT ticket_id, title, status, created_by, created_at "
        "FROM tickets ORDER BY created_at DESC"
    )
    return jsonify(rows)


@app.route("/api/tickets", methods=["POST"])
def create_ticket():
    ensure_schema()
    data = request.get_json(force=True, silent=True) or {}

    title = (data.get("title") or "").strip()
    created_by = (data.get("created_by") or "").strip()
    status = (data.get("status") or "open").strip()

    if not title:
        return jsonify({"error": "title is required"}), 400
    if not created_by:
        return jsonify({"error": "created_by is required"}), 400
    if status not in ALLOWED_STATUSES:
        return jsonify({"error": f"status must be one of {ALLOWED_STATUSES}"}), 400

    rows = lakebase.run_write_returning(
        """
        INSERT INTO tickets (title, status, created_by)
        VALUES (%s, %s, %s)
        RETURNING ticket_id, title, status, created_by, created_at
        """,
        (title, status, created_by),
    )
    return jsonify(rows[0]), 201


@app.route("/api/tickets/<int:ticket_id>/messages", methods=["GET"])
def list_messages(ticket_id):
    ensure_schema()
    ticket = lakebase.run_query(
        "SELECT ticket_id FROM tickets WHERE ticket_id = %s", (ticket_id,)
    )
    if not ticket:
        abort(404, description=f"Ticket {ticket_id} not found")

    rows = lakebase.run_query(
        "SELECT message_id, ticket_id, message_text, author, created_at "
        "FROM ticket_messages WHERE ticket_id = %s ORDER BY created_at ASC",
        (ticket_id,),
    )
    return jsonify(rows)


@app.route("/api/tickets/<int:ticket_id>/messages", methods=["POST"])
def add_message(ticket_id):
    ensure_schema()
    data = request.get_json(force=True, silent=True) or {}

    message_text = (data.get("message_text") or "").strip()
    author = (data.get("author") or "").strip()

    if not message_text:
        return jsonify({"error": "message_text is required"}), 400
    if not author:
        return jsonify({"error": "author is required"}), 400

    ticket = lakebase.run_query(
        "SELECT ticket_id FROM tickets WHERE ticket_id = %s", (ticket_id,)
    )
    if not ticket:
        abort(404, description=f"Ticket {ticket_id} not found")

    rows = lakebase.run_write_returning(
        """
        INSERT INTO ticket_messages (ticket_id, message_text, author)
        VALUES (%s, %s, %s)
        RETURNING message_id, ticket_id, message_text, author, created_at
        """,
        (ticket_id, message_text, author),
    )
    return jsonify(rows[0]), 201


@app.route("/api/tickets/<int:ticket_id>/status", methods=["PATCH"])
def update_status(ticket_id):
    ensure_schema()
    data = request.get_json(force=True, silent=True) or {}
    status = (data.get("status") or "").strip()

    if status not in ALLOWED_STATUSES:
        return jsonify({"error": f"status must be one of {ALLOWED_STATUSES}"}), 400

    rows = lakebase.run_write_returning(
        """
        UPDATE tickets SET status = %s
        WHERE ticket_id = %s
        RETURNING ticket_id, title, status, created_by, created_at
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
