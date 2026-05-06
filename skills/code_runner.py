"""Code Runner skill – execute Python snippets safely in a subprocess."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import os
from pathlib import Path

from skills.base import BaseSkill
from core.logger import get_logger

logger = get_logger("javris.skill.code_runner")

TIMEOUT = 30  # seconds


class CodeRunnerSkill(BaseSkill):
    name = "run_code"
    description = "Execute Python code snippets and return output"

    tool_definition = {
        "name": "run_code",
        "description": (
            "Execute a Python code snippet in a sandboxed subprocess. "
            "Returns stdout, stderr, and return code. "
            "Use this for calculations, data processing, or testing logic."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Valid Python 3 code to execute",
                },
                "language": {
                    "type": "string",
                    "description": "Programming language (currently only 'python' supported)",
                    "default": "python",
                },
            },
            "required": ["code"],
        },
    }

    async def run(self, code: str, language: str = "python") -> dict:
        if language != "python":
            return {"error": f"Language '{language}' not supported yet"}

        # Write code to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=TIMEOUT
                )
                return {
                    "returncode": proc.returncode,
                    "stdout": stdout.decode(errors="replace")[:8000],
                    "stderr": stderr.decode(errors="replace")[:2000],
                    "success": proc.returncode == 0,
                }
            except asyncio.TimeoutError:
                proc.kill()
                return {"error": f"Code timed out after {TIMEOUT}s", "success": False}
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
