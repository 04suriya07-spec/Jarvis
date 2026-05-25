"""Document Intelligence Skill for Javris."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from skills.base import BaseSkill
from core.models import SkillResult
from core.logger import get_logger

logger = get_logger("javris.skills.documents")

class DocumentsSkill(BaseSkill):
    name = "documents"
    description = "Read, summarize, and extract information from documents (PDF, DOCX, TXT, MD)."

    tool_definition = {
        "name": "documents",
        "description": "Read, summarize, and extract information from documents (PDF, DOCX, TXT, MD).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "summarize", "ask"],
                    "description": "The action to perform on the document."
                },
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the document file."
                },
                "query": {
                    "type": "string",
                    "description": "Question to ask about the document (only for 'ask' action)."
                }
            },
            "required": ["action", "path"]
        }
    }

    async def run(self, action: str, path: str, query: str = "") -> Any:
        file_path = Path(path).resolve()
        if not file_path.exists() or not file_path.is_file():
            return SkillResult(ok=False, error=f"File not found: {path}")

        try:
            content = self._read_file(file_path)
            if not content:
                return SkillResult(ok=False, error=f"Could not extract text from {path}")

            if action == "read":
                # Truncate if extremely long to avoid memory issues
                return SkillResult(ok=True, data={"content": content[:100000], "path": str(file_path)})

            elif action == "summarize":
                # For a full implementation, we'd pass this to the LLM. 
                # Here we just return the instruction for the LLM router to handle
                return SkillResult(ok=True, data={
                    "instruction": "Please summarize the following document content.",
                    "content": content[:50000]
                })

            elif action == "ask":
                if not query:
                    return SkillResult(ok=False, error="Query is required for 'ask' action.")
                return SkillResult(ok=True, data={
                    "instruction": f"Answer the following question based on the document: {query}",
                    "content": content[:50000]
                })
            else:
                return SkillResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            logger.error(f"Error processing document {path}: {e}")
            return SkillResult(ok=False, error=str(e))

    def _read_file(self, path: Path) -> str:
        ext = path.suffix.lower()
        if ext in [".txt", ".md", ".json", ".csv", ".py", ".js", ".html"]:
            try:
                return path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return path.read_text(encoding="latin-1", errors="replace")
        elif ext == ".pdf":
            try:
                import PyPDF2
                with open(path, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    return "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
            except ImportError:
                return f"[PDF parsing requires PyPDF2 package. Content of {path.name} cannot be read.]"
        elif ext == ".docx":
            try:
                import docx
                doc = docx.Document(path)
                return "\n".join([p.text for p in doc.paragraphs])
            except ImportError:
                return f"[DOCX parsing requires python-docx package. Content of {path.name} cannot be read.]"
        else:
            return f"[Unsupported file type: {ext}]"

