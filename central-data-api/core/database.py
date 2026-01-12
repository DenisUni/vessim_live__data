from contextlib import contextmanager
from datetime import datetime, timezone

from core.config import settings
from core.logger import setup_logger
from sqlmodel import SQLModel, create_engine, Field, Session

logger = setup_logger(__name__, "DATABASE")

# Create database engine (uses URL from configuration)
engine = create_engine(settings.DATABASE_URL, echo=False)


def configure_sqlalchemy_logging():
    """Re-Configure all SQLAlchemy loggers"""

    # List of all relevant SQLAlchemy loggers
    sqla_loggers = [
        'sqlalchemy.engine',
        'sqlalchemy.pool',
        'sqlalchemy.orm',
        'sqlalchemy.dialects'
    ]

    # Mapping for more attractive display names
    display_names = {
        'sqlalchemy.engine': 'SQL-ENGINE',
        'sqlalchemy.pool': 'SQL-POOL',
        'sqlalchemy.orm': 'SQL-ORM',
        'sqlalchemy.dialects': 'SQL-DIALECTS'
    }

    for logger_name in sqla_loggers:
        # Setup with a specific display name
        display_name = display_names.get(logger_name, logger_name.upper())
        setup_logger(logger_name, display_name)

        # Debug output for confirmation
        logger.debug(f"SQLAlchemy Logger '{logger_name}' re-configured.")


# Call up the function
configure_sqlalchemy_logging()


# Basic model with timestamp
class TimeStampedModel(SQLModel):
    """Base class for all tables that contain timestamps."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), nullable=False, index=True)


# IMPORTANT: Function for FastAPI Dependency
@contextmanager
def get_managed_session():
    """
    FastAPI Dependency, which provides a database session for each request.
    Context manager for database sessions with auto-commit/rollback.
    Usage: with get_managed_session() as session: ...
    """
    session = Session(engine)
    try:
        yield session
        session.commit()  # Auto-commit on success
    except Exception:
        session.rollback()  # Automatic rollback in case of errors
        raise
    finally:
        session.close()  # Always close


# Helper function for creating all tables (for tests/scripts)
def create_all_tables():
    """Creates all tables in the database."""
    SQLModel.metadata.create_all(engine)


def dispose_engine():
    """Disposes the database engine and closes all connections."""
    global engine
    if engine:
        logger.info("Disposing engine...")
        engine.dispose()  # Important: Empties the connection pool
        logger.info("Engine disposed.")
