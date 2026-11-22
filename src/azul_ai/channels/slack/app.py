import json
import logging
import os
import re

from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler

from azul_ai.channels.base import IncomingMessage
from azul_ai.core.db import connect_to_database, record_session_participant
from azul_ai.core.session import AgentSessionService
from azul_ai.core.config import PROJECT_DIR
from azul_ai.channels.slack.repository import (
    SYSTEM_PROMPT,
    create_new_session,
    get_command_session,
    get_or_create_thread_session,
    initialize_slack_tables,
    refresh_session_system_prompt,
)
from azul_ai.tools.skills import SkillsTools


logger = logging.getLogger(__name__)

bot_token = os.getenv("SLACK_BOT_TOKEN")
signing_secret = os.getenv("SLACK_SIGNING_SECRET")
allowed_user_ids = {
    user_id.strip()
    for user_id in os.getenv("SLACK_ALLOWED_USER_IDS", "").split(",")
    if user_id.strip()
}
if not bot_token or not signing_secret:
    raise RuntimeError("Set SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET in .env.")
if not allowed_user_ids:
    raise RuntimeError("Set SLACK_ALLOWED_USER_IDS to one or more Slack user IDs in .env.")

slack_app = App(
    token=bot_token,
    signing_secret=signing_secret,
    token_verification_enabled=False,
)
flask_app = Flask(__name__)
request_handler = SlackRequestHandler(slack_app)

