"""Database connection and schema setup."""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "schema.sql"


def connect() -> psycopg.Connection:
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
    return psycopg.connect(url)


def init_schema(conn: psycopg.Connection) -> None:
    """Create tables if they don't exist. Safe to run every time."""
    conn.execute(SCHEMA_FILE.read_text())
    conn.commit()


def connect_with_vectors() -> psycopg.Connection:
    """Connection that reads/writes pgvector columns as numpy arrays."""
    from pgvector.psycopg import register_vector

    conn = connect()
    init_schema(conn)
    register_vector(conn)
    return conn


if __name__ == "__main__":
    with connect() as conn:
        init_schema(conn)
    print("Schema is ready.")
