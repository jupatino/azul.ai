import subprocess
from pathlib import Path


MAX_FILE_BYTES = 100_000
MAX_COMMAND_OUTPUT_BYTES = 10_000
SAFE_COMMANDS = {"pwd": ["pwd"], "ls": ["ls"]}


class SkillsTools:
    def __init__(self, skills_dir):
        self.skills_dir = Path(skills_dir).resolve()
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def resolve_path(self, path):
        requested = Path(path)
        resolved = (requested if requested.is_absolute() else self.skills_dir / requested).resolve()
        try:
            resolved.relative_to(self.skills_dir)
        except ValueError as exc:
            raise ValueError("File tools can only access paths inside the skills directory.") from exc
        return resolved

    def list_files(self, path="."):
        directory = self.resolve_path(path)
        entries = []
        for entry in directory.iterdir():
            if entry.is_symlink():
                continue
            suffix = " (dir)" if entry.is_dir() else ""
            entries.append(entry.name + suffix)
        return "\n".join(sorted(entries)) or "(empty directory)"

    def read_file(self, path):
        file_path = self.resolve_path(path)
        if file_path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(f"Files larger than {MAX_FILE_BYTES} bytes cannot be read.")
        return file_path.read_text(encoding="utf-8")

    def write_file(self, path, content):
        file_path = self.resolve_path(path)
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError(f"Files larger than {MAX_FILE_BYTES} bytes cannot be written.")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"Saved {file_path.relative_to(self.skills_dir)} ({len(content)} characters written)."

    def delete_file(self, path):
        requested = Path(path)
        candidate = requested if requested.is_absolute() else self.skills_dir / requested
        parent = candidate.parent.resolve()
        try:
            parent.relative_to(self.skills_dir)
        except ValueError as exc:
            raise ValueError("File tools can only access paths inside the skills directory.") from exc
        if candidate.is_symlink():
            raise ValueError("Symbolic links cannot be deleted with delete_file.")

        file_path = self.resolve_path(path)
        if not file_path.is_file():
            raise ValueError(f"{path} is not a file.")
        file_path.unlink()
        return f"Deleted {file_path.relative_to(self.skills_dir)}."

    def run_command(self, command):
        if command not in SAFE_COMMANDS:
            raise ValueError(f"Command is not allowed. Choose one of: {', '.join(SAFE_COMMANDS)}.")
        result = subprocess.run(
            SAFE_COMMANDS[command],
            cwd=self.skills_dir,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        output = (result.stdout + result.stderr).strip()
        if len(output) > MAX_COMMAND_OUTPUT_BYTES:
            output = output[:MAX_COMMAND_OUTPUT_BYTES] + "\n... output truncated"
        return output or f"(no output, exit code {result.returncode})"
