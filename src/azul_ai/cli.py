import argparse
from uuid import UUID

from .core.agent import DEFAULT_SYSTEM_PROMPT
from .core.db import (
    connect_to_database,
    create_session,
    delete_stale_sessions,
    initialize_session_tables,
    load_messages,
    record_session_participant,
    resume_session,
    save_message,
)
from .tools.local import list_files, read_file, run_command, write_file


TOOLS = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "run_command": run_command,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "Lists the files in a directory.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Reads a file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Writes a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Runs a shell command after user confirmation.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
]


def main():
    parser = argparse.ArgumentParser(description="Run the Azul AI coding agent.")
    parser.add_argument("--session-id", type=UUID)
    parser.add_argument(
        "--prune-sessions-older-than-days",
        type=int,
        metavar="DAYS",
        help="Delete old sessions unless the preserved user participated in them.",
    )
    parser.add_argument(
        "--keep-platform",
        help="Platform ID for the user whose sessions must be preserved (e.g. slack).",
    )
    parser.add_argument(
        "--keep-user-id",
        help="Stable platform user ID to preserve (Slack IDs look like U...).",
    )
    args = parser.parse_args()

    pruning = args.prune_sessions_older_than_days is not None
    if pruning and (not args.keep_platform or not args.keep_user_id):
        parser.error("--keep-platform and --keep-user-id are required when pruning sessions.")
    if not pruning and (args.keep_platform or args.keep_user_id):
        parser.error("--keep-platform and --keep-user-id require --prune-sessions-older-than-days.")
    if pruning and args.session_id:
        parser.error("--session-id cannot be combined with session pruning.")

    with connect_to_database() as connection:
        initialize_session_tables(connection)
        if pruning:
            deleted_count = delete_stale_sessions(
                connection,
                args.prune_sessions_older_than_days,
                args.keep_platform,
                args.keep_user_id,
            )
            print(f"Deleted {deleted_count} stale session(s).")
            return

        if args.session_id is None:
            session_id = create_session(connection, DEFAULT_SYSTEM_PROMPT)
            record_session_participant(connection, session_id, "cli", "local")
        else:
            resume_session(connection, args.session_id)
            session_id = args.session_id
            record_session_participant(connection, session_id, "cli", "local")

        print(f"Azul AI ready. Session ID: {session_id}")
        while True:
            user_input = input("You: ").strip()
            if user_input.lower() in ("exit", "quit"):
                break
            if not user_input:
                continue
            save_message(connection, session_id, {"role": "user", "content": user_input})
            from .core.agent import run_agent
            print("Agent:", run_agent(
                connection,
                session_id,
                load_messages(connection, session_id),
                TOOL_SCHEMAS,
                TOOLS,
            ))
