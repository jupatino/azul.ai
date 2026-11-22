import os
from urllib.parse import parse_qsl, unquote, urlparse
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from .config import ENV_FILE


def connect_to_database():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(f"Set DATABASE_URL in {ENV_FILE}.")

    parsed_url = urlparse(database_url)
    if parsed_url.scheme not in ("postgres", "postgresql") or not parsed_url.hostname or not parsed_url.path.strip("/"):
        raise ValueError("DATABASE_URL must be a PostgreSQL URL with a host and database.")

    host = os.getenv("POSTGRES_HOST")
    if not host:
        host = "localhost" if parsed_url.hostname == "db" else parsed_url.hostname

    return psycopg.connect(
        dbname=os.getenv("POSTGRES_DB") or unquote(parsed_url.path.lstrip("/")),
        user=os.getenv("POSTGRES_USER") or (unquote(parsed_url.username) if parsed_url.username else None),
        password=os.getenv("POSTGRES_PASSWORD") or (unquote(parsed_url.password) if parsed_url.password else None),
        host=host,
        port=parsed_url.port or 5432,
        **dict(parse_qsl(parsed_url.query)),
    )


def initialize_session_tables(connection):
    with connection.transaction():
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_sessions (
                session_id UUID PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_session_messages (
                message_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                session_id UUID NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
                message JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS agent_session_messages_session_idx
            ON agent_session_messages (session_id, message_id)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_session_participants (
                session_id UUID NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
                platform TEXT NOT NULL,
                user_id TEXT NOT NULL,
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (session_id, platform, user_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS agent_session_participants_user_idx
            ON agent_session_participants (platform, user_id, session_id)
            """
        )


def record_session_participant(connection, session_id, platform, user_id):
    if not platform or not user_id:
        raise ValueError("A platform and stable user ID are required to record a session participant.")

    with connection.transaction():
        connection.execute(
            """
            INSERT INTO agent_session_participants (session_id, platform, user_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (session_id, platform, user_id)
            DO UPDATE SET last_seen_at = CURRENT_TIMESTAMP
            """,
            (session_id, platform, user_id),
        )


def delete_stale_sessions(connection, older_than_days, keep_platform, keep_user_id):
    if isinstance(older_than_days, bool) or older_than_days < 1:
        raise ValueError("older_than_days must be a positive integer.")
    if not keep_platform or not keep_user_id:
        raise ValueError("A platform and stable user ID are required to preserve sessions.")

    with connection.transaction():
        cursor = connection.execute(
            """
            DELETE FROM agent_sessions AS sessions
            WHERE sessions.updated_at < CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')
              AND EXISTS (
                  SELECT 1
                  FROM agent_session_participants AS participants
                  WHERE participants.session_id = sessions.session_id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM agent_session_participants AS participants
                  WHERE participants.session_id = sessions.session_id
                    AND participants.platform = %s
                    AND participants.user_id = %s
              )
            """,
            (older_than_days, keep_platform, keep_user_id),
        )
        return cursor.rowcount


def save_message(connection, session_id, message):
    with connection.transaction():
        connection.execute(
            "INSERT INTO agent_session_messages (session_id, message) VALUES (%s, %s)",
            (session_id, Jsonb(message)),
        )
        connection.execute(
            "UPDATE agent_sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = %s",
            (session_id,),
        )


def load_messages(connection, session_id):
    rows = connection.execute(
        """
        SELECT message
        FROM agent_session_messages
        WHERE session_id = %s
        ORDER BY message_id
        """,
        (session_id,),
    ).fetchall()
    return [row[0] for row in rows]


def create_session(connection, system_prompt):
    session_id = uuid4()
    with connection.transaction():
        connection.execute(
            "INSERT INTO agent_sessions (session_id) VALUES (%s)",
            (session_id,),
        )
        save_message(connection, session_id, {"role": "system", "content": system_prompt})
    return session_id


def resume_session(connection, session_id):
    row = connection.execute(
        "SELECT 1 FROM agent_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Session {session_id} does not exist.")
