-- Support ticket schema for Lakebase (Databricks-managed Postgres).
--
-- Run this ONCE against the Lakebase instance, as a role allowed to create
-- tables (e.g. your own Databricks identity in the SQL Editor). The app itself
-- never runs DDL - it only needs the DML grants at the bottom of this file.

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'in_progress', 'resolved')),
    created_by  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ticket_messages (
    message_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id     BIGINT NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
    message_text  TEXT NOT NULL,
    author        TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ticket_messages_ticket_id ON ticket_messages(ticket_id);


-- Sample data --------------------------------------------------------------

INSERT INTO tickets (title, status, created_by) VALUES
    ('Cannot log into dashboard', 'open', 'alice@example.com'),
    ('Export button not working', 'in_progress', 'bob@example.com'),
    ('Feature request: dark mode', 'resolved', 'carol@example.com'),
    ('Billing charged twice', 'open', 'dave@example.com');

INSERT INTO ticket_messages (ticket_id, message_text, author)
SELECT tickets.ticket_id, msg.message_text, msg.author
FROM tickets
JOIN (VALUES
    ('Cannot log into dashboard', 'I get an "invalid credentials" error even with the right password.', 'alice@example.com'),
    ('Cannot log into dashboard', 'Can you confirm which browser you are using?', 'support@example.com'),
    ('Export button not working', 'Clicking Export does nothing, no download starts.', 'bob@example.com'),
    ('Export button not working', 'We have reproduced this and are working on a fix.', 'support@example.com'),
    ('Feature request: dark mode', 'Would love a dark mode option in settings.', 'carol@example.com'),
    ('Feature request: dark mode', 'Dark mode has shipped in the latest release.', 'support@example.com'),
    ('Billing charged twice', 'I was charged twice for my subscription this month.', 'dave@example.com'),
    ('Billing charged twice', 'Can you share the last 4 digits of the card and the charge dates?', 'support@example.com')
) AS msg(title, message_text, author)
    ON tickets.title = msg.title;


-- Grants for the app's Postgres role ---------------------------------------
-- The app connects as a non-owner role, so it needs explicit DML rights.
-- Replace 'employe' if your app role is named differently.

GRANT USAGE ON SCHEMA public TO employe;
GRANT SELECT, INSERT, UPDATE, DELETE ON tickets, ticket_messages TO employe;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO employe;
