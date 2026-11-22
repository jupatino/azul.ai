import os
import subprocess
from pathlib import Path


def list_files(path):
    entries = []
    for entry in os.scandir(path):
        entries.append(entry.name + (" (dir)" if entry.is_dir() else ""))
    return "\n".join(sorted(entries)) or "(empty directory)"


def read_file(path):
    return Path(path).read_text(encoding="utf-8")


def write_file(path, content):
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return f"Saved {path} ({len(content)} characters written)."


def run_command(command):
    answer = input(f" Run '{command}'? (y/n): ")
    if answer.lower() != "y":
        return "The user declined to run the command."
    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=120)
    output = (result.stdout + result.stderr).strip()
    return output or f"(no output, exit code {result.returncode})"
