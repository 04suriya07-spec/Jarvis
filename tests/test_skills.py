"""
Tests for skills — NotesSkill, WeatherSkill, NewsSkill, RetryCache
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── NotesSkill ────────────────────────────────────────────────────

class TestNotesSkill:

    @pytest.fixture
    def skill(self, tmp_path):
        """Each test gets its own isolated SQLite DB so tests don't bleed."""
        import skills.notes as nm
        original = nm.DB_PATH
        nm.DB_PATH = tmp_path / "notes_test.db"
        from skills.notes import NotesSkill
        instance = NotesSkill()
        yield instance
        # DB is auto-closed when the tmp_path is removed; just restore the path
        nm.DB_PATH = original

    @pytest.mark.asyncio
    async def test_create_returns_note_id(self, skill):
        result = await skill.run(action="create", title="Test Note", content="body text")
        assert result["success"] is True
        assert "note_id" in result

    @pytest.mark.asyncio
    async def test_create_and_read(self, skill):
        r = await skill.run(action="create", title="My Note", content="some content")
        nid = r["note_id"]
        note = await skill.run(action="read", note_id=nid)
        assert note["title"] == "My Note"
        assert note["content"] == "some content"

    @pytest.mark.asyncio
    async def test_list_empty(self, skill):
        result = await skill.run(action="list")
        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_list_returns_all(self, skill):
        for i in range(3):
            await skill.run(action="create", title=f"Note {i}", content="x")
        result = await skill.run(action="list")
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_search_finds_match(self, skill):
        await skill.run(action="create", title="Meeting Notes", content="discussed budget")
        await skill.run(action="create", title="Shopping", content="buy groceries")
        results = await skill.run(action="search", query="budget")
        assert len(results) == 1
        assert "Meeting" in results[0]["title"]

    @pytest.mark.asyncio
    async def test_search_no_match_returns_empty(self, skill):
        await skill.run(action="create", title="Unrelated", content="xyz")
        results = await skill.run(action="search", query="quantum")
        assert results == []

    @pytest.mark.asyncio
    async def test_update_changes_content(self, skill):
        r = await skill.run(action="create", title="Old Title", content="old body")
        nid = r["note_id"]
        await skill.run(action="update", note_id=nid, title="New Title", content="new body")
        note = await skill.run(action="read", note_id=nid)
        assert note["title"] == "New Title"
        assert note["content"] == "new body"

    @pytest.mark.asyncio
    async def test_delete_removes_note(self, skill):
        r = await skill.run(action="create", title="Temp", content="x")
        nid = r["note_id"]
        await skill.run(action="delete", note_id=nid)
        result = await skill.run(action="read", note_id=nid)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self, skill):
        result = await skill.run(action="explode")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_tags_stored(self, skill):
        r = await skill.run(action="create", title="Tagged", content="x", tags=["work", "urgent"])
        nid = r["note_id"]
        note = await skill.run(action="read", note_id=nid)
        assert "work" in note["tags"]

    @pytest.mark.asyncio
    async def test_search_by_tag(self, skill):
        await skill.run(action="create", title="A", content="x", tags=["finance"])
        await skill.run(action="create", title="B", content="y", tags=["health"])
        results = await skill.run(action="search", query="finance")
        assert len(results) == 1


# ── RetryCache ────────────────────────────────────────────────────

class TestRetryCache:

    def test_cache_hit(self):
        from core.retry import cache_set, cache_get
        cache_set("k1", {"value": 42}, ttl=60)
        hit, val = cache_get("k1")
        assert hit is True
        assert val == {"value": 42}

    def test_cache_miss(self):
        from core.retry import cache_get, cache_invalidate
        cache_invalidate()
        hit, val = cache_get("nonexistent_key_xyz")
        assert hit is False
        assert val is None

    def test_cache_expiry(self):
        import time
        from core.retry import cache_set, cache_get
        cache_set("expiring", "data", ttl=0.05)
        time.sleep(0.1)
        hit, _ = cache_get("expiring")
        assert hit is False

    def test_cache_stats(self):
        from core.retry import cache_set, cache_stats, cache_invalidate
        cache_invalidate()
        cache_set("a", 1, ttl=60)
        cache_set("b", 2, ttl=60)
        stats = cache_stats()
        assert stats["live"] >= 2

    @pytest.mark.asyncio
    async def test_with_retry_succeeds_on_first(self):
        from core.retry import with_retry
        call_count = 0

        @with_retry(max_retries=3)
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_with_retry_retries_on_failure(self):
        from core.retry import with_retry
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)
        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temporary failure")
            return "recovered"

        result = await flaky()
        assert result == "recovered"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_with_retry_raises_after_exhaustion(self):
        from core.retry import with_retry

        @with_retry(max_retries=2, base_delay=0.01)
        async def always_fail():
            raise RuntimeError("permanent failure")

        with pytest.raises(RuntimeError, match="permanent failure"):
            await always_fail()

    @pytest.mark.asyncio
    async def test_cached_decorator(self):
        from core.retry import cached
        call_count = 0

        @cached(ttl=60)
        async def expensive(x: int):
            nonlocal call_count
            call_count += 1
            return x * 2

        r1 = await expensive(5)
        r2 = await expensive(5)
        assert r1 == r2 == 10
        assert call_count == 1   # cached on second call

    @pytest.mark.asyncio
    async def test_cached_skips_error_results(self):
        from core.retry import cached
        call_count = 0

        @cached(ttl=60, skip_on_error=True)
        async def may_error(flag: bool):
            nonlocal call_count
            call_count += 1
            if flag:
                return {"error": "not found"}
            return {"value": 99}

        r1 = await may_error(True)    # error — not cached
        r2 = await may_error(True)    # error again — still not cached
        assert call_count == 2
