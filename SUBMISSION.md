# Day 1 Homework — Lakebase-Powered Support App

**Name:** Ahmed Chelly
**Submitted:** <!-- fill in date -->

---

## 1. Databricks App URL

https://tickets-app-7474652890818214.aws.databricksapps.com

## 2. Source code

Attached as `tickets-app.zip`.
Repository: https://github.com/ahmed-chelly/tickets-app

---

## 3. Reflection

The most difficult part was getting the Lakebase permissions right. My app
connects as a different Postgres role than the one that created the tables, and
because PostgreSQL checks table ownership *before* it evaluates `IF NOT EXISTS`,
the app's `CREATE INDEX IF NOT EXISTS` call failed with "must be owner of table
ticket_messages" even though the index already existed — so every create,
message, and status update broke at once. I fixed it by removing all DDL from
the application and granting its role only the `SELECT`/`INSERT`/`UPDATE` rights
it actually needs, which is better practice anyway since an app shouldn't be
altering its own schema on every request. Lakebase differs from a traditional
analytics table because it is a real OLTP Postgres database: it enforces primary
and foreign keys, supports transactions, and serves single-row reads and writes
in milliseconds, whereas a Delta analytics table is columnar and built for large
scans and appends, doesn't enforce referential integrity, and isn't designed for
the per-row updates an application performs on every click. The feature I would
add next is image attachments, so a user can attach a screenshot of the problem
to a ticket or a message — in a support system a picture usually explains the
issue far faster than a written description, and it would give the AI agent
projects later in the boot camp a second kind of context to reason over.

---

## Requirements checklist

| # | Requirement | Status |
| - | ----------- | ------ |
| 1 | Two related tables (`ticket_messages.ticket_id` → `tickets.ticket_id`) | Done |
| 2 | ≥3 tickets, ≥2 messages each, ≥2 statuses | Done |
| 3 | View tickets / view messages / create / add message / update status | Done |
| 4 | Deployed on Databricks Apps, changes persist across refresh | Done |
| — | No credentials in source (secret scope `tickets-app-database`) | Done |
