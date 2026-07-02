import os
import pytest
import tempfile
import json

from db import SQLiteAdapter
import mcp_server
import init_db

@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    """Fixture to create an isolated database run for every test."""
    # Create a temporary file for the database
    db_fd, db_path = tempfile.mkstemp()
    
    # Configure env to use it
    monkeypatch.setenv("DB_TYPE", "sqlite")
    monkeypatch.setenv("SQLITE_PATH", db_path)
    
    # Force reload of adapter in mcp_server
    mcp_server._adapter = SQLiteAdapter(db_path)
    
    # Seed the database
    init_db.create_database()
    
    yield db_path
    
    # Cleanup
    os.close(db_fd)
    os.unlink(db_path)

def test_search_basic():
    results = mcp_server.search(table="students", filters={"cohort": "A1"})
    assert len(results) == 2
    assert results[0]["name"] == "Alice Smith"

def test_search_advanced():
    # Test IN operator
    results = mcp_server.search(table="students", filters=[{"column": "id", "operator": "IN", "value": [1, 3]}])
    assert len(results) == 2
    ids = {r["id"] for r in results}
    assert ids == {1, 3}
    
    # Test sort
    results = mcp_server.search(table="enrollments", order_by="score", descending=True)
    assert results[0]["score"] == 98.0

def test_insert_success():
    payload = {"name": "Test Student", "cohort": "C1", "email": "test@example.com"}
    res = mcp_server.insert(table="students", values=payload)
    assert res["id"] is not None
    assert res["name"] == "Test Student"
    
    # Verify in DB
    search_res = mcp_server.search(table="students", filters={"email": "test@example.com"})
    assert len(search_res) == 1

def test_insert_empty():
    with pytest.raises(ValueError) as exc:
        mcp_server.insert(table="students", values={})
    assert "Cannot perform an empty insert" in str(exc.value)

def test_aggregate():
    # count
    res = mcp_server.aggregate(table="students", metric="count")
    assert res[0]["value"] == 4
    
    # avg grouping
    res = mcp_server.aggregate(table="enrollments", metric="avg", column="score", group_by="student_id")
    assert len(res) == 4
    # student 1 scores: 95.0, 88.5 -> avg = 91.75
    assert next(r["value"] for r in res if r["student_id"] == 1) == 91.75

def test_safety_invalid_table():
    with pytest.raises(ValueError) as exc:
        mcp_server.search(table="non_existent")
    assert "does not exist in database" in str(exc.value)

def test_safety_invalid_column():
    with pytest.raises(ValueError) as exc:
        mcp_server.search(table="students", filters={"non_existent_column": "val"})
    assert "does not exist in table" in str(exc.value)

def test_safety_invalid_operator():
    with pytest.raises(ValueError) as exc:
        mcp_server.search(table="students", filters=[{"column": "name", "operator": "DROP", "value": "val"}])
    assert "Unsupported filter operator" in str(exc.value)

def test_resources():
    db_schema = json.loads(mcp_server.database_schema())
    assert "students" in db_schema
    assert "courses" in db_schema
    assert "enrollments" in db_schema
    
    stud_schema = json.loads(mcp_server.table_schema("students"))
    assert "students" in stud_schema
    assert stud_schema["students"]["email"] == "TEXT"
