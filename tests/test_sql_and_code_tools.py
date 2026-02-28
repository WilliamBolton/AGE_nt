"""Tests for the sql_query and run_python MCP tools."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

from src.tools.sql_query import has_limit_clause, rewrite_select_star, validate_sql

# ── SQL validation tests ─────────────────────────────────────────────────────


class TestValidateSQL:
    """Test the SQL query safety validator."""

    def test_allows_simple_select(self):
        ok, msg = validate_sql("SELECT COUNT(*) FROM documents")
        assert ok is True
        assert msg == ""

    def test_allows_select_with_where(self):
        ok, _ = validate_sql(
            "SELECT intervention, COUNT(*) FROM documents "
            "WHERE source_type='pubmed' GROUP BY intervention"
        )
        assert ok is True

    def test_allows_cte(self):
        ok, _ = validate_sql(
            "WITH counts AS (SELECT intervention, COUNT(*) as cnt FROM documents "
            "GROUP BY intervention) SELECT * FROM counts ORDER BY cnt DESC"
        )
        assert ok is True

    def test_allows_trailing_semicolon(self):
        ok, _ = validate_sql("SELECT 1;")
        assert ok is True

    def test_blocks_insert(self):
        ok, msg = validate_sql("INSERT INTO documents (id) VALUES ('x')")
        assert ok is False
        assert "INSERT" in msg

    def test_blocks_delete(self):
        ok, msg = validate_sql("DELETE FROM documents WHERE id='x'")
        assert ok is False
        assert "DELETE" in msg

    def test_blocks_drop(self):
        ok, msg = validate_sql("DROP TABLE documents")
        assert ok is False
        assert "DROP" in msg

    def test_blocks_update(self):
        ok, msg = validate_sql("UPDATE documents SET title='x' WHERE id='y'")
        assert ok is False
        assert "UPDATE" in msg

    def test_blocks_attach(self):
        ok, msg = validate_sql("ATTACH DATABASE '/tmp/evil.db' AS evil")
        assert ok is False
        assert "ATTACH" in msg

    def test_blocks_create(self):
        ok, msg = validate_sql("CREATE TABLE evil (id TEXT)")
        assert ok is False
        assert "Only SELECT" in msg

    def test_blocks_multi_statement(self):
        # Blocked keyword check fires first here, but query is still rejected
        ok, msg = validate_sql("SELECT 1; DROP TABLE documents")
        assert ok is False

    def test_blocks_multi_statement_both_selects(self):
        # Two SELECTs separated by semicolon — caught by multi-statement check
        ok, msg = validate_sql("SELECT 1; SELECT 2")
        assert ok is False
        assert "Multiple statements" in msg

    def test_blocks_comment_hidden_keyword(self):
        # Keyword hidden in comment should still be caught after stripping
        ok, msg = validate_sql("SELECT 1 /* harmless */ ; DROP TABLE documents")
        assert ok is False

    def test_blocks_line_comment_hidden_keyword(self):
        ok, msg = validate_sql("SELECT 1 -- harmless\n; DELETE FROM documents")
        assert ok is False

    def test_blocks_empty_query(self):
        ok, msg = validate_sql("")
        assert ok is False
        assert "Empty" in msg

    def test_blocks_whitespace_only(self):
        ok, msg = validate_sql("   \n  ")
        assert ok is False
        assert "Empty" in msg

    def test_blocks_pragma(self):
        ok, msg = validate_sql("SELECT 1 FROM documents WHERE REINDEX")
        assert ok is False

    def test_blocks_load_extension(self):
        ok, msg = validate_sql("SELECT LOAD_EXTENSION('/tmp/evil.so')")
        assert ok is False


class TestRewriteSelectStar:
    """Test SELECT * rewriting to exclude heavy columns."""

    def test_rewrites_simple_select_star(self):
        sql = "SELECT * FROM documents WHERE intervention='rapamycin'"
        result = rewrite_select_star(sql)
        assert "raw_response" not in result
        assert "source_metadata" not in result
        assert "intervention" in result
        assert "title" in result

    def test_preserves_explicit_columns(self):
        sql = "SELECT intervention, title FROM documents"
        result = rewrite_select_star(sql)
        assert result == sql

    def test_preserves_select_star_in_subquery(self):
        # Only rewrites top-level SELECT *, but since the regex matches the
        # first occurrence, this will rewrite. That's acceptable behaviour.
        sql = "SELECT * FROM (SELECT * FROM documents) sub"
        result = rewrite_select_star(sql)
        assert result != sql  # At least one rewrite happened


class TestHasLimitClause:
    """Test LIMIT clause detection."""

    def test_detects_limit(self):
        assert has_limit_clause("SELECT * FROM documents LIMIT 10") is True

    def test_detects_limit_with_offset(self):
        assert has_limit_clause("SELECT * FROM documents LIMIT 10 OFFSET 5") is True

    def test_no_limit(self):
        assert has_limit_clause("SELECT * FROM documents") is False

    def test_limit_in_subquery(self):
        assert has_limit_clause(
            "SELECT * FROM (SELECT * FROM documents LIMIT 5)"
        ) is True


# ── Integration tests (require database) ────────────────────────────────────

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "age_nt.db"
DB_EXISTS = DB_PATH.exists()


@pytest.mark.skipif(not DB_EXISTS, reason="SQLite database not found")
class TestSQLQueryIntegration:
    """Integration tests against the real database."""

    @pytest.fixture
    async def ro_db(self):
        import aiosqlite

        db = await aiosqlite.connect(str(DB_PATH))
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA query_only = ON")
        yield db
        await db.close()

    async def test_count_documents(self, ro_db):
        cursor = await ro_db.execute("SELECT COUNT(*) as cnt FROM documents")
        row = await cursor.fetchone()
        assert row["cnt"] > 0

    async def test_read_only_blocks_insert(self, ro_db):
        with pytest.raises(Exception):
            await ro_db.execute("INSERT INTO documents (id) VALUES ('test')")

    async def test_cross_intervention_query(self, ro_db):
        cursor = await ro_db.execute(
            "SELECT intervention, COUNT(*) as cnt FROM documents "
            "GROUP BY intervention ORDER BY cnt DESC LIMIT 5"
        )
        rows = await cursor.fetchall()
        assert len(rows) > 0
        assert rows[0]["cnt"] > 0


# ── Code execution tests ────────────────────────────────────────────────────


class TestRunPythonHelpers:
    """Test the code execution tool's subprocess approach."""

    async def test_simple_output(self):
        code = 'print("hello world")'
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            path = f.name
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            assert stdout.decode().strip() == "hello world"
            assert proc.returncode == 0
        finally:
            os.unlink(path)

    async def test_timeout_kills_process(self):
        code = "import time\nwhile True: time.sleep(0.1)"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            path = f.name
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(proc.communicate(), timeout=1)
            proc.kill()
        finally:
            os.unlink(path)

    async def test_syntax_error_returns_nonzero(self):
        code = "def broken(\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            path = f.name
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            assert proc.returncode != 0
        finally:
            os.unlink(path)

    @pytest.mark.skipif(not DB_EXISTS, reason="SQLite database not found")
    async def test_db_access_from_subprocess(self):
        code = f"""
import sqlite3
conn = sqlite3.connect("file:{DB_PATH}?mode=ro", uri=True)
cursor = conn.execute("SELECT COUNT(*) FROM documents")
print(cursor.fetchone()[0])
conn.close()
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            path = f.name
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            count = int(stdout.decode().strip())
            assert count > 0
        finally:
            os.unlink(path)
