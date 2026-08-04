# Support Desk — a Lakebase-backed Databricks App

An internal support ticket system deployed as a Databricks App. Users can open
support tickets, hold a threaded conversation on each one, and move tickets
through a status workflow. All operational data lives in **Lakebase**
(Databricks-managed Postgres) — nothing is hard-coded or held in memory.

## Features

- **View all tickets**, newest first, with live counts per status
- **Filter by status** (`open` / `in_progress` / `resolved`) — filtering runs as a
  SQL `WHERE` clause in Lakebase, not in the browser
- **Select a ticket** to read its full message thread
- **Create a ticket** together with its opening message, written in a single
  transaction so a ticket can never exist without one
- **Add messages** to an existing ticket
- **Update a ticket's status**
- Email addresses are validated in the browser *and* re-validated server-side,
  since the API can be called directly

## Architecture

```
Browser (templates/index.html)
    |  fetch() JSON
    v
Flask app (app.py)              <- runs as a Databricks App service principal
    |  psycopg2
    v
Lakebase / Postgres (tickets, ticket_messages)
```

Credentials are never stored in code. `lakebase.py` reads the Postgres
connection URL at runtime from a Databricks secret using the workspace SDK.
`app.yaml` only names the scope and key to read — it holds no secret value:

| Env var                 | Value                  |
| ----------------------- | ---------------------- |
| `LAKEBASE_SECRET_SCOPE` | `tickets-app-database` |
| `LAKEBASE_SECRET_KEY`   | `lakebase-url`         |

The app never runs DDL. The schema is created once by `schema.sql`, so the
app's Postgres role needs only `SELECT`/`INSERT`/`UPDATE` rights — not table
ownership.

## Files

| File                   | Purpose                                                       |
| ---------------------- | ------------------------------------------------------------- |
| `app.py`               | Flask routes for the UI and the ticket/message JSON API        |
| `lakebase.py`          | Lakebase connection helper (secret lookup, query/write helpers) |
| `templates/index.html` | Single-page UI (vanilla JS, no build step)                    |
| `schema.sql`           | Table definitions, sample data, and the app role's grants      |
| `setup_secrets.py`     | One-time script to store the connection URL as a secret        |
| `app.yaml`             | Databricks Apps deployment config                             |
| `requirements.txt`     | Python dependencies                                           |

## Data model

`ticket_messages.ticket_id` is a foreign key to `tickets.ticket_id`, so deleting
a ticket removes its messages (`ON DELETE CASCADE`).

**tickets**

| Column       | Type          | Notes                                        |
| ------------ | ------------- | -------------------------------------------- |
| `ticket_id`  | `BIGINT`      | primary key, generated as identity           |
| `title`      | `TEXT`        | not null                                     |
| `status`     | `TEXT`        | `open` / `in_progress` / `resolved` (checked) |
| `created_by` | `TEXT`        | email of the person who opened the ticket    |
| `created_at` | `TIMESTAMPTZ` | defaults to `now()`                          |

**ticket_messages**

| Column         | Type          | Notes                              |
| -------------- | ------------- | ---------------------------------- |
| `message_id`   | `BIGINT`      | primary key, generated as identity |
| `ticket_id`    | `BIGINT`      | foreign key → `tickets.ticket_id`  |
| `message_text` | `TEXT`        | not null                           |
| `author`       | `TEXT`        | email of the message author        |
| `created_at`   | `TIMESTAMPTZ` | defaults to `now()`                |

## Setup

### 1. Create a Lakebase instance and a password role

1. In the Databricks workspace, open **Compute** → **Lakebase** (or search for
   "Lakebase") and create a database instance. Wait for it to become
   **Available**.
2. Open the instance's **Roles & Databases** tab and enable native (password)
   authentication if it isn't already on.
3. Create a role for the app (this project uses `employe`) with a generated
   password, and copy the connection URL it gives you:

   ```
   postgresql://<role>:<password>@<host>.database.cloud.databricks.com:5432/databricks_postgres?sslmode=require
   ```

### 2. Store the connection URL as a secret

Run `setup_secrets.py` from a Databricks notebook. It prompts via `getpass`, so
the URL is never echoed, written to disk, or left in shell history:

```python
%run ./setup_secrets.py
```

This creates the `tickets-app-database` scope and stores the URL under the
`lakebase-url` key.

### 3. Create the schema, sample data, and grants

Run `schema.sql` against the instance — from the SQL Editor with the Lakebase
instance selected, or via `psql`. It creates both tables, inserts sample
tickets and messages, and grants the app's role the DML rights it needs.

Run it as a role allowed to create tables (for example your own Databricks
identity). The `GRANT` statements at the bottom must be run **by the table
owner**, otherwise the app will fail with `permission denied for table tickets`.

### 4. Deploy

Push this repository to GitHub, then in **Compute** → **Apps** create an app
pointing at the repo (or at a Databricks Git folder containing it). Databricks
reads `app.yaml` to start the app. Redeploy from the Apps UI after each push.

## API

| Method  | Path                            | Purpose                                     |
| ------- | ------------------------------- | ------------------------------------------- |
| `GET`   | `/`                             | The ticket UI                               |
| `GET`   | `/healthz`                      | Health check                                |
| `GET`   | `/api/tickets`                  | List tickets; optional `?status=<status>`   |
| `GET`   | `/api/tickets/stats`            | Ticket counts per status                    |
| `POST`  | `/api/tickets`                  | Create a ticket and its opening message     |
| `GET`   | `/api/tickets/<id>/messages`    | List a ticket's messages                    |
| `POST`  | `/api/tickets/<id>/messages`    | Add a message to a ticket                   |
| `PATCH` | `/api/tickets/<id>/status`      | Update a ticket's status                    |

Create a ticket:

```bash
curl -X POST /api/tickets -H "Content-Type: application/json" -d '{
  "title": "Cannot log into dashboard",
  "created_by": "alice@example.com",
  "first_message": "I get an invalid credentials error even with the right password.",
  "status": "open"
}'
```

## Security notes

- No passwords, connection strings, or API keys appear in this repository. The
  connection URL lives only in the Databricks secret store.
- `.env` is gitignored; `.env.example` contains no real values.
- All SQL uses parameterised queries, so user input is never string-interpolated
  into a statement.
- User-supplied text is HTML-escaped before rendering.
