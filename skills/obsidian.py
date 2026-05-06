"""
Obsidian skill — read, write, search, list Markdown notes in an Obsidian vault.
Adapted from openclaw/skills/obsidian SKILL.md — ported to Python + Javris pattern.
Vault = a plain folder of .md files; no special API needed.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from skills.base import BaseSkill
from core.logger import get_logger
from core.config import get_config

logger = get_logger("javris.skill.obsidian")
cfg = get_config()


def _vault() -> Path | None:
    """Resolve the configured Obsidian vault path."""
    raw = cfg.obsidian_vault_path
    if not raw:
        return None
    p = Path(raw).expanduser().resolve()
    if p.is_dir():
        return p
    return None


def _find_note(vault: Path, name: str) -> Path | None:
    """Find a note by name (with or without .md extension) anywhere in vault."""
    if not name.endswith(".md"):
        name += ".md"
    # Exact relative path first
    exact = vault / name
    if exact.exists():
        return exact
    # Walk vault
    for root, _, files in os.walk(vault):
        for f in files:
            if f.lower() == name.lower():
                return Path(root) / f
    return None


class ObsidianSkill(BaseSkill):
    name = "obsidian"
    description = "Read, write, and search notes in your Obsidian vault"

    tool_definition = {
        "name": "obsidian",
        "description": (
            "Interact with your local Obsidian vault (Markdown notes). "
            "Actions: list_notes, read_note, create_note, append_note, search_notes, search_content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list_notes", "read_note", "create_note",
                        "append_note", "search_notes", "search_content",
                    ],
                    "description": "Obsidian operation to perform",
                },
                "note": {
                    "type": "string",
                    "description": "Note name or relative path (e.g. 'Daily/2024-01-01' or 'Meeting Notes')",
                },
                "content": {
                    "type": "string",
                    "description": "Markdown content for create_note or append_note",
                },
                "query": {
                    "type": "string",
                    "description": "Search query (for search_notes / search_content)",
                },
                "folder": {
                    "type": "string",
                    "description": "Subfolder to list/restrict to (optional)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return",
                    "default": 20,
                },
            },
            "required": ["action"],
        },
    }

    async def run(
        self,
        action: str,
        note: str = "",
        content: str = "",
        query: str = "",
        folder: str = "",
        limit: int = 20,
    ) -> str | list | dict:
        vault = _vault()
        if vault is None:
            return (
                "Obsidian vault not configured or not found. "
                "Set OBSIDIAN_VAULT_PATH in .env (e.g. C:/Users/you/Documents/MyVault)"
            )

        logger.info(f"Obsidian:{action} vault={vault.name}")

        match action:
            case "list_notes":
                root = vault / folder if folder else vault
                if not root.is_dir():
                    return f"Folder not found: {folder}"
                notes = sorted(
                    p.relative_to(vault).as_posix()
                    for p in root.rglob("*.md")
                    if not any(part.startswith(".") for part in p.parts)
                )[:limit]
                return {"vault": vault.name, "count": len(notes), "notes": notes}

            case "read_note":
                if not note:
                    return "note parameter required"
                path = _find_note(vault, note)
                if path is None:
                    return f"Note not found: {note}"
                return {
                    "path": path.relative_to(vault).as_posix(),
                    "content": path.read_text(encoding="utf-8"),
                    "size_bytes": path.stat().st_size,
                }

            case "create_note":
                if not note:
                    return "note parameter required"
                if not note.endswith(".md"):
                    note += ".md"
                path = vault / note
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    return f"Note already exists: {note} — use append_note to add content"
                path.write_text(content or "", encoding="utf-8")
                return {"created": note, "bytes": len((content or "").encode())}

            case "append_note":
                if not note:
                    return "note parameter required"
                path = _find_note(vault, note)
                if path is None:
                    # Auto-create if not found
                    if not note.endswith(".md"):
                        note += ".md"
                    path = vault / note
                    path.parent.mkdir(parents=True, exist_ok=True)
                existing = path.read_text(encoding="utf-8") if path.exists() else ""
                separator = "\n\n" if existing and not existing.endswith("\n\n") else ""
                path.write_text(existing + separator + (content or ""), encoding="utf-8")
                return {"appended_to": path.relative_to(vault).as_posix()}

            case "search_notes":
                if not query:
                    return "query parameter required"
                q = query.lower()
                matches = [
                    p.relative_to(vault).as_posix()
                    for p in vault.rglob("*.md")
                    if q in p.stem.lower()
                    and not any(part.startswith(".") for part in p.parts)
                ][:limit]
                return {"query": query, "matches": matches, "count": len(matches)}

            case "search_content":
                if not query:
                    return "query parameter required"
                q = query.lower()
                results: list[dict] = []
                for p in vault.rglob("*.md"):
                    if any(part.startswith(".") for part in p.parts):
                        continue
                    try:
                        text = p.read_text(encoding="utf-8", errors="ignore")
                        if q in text.lower():
                            # Find matching lines with context
                            lines = text.splitlines()
                            snippets = [
                                f"L{i+1}: {line.strip()}"
                                for i, line in enumerate(lines)
                                if q in line.lower()
                            ][:3]
                            results.append({
                                "note": p.relative_to(vault).as_posix(),
                                "snippets": snippets,
                            })
                            if len(results) >= limit:
                                break
                    except Exception:
                        continue
                return {"query": query, "results": results, "count": len(results)}

            case _:
                return f"Unknown action: {action}"
