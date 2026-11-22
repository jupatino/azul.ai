import json

from .agent import run_agent
from .agent import MODEL, get_client
from .db import (
    create_session,
    load_messages,
    save_message,
)


class AgentSessionService:
    def __init__(self, system_prompt, tool_schemas, tools, max_rounds=8):
        self.system_prompt = system_prompt
        self.tool_schemas = tool_schemas
        self.tools = tools
        self.max_rounds = max_rounds

    def create(self, connection):
        return create_session(connection, self.system_prompt)

    def reset(self, connection, session_id):
        with connection.transaction():
            connection.execute(
                "DELETE FROM agent_session_messages WHERE session_id = %s",
                (session_id,),
            )
            save_message(
                connection,
                session_id,
                {"role": "system", "content": self.system_prompt},
            )

    def process(self, connection, session_id, text, *, append_user_message=True):
        if append_user_message:
            save_message(connection, session_id, {"role": "user", "content": text})
        return run_agent(
            connection,
            session_id,
            load_messages(connection, session_id),
            self.tool_schemas,
            self.tools,
            self.max_rounds,
        )

    def compact(self, connection, session_id, max_message_chars=12_000,
                max_chunk_chars=24_000, max_chunks=20):
        messages = [
            message
            for message in load_messages(connection, session_id)
            if message.get("role") != "system"
        ]
        if not messages:
            raise ValueError("This session has no conversation history to compact.")

        chunks = []
        current_chunk = []
        current_size = 0
        for message in messages:
            serialized = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
            if len(serialized) > max_message_chars:
                serialized = serialized[:max_message_chars] + "... [message truncated]"
            if current_chunk and current_size + len(serialized) > max_chunk_chars:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_size = 0
            current_chunk.append(serialized)
            current_size += len(serialized)
        if current_chunk:
            chunks.append("\n".join(current_chunk))
        if len(chunks) > max_chunks:
            raise ValueError("This session is too large to compact. Start a new session.")

        summaries = []
        for index, chunk in enumerate(chunks, start=1):
            response = get_client().chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": "Summarize this conversation segment for continuation. Preserve goals, decisions, facts, and tool outcomes."},
                    {"role": "user", "content": f"Conversation segment {index} of {len(chunks)}:\n{chunk}"},
                ],
                max_tokens=800,
            )
            summary = response.choices[0].message.content
            if not summary:
                raise RuntimeError(f"Model returned an empty summary for segment {index}.")
            summaries.append(summary)

        if len(summaries) > 1:
            response = get_client().chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": "Merge these notes into one compact continuation summary."},
                    {"role": "user", "content": "\n\n".join(summaries)},
                ],
                max_tokens=1200,
            )
            summary = response.choices[0].message.content
            if not summary:
                raise RuntimeError("Model returned an empty merged summary.")
        else:
            summary = summaries[0]

        with connection.transaction():
            connection.execute(
                "DELETE FROM agent_session_messages WHERE session_id = %s AND message->>'role' <> 'system'",
                (session_id,),
            )
            save_message(
                connection,
                session_id,
                {"role": "assistant", "content": f"Conversation summary for continuity:\n{summary}"},
            )
        return summary
