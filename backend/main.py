"""
PrePress Server — FastAPI entry point.
Tables are created at startup via SQLAlchemy lifespan event.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import engine, Base
# Import all models so their tables are registered with Base before create_all
import models  # noqa: F401

from routers import jobs, preflight, imposition, repair


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create DB tables on startup (idempotent)
    Base.metadata.create_all(bind=engine)
    yield
    # Nothing to tear down


app = FastAPI(
    title="PrePress Server",
    description="PDF předtisková příprava — imposice, preflight, opravy",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(jobs.router)
app.include_router(preflight.router)
app.include_router(imposition.router)
app.include_router(repair.router)


@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok"}
