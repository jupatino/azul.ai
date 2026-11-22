from uuid import uuid4

from azul_ai.core.agent_runtime import SYSTEM_PROMPT
from azul_ai.core.db import initialize_session_tables, save_message


def initialize_slack_tables(connection):
    initialize_session_tables(connection)
    with connection.transaction():
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS slack_thread_sessions (
                team_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                thread_ts TEXT NOT NULL,
                session_id UUID NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
                PRIMARY KEY (team_id, channel_id, thread_ts)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS slack_processed_events (
                event_id TEXT PRIMARY KEY,
                session_id UUID REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'processing'
                    CHECK (status IN ('processing', 'completed', 'failed')),
                processed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def get_or_create_thread_session(connection, team_id, channel_id, thread_ts):
    lock_key = f"{team_id}:{channel_id}:{thread_ts}"
    with connection.transaction():
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (lock_key,),
        )
        row = connection.execute(
            """
            SELECT session_id
            FROM slack_thread_sessions
            WHERE team_id = %s AND channel_id = %s AND thread_ts = %s
            """,
            (team_id, channel_id, thread_ts),
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
            """
            INSERT INTO slack_thread_sessions (team_id, channel_id, thread_ts, session_id)
            VALUES (%s, %s, %s, %s)
            """,
            (team_id, channel_id, thread_ts, session_id),
        )
        return session_id


def get_command_session(connection, team_id, channel_id):
    direct_message = channel_id.startswith("D")
    thread_key = "direct-message" if direct_message else None
    lock_key = f"{team_id}:{channel_id}:session-command"

    with connection.transaction():
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (lock_key,),
        )
        if direct_message:
            row = connection.execute(
                """
                SELECT thread_ts, session_id
                FROM slack_thread_sessions
                WHERE team_id = %s AND channel_id = %s AND thread_ts = %s
                """,
                (team_id, channel_id, thread_key),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT sts.thread_ts, sts.session_id
                FROM slack_thread_sessions AS sts
                JOIN agent_sessions AS sessions USING (session_id)
                WHERE sts.team_id = %s AND sts.channel_id = %s
                ORDER BY sessions.updated_at DESC
                LIMIT 1
                """,
                (team_id, channel_id),
            ).fetchone()

        if row:
            return row[0], row[1]
        if not direct_message:
            raise ValueError("There is no agent session in this channel yet.")

        session_id = uuid4()
        connection.execute(
            "INSERT INTO agent_sessions (session_id) VALUES (%s)",
            (session_id,),
        )
        save_message(connection, session_id, {"role": "system", "content": SYSTEM_PROMPT})
        connection.execute(
            """
            INSERT INTO slack_thread_sessions (team_id, channel_id, thread_ts, session_id)
            VALUES (%s, %s, %s, %s)
            """,
            (team_id, channel_id, thread_key, session_id),
        )
        return thread_key, session_id


def create_new_session(connection, team_id, channel_id, thread_key, old_session_id):
    session_id = uuid4()
    with connection.transaction():
        connection.execute(
            "INSERT INTO agent_sessions (session_id) VALUES (%s)",
            (session_id,),
        )
        save_message(connection, session_id, {"role": "system", "content": SYSTEM_PROMPT})
        cursor = connection.execute(
            """
            UPDATE slack_thread_sessions
            SET session_id = %s
            WHERE team_id = %s AND channel_id = %s AND thread_ts = %s
              AND session_id = %s
            """,
            (session_id, team_id, channel_id, thread_key, old_session_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Unable to switch the conversation to a new session.")
    return session_id
