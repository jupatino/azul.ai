import json
import os

from openai import OpenAI

from .config import get_required


MODEL = "deepseek/deepseek-v4-flash-0731"
DEFAULT_SYSTEM_PROMPT = (
    "You are a coding agent running in a Python environment. "
    "Use the available tools to help complete the user's request."
)

client = None


def get_client():
    global client
    if client is None:
        client = OpenAI(
            api_key=get_required("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1",
            max_retries=5,
        )
    return client


def run_tool(tool_call, tools):
    name = tool_call.function.name
    try:
        arguments = json.loads(tool_call.function.arguments)
        if name not in tools:
            return f"Error running unsupported tool '{name}'."
        return str(tools[name](**arguments))
    except Exception as exc:
        return f"Error running tool '{name}': {exc}"


def run_agent(connection, session_id, messages, tool_schemas, tools, max_rounds=8):
    from .db import load_messages, save_message

    openai_client = get_client()
    for _ in range(max_rounds):
        response = openai_client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tool_schemas,
            tool_choice="auto",
        )
        assistant_message = response.choices[0].message
        save_message(
            connection,
            session_id,
            assistant_message.model_dump(exclude_none=True),
        )
        if not assistant_message.tool_calls:
            return assistant_message.content or "I couldn't generate a text response."

        for tool_call in assistant_message.tool_calls:
            save_message(
                connection,
                session_id,
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": run_tool(tool_call, tools),
                },
            )
        messages = load_messages(connection, session_id)
    raise RuntimeError(f"Agent exceeded {max_rounds} tool-call rounds.")
