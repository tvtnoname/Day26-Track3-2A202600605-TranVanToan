import os
import argparse
import json
import uvicorn
from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Load env configuration
load_dotenv()

# Create the FastMCP server
mcp = FastMCP("SQLite/Postgres Lab Server")

_adapter = None

def get_db():
    """Lazily load the database adapter so the server doesn't crash on startup if DB is offline."""
    global _adapter
    if _adapter is None:
        from db import get_adapter
        _adapter = get_adapter()
    return _adapter

class BearerAuthMiddleware:
    """Raw ASGI middleware to enforce Bearer Token authentication on all HTTP/SSE routes."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # We only intercept HTTP requests
        if scope["type"] == "http":
            expected_token = os.getenv("MCP_AUTH_TOKEN")
            
            # If a token is configured and this is not a CORS preflight request
            if expected_token and scope.get("method") != "OPTIONS":
                # Extract headers
                headers = dict(scope.get("headers", []))
                auth_header = headers.get(b"authorization", b"").decode("utf-8")
                
                if not auth_header.startswith("Bearer "):
                    await self._unauthorized(send, "Missing or malformed Bearer Token in Authorization header")
                    return
                
                token = auth_header.split(" ")[1]
                if token != expected_token:
                    await self._unauthorized(send, "Access token mismatch")
                    return

        # Continue to the app
        await self.app(scope, receive, send)

    async def _unauthorized(self, send, message):
        body = json.dumps({"error": f"Unauthorized: {message}"}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("utf-8")),
            ]
        })
        await send({
            "type": "http.response.body",
            "body": body,
            "more_body": False
        })



@mcp.tool(name="search")
def search(
    table: str, 
    filters: list | dict | None = None, 
    columns: list | None = None, 
    limit: int = 20, 
    offset: int = 0, 
    order_by: str | None = None, 
    descending: bool = False
) -> list:
    """
    Search and query records in the database with filtering, ordering, and pagination.
    
    Args:
        table: Name of the database table to query.
        filters: Filters to apply. Can be a dictionary of equality pairs {col: val} or list of dicts/tuples [col, op, val].
        columns: List of specific columns to return. Defaults to all columns (*).
        limit: Maximum number of records to return. Defaults to 20.
        offset: Offset for pagination. Defaults to 0.
        order_by: Column name to sort the results by.
        descending: Sort in descending order if True, otherwise ascending.
    """
    from db import ValidationError
    db = get_db()
    try:
        return db.search(
            table=table,
            columns=columns,
            filters=filters,
            limit=limit,
            offset=offset,
            order_by=order_by,
            descending=descending
        )
    except ValidationError as e:
        raise ValueError(str(e))


@mcp.tool(name="insert")
def insert(table: str, values: dict) -> dict:
    """
    Insert a new row into the specified table.
    
    Args:
        table: Name of the table.
        values: Dictionary mapping columns to their corresponding values.
    """
    from db import ValidationError
    db = get_db()
    try:
        return db.insert(table=table, values=values)
    except ValidationError as e:
        raise ValueError(str(e))


@mcp.tool(name="aggregate")
def aggregate(
    table: str, 
    metric: str, 
    column: str | None = None, 
    filters: list | dict | None = None, 
    group_by: str | list | None = None
) -> list:
    """
    Calculate aggregates (COUNT, AVG, SUM, MIN, MAX) with optional grouping and filtering.
    
    Args:
        table: Name of the table.
        metric: Aggregate function to execute ('count', 'avg', 'sum', 'min', 'max').
        column: Column to apply the metric on. (Optional for 'count', required for others).
        filters: Filters to apply before aggregation.
        group_by: Column name or list of columns to group the aggregation results by.
    """
    from db import ValidationError
    db = get_db()
    try:
        return db.aggregate(
            table=table,
            metric=metric,
            column=column,
            filters=filters,
            group_by=group_by
        )
    except ValidationError as e:
        raise ValueError(str(e))


@mcp.resource("schema://database")
def database_schema() -> str:
    """
    Read the schema of all user tables in the database.
    """
    db = get_db()
    tables = db.list_tables()
    schema = {}
    for t in tables:
        schema[t] = db.get_table_schema(t)
    return json.dumps(schema, indent=2)


@mcp.resource("schema://table/{table_name}")
def table_schema(table_name: str) -> str:
    """
    Read the schema of a specific table.
    """
    from db import ValidationError
    db = get_db()
    try:
        tables = db.list_tables()
        if table_name not in tables:
            raise ValidationError(f"Table '{table_name}' does not exist.")
        schema = db.get_table_schema(table_name)
        return json.dumps({table_name: schema}, indent=2)
    except ValidationError as e:
        raise ValueError(str(e))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start the Database FastMCP Server")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "sse"], help="Transport mechanism (stdio or sse)")
    parser.add_argument("--host", default="127.0.0.1", help="Host address for SSE server")
    parser.add_argument("--port", type=int, default=8000, help="Port for SSE server")
    args = parser.parse_args()

    if args.transport == "sse":
        print(f"Starting MCP Server on SSE transport...")
        # Get the underlying Starlette app configured for SSE
        app = mcp.http_app(transport="sse")
        
        # Add Bearer Token Auth middleware
        app.add_middleware(BearerAuthMiddleware)
        
        expected_token = os.getenv("MCP_AUTH_TOKEN")
        if expected_token:
            print("Bearer Token Authentication enabled.")
        else:
            print("WARNING: No MCP_AUTH_TOKEN set in environment. Running WITHOUT authentication.")
            
        print(f"Server is listening at http://{args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port)
    else:
        print("Starting MCP Server on STDIO transport (default)...")
        mcp.run(transport="stdio")
