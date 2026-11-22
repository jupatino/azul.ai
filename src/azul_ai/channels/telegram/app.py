import asyncio
import logging
import os

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from azul_ai.channels.base import IncomingMessage
from azul_ai.core.agent_runtime import build_session_service
from azul_ai.core.config import get_required
from azul_ai.core.db import connect_to_database, record_session_participant
from azul_ai.channels.telegram.repository import (
    create_new_chat_session,
    get_or_create_chat_session,
    initialize_telegram_tables,
)


logger = logging.getLogger(__name__)
TELEGRAM_MAX_MESSAGE_LENGTH = 4096


def configured_user_ids():
    values = {
        value.strip()
        for value in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",")
        if value.strip()
    }
    if not all(value.isdecimal() for value in values):
        raise ValueError("TELEGRAM_ALLOWED_USER_IDS must contain numeric Telegram user IDs.")
    return values


def normalize_telegram_message(update: Update) -> IncomingMessage:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if message is None or user is None or chat is None:
        raise ValueError("Telegram update is missing a message, user, or chat.")
    if chat.type != ChatType.PRIVATE:
        raise ValueError("Only private Telegram chats are supported.")
    if not message.text:
        raise ValueError("Telegram update does not contain text.")

    return IncomingMessage(
        channel="telegram",
        sender_id=str(user.id),
        conversation_id=str(chat.id),
        thread_id=str(chat.id),
        event_id=str(update.update_id),
        text=message.text.strip(),
    )


def process_telegram_message(message, allowed_user_ids, session_service):
    if message.sender_id not in allowed_user_ids:
        logger.warning("Ignoring Telegram message from non-allowlisted user %s", message.sender_id)
        return None
    if not message.text:
        return None

    chat_id = message.conversation_id
    update_id = int(message.event_id)
    with connect_to_database() as connection:
        with connection.transaction():
            inserted = connection.execute(
                """
                INSERT INTO telegram_processed_updates (update_id)
                VALUES (%s)
                ON CONFLICT DO NOTHING
                RETURNING update_id
                """,
                (update_id,),
            ).fetchone()
            if inserted is None:
                row = connection.execute(
                    """
                    SELECT session_id, status
                    FROM telegram_processed_updates
                    WHERE update_id = %s
                    FOR UPDATE
                    """,
                    (update_id,),
                ).fetchone()
                if row is None:
                    raise RuntimeError(f"Unable to load Telegram update {update_id}.")
                session_id, status = row
                if status != "failed":
                    return None
                connection.execute(
                    """
                    UPDATE telegram_processed_updates
                    SET status = 'processing', processed_at = CURRENT_TIMESTAMP
                    WHERE update_id = %s
                    """,
                    (update_id,),
                )
            else:
                session_id = get_or_create_chat_session(connection, chat_id)
                connection.execute(
                    "UPDATE telegram_processed_updates SET session_id = %s WHERE update_id = %s",
                    (session_id, update_id),
                )
            record_session_participant(connection, session_id, "telegram", message.sender_id)

        try:
            session_service.refresh_system_prompt(connection, session_id)
            reply = session_service.process(
                connection,
                session_id,
                message.text,
                append_user_message=inserted is not None,
            )
        except Exception:
            with connection.transaction():
                connection.execute(
                    """
                    UPDATE telegram_processed_updates
                    SET status = 'failed'
                    WHERE update_id = %s
                    """,
                    (update_id,),
                )
            raise

        with connection.transaction():
            connection.execute(
                """
                UPDATE telegram_processed_updates
                SET status = 'completed'
                WHERE update_id = %s
                """,
                (update_id,),
            )
        return reply


def split_reply(text, limit=TELEGRAM_MAX_MESSAGE_LENGTH):
    parts = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit + 1)
        if split_at <= 0:
            split_at = remaining.rfind(" ", 0, limit + 1)
        if split_at <= 0:
            split_at = limit
        parts.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip()
    if remaining:
        parts.append(remaining)
    return parts


async def reply_in_parts(message, text):
    for part in split_reply(text):
        await message.reply_text(part)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    try:
        incoming = normalize_telegram_message(update)
        allowed_user_ids = context.application.bot_data["allowed_user_ids"]
        if incoming.sender_id not in allowed_user_ids:
            logger.warning(
                "Ignoring Telegram message from non-allowlisted user %s",
                incoming.sender_id,
            )
            return
        reply = await asyncio.to_thread(
            process_telegram_message,
            incoming,
            allowed_user_ids,
            context.application.bot_data["session_service"],
        )
        if reply:
            await reply_in_parts(message, reply)
    except Exception:
        logger.exception("Failed to process Telegram update %s", update.update_id)
        if message:
            await message.reply_text("I couldn't process that request.")


def process_session_command(message, operation, allowed_user_ids, session_service):
    user_id = str(message.from_user.id)
    if user_id not in allowed_user_ids:
        return "You are not authorized to manage this agent session."

    chat_id = str(message.chat_id)
    with connect_to_database() as connection:
        session_id = get_or_create_chat_session(connection, chat_id)
        record_session_participant(connection, session_id, "telegram", user_id)
        if operation == "new":
            session_id = create_new_chat_session(connection, chat_id, session_id)
            record_session_participant(connection, session_id, "telegram", user_id)
            return "Started a new session."
        if operation == "reset":
            session_service.reset(connection, session_id)
            return "Session history cleared."
        if operation == "compact":
            session_service.compact(connection, session_id)
            return "Session compacted into a concise continuity summary."
        raise ValueError(f"Unknown session operation: {operation}")


async def handle_session_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    operation = update.effective_message.text.split("@", 1)[0].lstrip("/").lower()
    try:
        response = await asyncio.to_thread(
            process_session_command,
            message,
            operation,
            context.application.bot_data["allowed_user_ids"],
            context.application.bot_data["session_service"],
        )
        await reply_in_parts(message, response)
    except Exception:
        logger.exception("Failed to %s Telegram session", operation)
        await message.reply_text(f"Couldn't {operation} the session.")


async def handle_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.effective_message.reply_text(
        f"Your Telegram user ID is {user.id}. "
        "Add it to TELEGRAM_ALLOWED_USER_IDS in .env to authorize this bot."
    )


def build_application(token, allowed_user_ids, session_service):
    application = Application.builder().token(token).build()
    application.bot_data["allowed_user_ids"] = allowed_user_ids
    application.bot_data["session_service"] = session_service
    private_chat = filters.ChatType.PRIVATE
    application.add_handler(CommandHandler("id", handle_id_command, filters=private_chat))
    application.add_handler(CommandHandler(
        ["new", "reset", "compact"],
        handle_session_command,
        filters=private_chat,
    ))
    application.add_handler(
        MessageHandler(
            private_chat & filters.TEXT & ~filters.COMMAND,
            handle_text,
        )
    )
    return application


def main():
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    token = get_required("TELEGRAM_BOT_TOKEN")
    allowed_ids = configured_user_ids()
    with connect_to_database() as connection:
        initialize_telegram_tables(connection)

    application = build_application(token, allowed_ids, build_session_service())
    application.run_polling()


if __name__ == "__main__":
    main()
