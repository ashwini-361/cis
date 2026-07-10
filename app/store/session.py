"""PostgresSessionStore — out of scope for v1.0.

In v1.0 sessions live in-memory inside SessionManager (app.session).
A Postgres-backed store is deferred to a future phase when persistence
across restarts is required.
"""
