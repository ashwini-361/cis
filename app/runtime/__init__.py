"""Runtime glue — the live-loop wiring that turns an ingest adapter stream
into a ``Verdict`` time-series.

Kept as a package separate from ``app.analyzers`` (the sensors) and
``app.realtime`` (the existing ticker math): runtime = the bus/registry/
scheduler plumbing that was never built in Phases 1–8. Live and the
offline accuracy harness share this exact code path (clock is the seam).
"""
