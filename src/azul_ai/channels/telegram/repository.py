from uuid import uuid4

from azul_ai.core.db import initialize_session_tables, save_message
from azul_ai.core.agent_runtime import SYSTEM_PROMPT


def initialize_telegram_tables(connection):
    initialize_session_tables(connection)
    with connection.transaction():
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_chat_sessions (
                chat_id TEXT PRIMARY KEY,
                session_id UUID NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_processed_updates (
                update_id BIGINT PRIMARY KEY,
                session_id UUID REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'processing'
                    CHECK (status IN ('processing', 'completed', 'failed')),
                processed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def get_or_create_chat_session(connection, chat_id):
    lock_key = f"telegram:{chat_id}"
    with connection.transaction():
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (lock_key,),
        )
        row = connection.execute(
            "SELECT session_id FROM telegram_chat_sessions WHERE chat_id = %s",
            (chat_id,),
        ).fetchone()
        if row:
            return row[0]

        session_id = uuid4()
        connection.execute(
            "INSERT INTO agent_sessions (session_id) VALUES (%s)",
            (session_id,),
        )
        save_message(connection, session_id, {"role": "system", "content": SYSTEM_PROMPT})
        connection.execute(
            "INSERT INTO telegram_chat_sessions (chat_id, session_id) VALUES (%s, %s)",
            (chat_id, session_id),
        )
        return session_id


def create_new_chat_session(connection, chat_id, old_session_id):
    lock_key = f"telegram:{chat_id}"
    session_id = uuid4()
    with connection.transaction():
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (lock_key,),
        )
        connection.execute(
            "INSERT INTO agent_sessions (session_id) VALUES (%s)",
            (session_id,),
        )
        save_message(connection, session_id, {"role": "system", "content": SYSTEM_PROMPT})
        cursor = connection.execute(
            """
            UPDATE telegram_chat_sessions
            SET session_id = %s
            WHERE chat_id = %s AND session_id = %s
            """,
            (session_id, chat_id, old_session_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Unable to switch the Telegram chat to a new session.")
    return session_id