skills_dir = os.getenv("AZUL_AGENT_SKILLS_DIR", PROJECT_DIR / "skills")
skills = SkillsTools(skills_dir)
TOOLS = {
    "list_files": skills.list_files,
    "read_file": skills.read_file,
    "write_file": skills.write_file,
    "run_command": skills.run_command,
}
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }
    for name, description, properties, required in (
        ("list_files", "Lists files inside the persistent skills directory only.",
         {"path": {"type": "string"}}, ["path"]),
        ("read_file", "Reads a file inside the persistent skills directory only.",
         {"path": {"type": "string"}}, ["path"]),
        ("write_file", "Creates or replaces a file inside the persistent skills directory only.",
         {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
        ("run_command", "Runs pwd or ls in the persistent skills directory.",
         {"command": {"type": "string"}}, ["command"]),
    )
]

session_service = AgentSessionService(SYSTEM_PROMPT, TOOL_SCHEMAS, TOOLS)


def normalize_slack_message(body, event):
    user_id = event.get("user")
    text = re.sub(r"<@[A-Z0-9]+>", "", event.get("text", "")).strip()
    team_id = body.get("team_id") or event.get("team")
    channel_id = event.get("channel")
    is_direct_message = event.get("channel_type") == "im"
    thread_id = event.get("thread_ts") or (
        "direct-message" if is_direct_message else event.get("ts")
    )
    event_id = body.get("event_id")
    if not all((team_id, channel_id, thread_id, event_id)):
        raise ValueError("Slack event is missing required identifiers.")
    return IncomingMessage(
        channel="slack",
        sender_id=user_id,
        conversation_id=f"{team_id}:{channel_id}",
        thread_id=thread_id,
        event_id=event_id,
        text=text,
    )


def process_slack_message(body, event):
    message = normalize_slack_message(body, event)
    if message.sender_id not in allowed_user_ids:
        logger.warning("Ignoring Slack message from non-allowlisted user %s", message.sender_id)
        return None
    if not message.text:
        return None

    team_id = body.get("team_id") or event.get("team")
    channel_id = event.get("channel")
    thread_ts = message.thread_id

    with connect_to_database() as connection:
        with connection.transaction():
            inserted = connection.execute(
                "INSERT INTO slack_processed_events (event_id) VALUES (%s) "
                "ON CONFLICT DO NOTHING RETURNING event_id",
                (message.event_id,),
            ).fetchone()
            if inserted is None:
                event_row = connection.execute(
                    "SELECT session_id, status FROM slack_processed_events "
                    "WHERE event_id = %s FOR UPDATE",
                    (message.event_id,),
                ).fetchone()
                session_id, status = event_row
                if status != "failed":
                    return None
                connection.execute(
                    "UPDATE slack_processed_events SET status = 'processing', "
                    "processed_at = CURRENT_TIMESTAMP WHERE event_id = %s",
                    (message.event_id,),
                )
            else:
                session_id = get_or_create_thread_session(
                    connection, team_id, channel_id, thread_ts
                )
                connection.execute(
                    "UPDATE slack_processed_events SET session_id = %s WHERE event_id = %s",
                    (session_id, message.event_id),
                )
            record_session_participant(
                connection,
                session_id,
                message.channel,
                message.sender_id,
            )

        refresh_session_system_prompt(connection, session_id)
        try:
            reply = session_service.process(
                connection,
                session_id,
                message.text,
                append_user_message=inserted is not None,
            )
        except Exception:
            with connection.transaction():
                connection.execute(
                    "UPDATE slack_processed_events SET status = 'failed' WHERE event_id = %s",
                    (message.event_id,),
                )
            raise

        with connection.transaction():
            connection.execute(
                "UPDATE slack_processed_events SET status = 'completed' WHERE event_id = %s",
                (message.event_id,),
            )
        return reply


def run_session_command(body, respond, operation):
    user_id = body.get("user_id")
    if user_id not in allowed_user_ids:
        respond(text="You are not authorized to manage this agent session.", response_type="ephemeral")
        return

    team_id = body.get("team_id")
    channel_id = body.get("channel_id")
    if not team_id or not channel_id:
        respond(text="Slack did not provide the session workspace or conversation.", response_type="ephemeral")
        return

    try:
        with connect_to_database() as connection:
            thread_key, session_id = get_command_session(connection, team_id, channel_id)
            record_session_participant(connection, session_id, "slack", user_id)
            if operation == "reset":
                session_service.reset(connection, session_id)
                response_text = "Session history cleared."
            elif operation == "new":
                session_id = create_new_session(
                    connection, team_id, channel_id, thread_key, session_id
                )
                record_session_participant(connection, session_id, "slack", user_id)
                response_text = "Started a new session."
            elif operation == "compact":
                session_service.compact(connection, session_id)
                response_text = "Session compacted into a concise continuity summary."
            else:
                raise ValueError(f"Unknown session operation: {operation}")
        respond(text=response_text, response_type="ephemeral")
    except Exception:
        logger.exception("Failed to %s Slack session", operation)
        respond(text=f"Couldn't {operation} the session.", response_type="ephemeral")


def handle_message_event(body, event, say, *, direct_message=False):
    if direct_message and (
        event.get("channel_type") != "im"
        or event.get("subtype")
        or event.get("bot_id")
    ):
        return

    reply_thread_ts = event.get("thread_ts")
    if not direct_message:
        reply_thread_ts = reply_thread_ts or event.get("ts")
    try:
        reply = process_slack_message(body, event)
        if reply:
            say(text=reply, **({"thread_ts": reply_thread_ts} if reply_thread_ts else {}))
    except Exception:
        logger.exception("Failed to process Slack event %s", body.get("event_id"))
        say_kwargs = {"text": "I couldn't process that request."}
        if reply_thread_ts:
            say_kwargs["thread_ts"] = reply_thread_ts
        say(**say_kwargs)


@slack_app.event("app_mention")
def handle_app_mention(body, event, say):
    handle_message_event(body, event, say)


@slack_app.event("message")
def handle_direct_message(body, event, say):
    handle_message_event(body, event, say, direct_message=True)


@slack_app.command("/agent-reset")
def handle_agent_reset(ack, body, respond):
    ack()
    run_session_command(body, respond, "reset")


@slack_app.command("/agent-new")
def handle_agent_new(ack, body, respond):
    ack()
    run_session_command(body, respond, "new")


@slack_app.command("/agent-compact")
def handle_agent_compact(ack, body, respond):
    ack()
    run_session_command(body, respond, "compact")


@flask_app.get("/healthz")
def health_check():
    return {"status": "ok"}


@flask_app.post("/slack/events")
def slack_events():
    return request_handler.handle(request)


with connect_to_database() as connection:
    initialize_slack_tables(connection)
