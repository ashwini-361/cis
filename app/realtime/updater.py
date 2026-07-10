"""ParticipantState updater — out of scope for v1.0.

In v1.0 the ticker (app.realtime.ticker) owns the update loop directly.
A dedicated updater abstraction is deferred to a future phase when the
update logic needs to be shared across multiple callers.
"""
