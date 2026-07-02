# SQLite/PostgreSQL Lab MCP Server — Implementation

FastMCP server exposing a small `students` / `courses` / `enrollments` database
through three MCP tools (`search`, `insert`, `aggregate`) and two MCP resources
(full schema + per-table schema).

## 1. Project Structure

```text
implementation/
  db.py                          # DatabaseAdapter (ABC) + SQLiteAdapter + PostgreSQLAdapter
  init_db.py                     # creates schema and seeds sample data
  mcp_server.py                  # FastMCP server: tools, resources, stdio/SSE entrypoints
  verify_server.py               # in-process smoke test (calls the tool functions directly)
  mcp_inspector_verification.log # protocol-level verification via MCP Inspector CLI (see §5)
  demo-day26.mov                 # local copy of demo video (not committed; see §8 for Drive link)
  tests/test_server.py           # pytest unit tests
  docker-compose.yml             # optional local Postgres for the bonus dual-backend path
  .env                           # DB_TYPE, SQLITE_PATH, POSTGRES_URI, MCP_AUTH_TOKEN
```

## 2. Setup

```bash
cd implementation
python3 -m venv .venv
source .venv/bin/activate          # macOS/Linux
pip install fastmcp psycopg2-binary python-dotenv uvicorn pytest

# create + seed the SQLite database
python init_db.py
```

`.env` controls the backend:

```dotenv
DB_TYPE=sqlite
SQLITE_PATH=sqlite_lab.db
POSTGRES_URI=postgresql://postgres:postgres@localhost:5432/mcp_db
MCP_AUTH_TOKEN=my-secret-key
```

To run against PostgreSQL instead, start `docker-compose up -d`, set
`DB_TYPE=postgres` in `.env`, then rerun `python init_db.py`.

## 3. Running the Server

```bash
# stdio transport (used by MCP clients / Inspector)
python mcp_server.py

# SSE transport with Bearer auth (bonus)
python mcp_server.py --transport sse --host 127.0.0.1 --port 8000
# requires header: Authorization: Bearer <MCP_AUTH_TOKEN>
```

## 4. Tools and Resources

| Tool | Description |
|---|---|
| `search` | `table`, `filters` (dict of equality pairs or list of `{column, operator, value}` / `[col, op, val]`), `columns`, `limit`, `offset`, `order_by`, `descending`. Operators: `=, !=, >, <, >=, <=, LIKE, IN`. |
| `insert` | `table`, `values` (dict of column→value). Returns the inserted row. Rejects empty inserts. |
| `aggregate` | `table`, `metric` (`count/avg/sum/min/max`), `column`, `filters`, `group_by` (string or list). |

| Resource | URI | Description |
|---|---|---|
| Full schema | `schema://database` | JSON of every table → `{column: type}` |
| Table schema | `schema://table/{table_name}` | JSON schema for one table |

All identifiers (table/column names) are validated against `list_tables()` /
`get_table_schema()` before being interpolated into SQL; all values are bound
via placeholders (`?` / `%s`) — never string-concatenated.

## 5. Testing and Verification

### 5.1 Unit tests (pytest)

```bash
python -m pytest tests/ -q
```
Result: **9 passed** — covers `search` (basic + `IN` + sort), `insert`
(success + empty-insert rejection), `aggregate` (count + grouped avg), safety
(invalid table / invalid column / invalid operator), and both resources.

### 5.2 In-process smoke test

```bash
python verify_server.py
```
Runs all 3 tools and both resources against a live SQLite DB, then
deliberately triggers 3 failure cases (unknown table, unknown column,
unsupported aggregate metric) and confirms each is rejected with a clear
error message.

### 5.3 Protocol-level verification (MCP Inspector CLI)

Unlike §5.1/§5.2, which call the Python functions directly, this step talks to
the server over the real MCP stdio protocol, the same way an actual client
would:

