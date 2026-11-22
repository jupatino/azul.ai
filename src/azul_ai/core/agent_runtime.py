import os

from azul_ai.core.config import PROJECT_DIR
from azul_ai.core.session import AgentSessionService
from azul_ai.tools.skills import SkillsTools


SYSTEM_PROMPT = (
    "You are a helpful assistant communicating through a messaging channel. "
    "You have these tools: list_files, read_file, write_file, delete_file, and run_command. "
    "When asked what tools you have, list them and explain their limits; do not claim that tools are unavailable. "
    "Use them when helpful. File tools can only access the persistent skills directory, "
    "not application or other container files, and enforce a 100 KB file-size limit. "
    "delete_file removes files only; it cannot delete directories or symbolic links. "
    "When the user explicitly asks to delete a named file, use delete_file. "
    "If the target path is missing or ambiguous, ask which file they mean. "
    "Never claim a file was deleted unless delete_file reports success. "
    "Files in the skills directory are stored on the host and survive service restarts. "
    "run_command accepts only pwd and ls, and runs them in the skills directory; "
    "arbitrary shell commands are not allowed. "
    "Respond to the user's message directly. Do not add a greeting unless they greeted you, "
    "and do not end with generic follow-up questions or invitations. "
    "Ask a question only when required to clarify or complete the user's request. "
    "Answer clearly and concisely."
)

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
        ("delete_file",
         "Deletes a regular file inside the persistent skills directory; "
         "directories and symbolic links are not allowed.",
         {"path": {"type": "string"}}, ["path"]),
        ("run_command", "Runs pwd or ls in the persistent skills directory.",
         {"command": {"type": "string"}}, ["command"]),
    )
]


def build_session_service():
    skills_dir = os.getenv("AZUL_AGENT_SKILLS_DIR", PROJECT_DIR / "skills")
    skills = SkillsTools(skills_dir)
    tools = {
        "list_files": skills.list_files,
        "read_file": skills.read_file,
        "write_file": skills.write_file,
        "delete_file": skills.delete_file,
        "run_command": skills.run_command,
    }
    return AgentSessionService(SYSTEM_PROMPT, TOOL_SCHEMAS, tools)
