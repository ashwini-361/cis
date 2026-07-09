"""FastAPI entrypoint — session bootstrap and CLI (--scenario) land in later phases."""
from fastapi import FastAPI

app = FastAPI(title="cis")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}