```bash
npx -y @modelcontextprotocol/inspector --cli ./.venv/bin/python mcp_server.py --method tools/list
npx -y @modelcontextprotocol/inspector --cli ./.venv/bin/python mcp_server.py --method resources/list
npx -y @modelcontextprotocol/inspector --cli ./.venv/bin/python mcp_server.py --method resources/templates/list
npx -y @modelcontextprotocol/inspector --cli ./.venv/bin/python mcp_server.py --method tools/call --tool-name search --tool-arg table=students --tool-arg 'filters={"cohort":"A1"}'
npx -y @modelcontextprotocol/inspector --cli ./.venv/bin/python mcp_server.py --method tools/call --tool-name search --tool-arg table=hackers
npx -y @modelcontextprotocol/inspector --cli ./.venv/bin/python mcp_server.py --method resources/read --uri schema://database
```

Full captured output for all of these (server starts → 3 tools + 1 resource +
1 resource template discovered → valid `search`/`aggregate` calls succeed →
invalid `search` (bad table) and `aggregate` (bad metric) calls return
`isError: true` with a readable message → both resources read correctly) is
saved in [`mcp_inspector_verification.log`](./mcp_inspector_verification.log).

Or launch the interactive Inspector UI:

```bash
npx @modelcontextprotocol/inspector ./.venv/bin/python mcp_server.py
```

## 6. Client Configuration Example

### Claude Code

A ready-to-use config is checked in at the repo root: [`../.mcp.json`](../.mcp.json).
It points at this project's venv interpreter, so no global install is needed.

```json
{
  "mcpServers": {
    "sqlite-lab": {
      "type": "stdio",
      "command": "/ABSOLUTE/PATH/TO/implementation/.venv/bin/python",
      "args": ["/ABSOLUTE/PATH/TO/implementation/mcp_server.py"],
      "env": { "DB_TYPE": "sqlite", "SQLITE_PATH": "/ABSOLUTE/PATH/TO/implementation/sqlite_lab.db" }
    }
  }
}
```

Open the project in Claude Code, approve the `sqlite-lab` server when
prompted, then reference the resource with `@sqlite-lab:schema://database` or
ask Claude to call `search` / `insert` / `aggregate`.

### Gemini CLI

```bash
gemini mcp add sqlite-lab /ABSOLUTE/PATH/TO/implementation/.venv/bin/python /ABSOLUTE/PATH/TO/implementation/mcp_server.py --description "SQLite lab FastMCP server" --timeout 10000
gemini mcp list
gemini --allowed-mcp-server-names sqlite-lab --yolo -p "search the students table for cohort A1"
```

## 8. Demo Video

[Watch on Google Drive](https://drive.google.com/file/d/12sm_nYL3xMmjVh3g05LbqfYMrxI4I-uj/view?usp=sharing) — 3 minute walkthrough covering:

- server/database setup (`init_db.py`, `pytest`)
- tool discovery via MCP Inspector CLI
- connecting Claude Code to this server via the repo's [`../.mcp.json`](../.mcp.json)
- a live `search` tool call from Claude Code (`search students table for cohort A1`)
- an invalid request (unknown table) demonstrating clear error handling

## 9. Deliverable Checklist

- [x] working FastMCP server (`mcp_server.py`)
- [x] SQLite database and seed data (`init_db.py`, `sqlite_lab.db`)
- [x] `search`, `insert`, `aggregate` tools
- [x] schema resource and schema resource template
- [x] verification steps (`tests/`, `verify_server.py`, MCP Inspector CLI log)
- [x] automated tests (`pytest`) and repeatable verification script
- [x] client configuration example (`../.mcp.json`, Gemini CLI command above)
- [x] README with setup and demo steps (this file)
- [x] Inspector startup command (§5.3)
- [x] short demo video (3 min) — [Google Drive link](https://drive.google.com/file/d/12sm_nYL3xMmjVh3g05LbqfYMrxI4I-uj/view?usp=sharing)
