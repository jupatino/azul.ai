import tempfile
import unittest
from unittest.mock import patch

from azul_ai.core.agent_runtime import SYSTEM_PROMPT, TOOL_SCHEMAS, build_session_service


class AgentRuntimeTests(unittest.TestCase):
    def test_registers_matching_tool_schemas_and_handlers(self):
        with tempfile.TemporaryDirectory() as skills_dir, patch.dict(
            "os.environ", {"AZUL_AGENT_SKILLS_DIR": skills_dir}
        ):
            service = build_session_service()

        schema_names = {schema["function"]["name"] for schema in TOOL_SCHEMAS}
        self.assertEqual(schema_names, set(service.tools))
        self.assertEqual(
            schema_names,
            {"list_files", "read_file", "write_file", "delete_file", "run_command"},
        )

    def test_prompt_documents_file_scope_and_delete_behavior(self):
        self.assertIn("File tools can only access the persistent skills directory", SYSTEM_PROMPT)
        self.assertIn("not application or other container files", SYSTEM_PROMPT)
        self.assertIn("When the user explicitly asks to delete a named file, use delete_file.", SYSTEM_PROMPT)
        self.assertIn("Never claim a file was deleted unless delete_file reports success.", SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
