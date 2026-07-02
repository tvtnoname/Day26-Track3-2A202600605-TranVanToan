import os
import sqlite3
from abc import ABC, abstractmethod
import psycopg2
from psycopg2.extras import RealDictCursor

class ValidationError(Exception):
    """Exception raised when database inputs fail security or schema validation."""
    pass

class DatabaseAdapter(ABC):
    """Abstract Base Class defining the interface for DB adapters."""
    
    @property
    @abstractmethod
    def placeholder(self):
        """Returns the SQL placeholder character (? or %s)."""
        pass

    @abstractmethod
    def connect(self):
        """Establishes and returns a database connection."""
        pass

    @abstractmethod
    def list_tables(self):
        """Returns a list of user table names in the database."""
        pass

    @abstractmethod
    def get_table_schema(self, table_name):
        """Returns a dictionary mapping column names to their types for a given table."""
        pass

    def validate_identifier(self, table_name, columns=None):
        """
        Validates that the table exists and columns belong to the table.
        Raises ValidationError if any check fails.
        """
        tables = self.list_tables()
        if table_name not in tables:
            raise ValidationError(f"Table '{table_name}' does not exist in database.")
        
        if columns:
            schema = self.get_table_schema(table_name)
            for col in columns:
                if col not in schema:
                    raise ValidationError(f"Column '{col}' does not exist in table '{table_name}'.")

    def _parse_filters(self, table_name, filters):
        """Helper to parse filters into a standard format and validate columns."""
        parsed = []
        schema = self.get_table_schema(table_name)
        
        if isinstance(filters, dict):
            for col, val in filters.items():
                parsed.append({"column": col, "operator": "=", "value": val})
        elif isinstance(filters, list):
            for idx, f in enumerate(filters):
                if isinstance(f, dict):
                    if "column" not in f or "operator" not in f or "value" not in f:
                        raise ValidationError(f"Filter at index {idx} must contain 'column', 'operator', and 'value'.")
                    parsed.append(f)
                elif isinstance(f, (list, tuple)) and len(f) == 3:
                    parsed.append({"column": f[0], "operator": f[1], "value": f[2]})
                else:
                    raise ValidationError(f"Invalid filter format at index {idx}.")
        elif filters is not None:
            raise ValidationError("Filters must be a list or a dictionary.")

        # Validate columns and operators
        allowed_operators = {"=", "!=", ">", "<", ">=", "<=", "LIKE", "IN"}
        for f in parsed:
            col = f["column"]
            op = f["operator"].upper()
            if col not in schema:
                raise ValidationError(f"Filter column '{col}' does not exist in table '{table_name}'.")
            if op not in allowed_operators:
                raise ValidationError(f"Unsupported filter operator '{op}'. Allowed: {allowed_operators}")
                
        return parsed

    def _build_where_clause(self, parsed_filters):
        """Helper to construct the WHERE SQL clause and collect query parameters."""
        if not parsed_filters:
            return "", []
        
        where_parts = []
        params = []
        for f in parsed_filters:
            col = f["column"]
            op = f["operator"].upper()
            val = f["value"]
            
            if op == "IN":
                if not isinstance(val, (list, tuple)):
                    raise ValidationError("Value for 'IN' operator must be a list or tuple.")
                placeholders = ", ".join([self.placeholder] * len(val))
                where_parts.append(f'"{col}" IN ({placeholders})')
                params.extend(val)
            else:
                where_parts.append(f'"{col}" {op} {self.placeholder}')
                params.append(val)
                
        return "WHERE " + " AND ".join(where_parts), params

    @abstractmethod
    def search(self, table, columns=None, filters=None, limit=20, offset=0, order_by=None, descending=False):
        pass

    @abstractmethod
    def insert(self, table, values):
        pass

    @abstractmethod
    def aggregate(self, table, metric, column=None, filters=None, group_by=None):
        pass


class SQLiteAdapter(DatabaseAdapter):
    """SQLite implementation of the DatabaseAdapter."""
    
    def __init__(self, db_path):
        self.db_path = db_path

    @property
    def placeholder(self):
        return "?"

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def list_tables(self):
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
            return [row["name"] for row in cursor.fetchall()]

    def get_table_schema(self, table_name):
        # We need to make sure the table exists to prevent SQL injection in PRAGMA statement
        tables = self.list_tables()
        if table_name not in tables:
            raise ValidationError(f"Table '{table_name}' does not exist.")
            
        with self.connect() as conn:
            cursor = conn.cursor()
            # PRAGMA doesn't accept parameters, but since we whitelisted table_name, it's 100% safe.
            cursor.execute(f"PRAGMA table_info(\"{table_name}\");")
            return {row["name"]: row["type"].upper() for row in cursor.fetchall()}

    def search(self, table, columns=None, filters=None, limit=20, offset=0, order_by=None, descending=False):
        self.validate_identifier(table, columns)
        if order_by:
            self.validate_identifier(table, [order_by])
            
        parsed_filters = self._parse_filters(table, filters)
        where_clause, params = self._build_where_clause(parsed_filters)
        
        select_cols = ", ".join([f'"{c}"' for c in columns]) if columns else "*"
        sql = f"SELECT {select_cols} FROM \"{table}\" {where_clause}"
        
        if order_by:
            direction = "DESC" if descending else "ASC"
            sql += f" ORDER BY \"{order_by}\" {direction}"
            
        sql += f" LIMIT {self.placeholder} OFFSET {self.placeholder}"
        params.extend([limit, offset])
        
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    def insert(self, table, values):
        if not values:
            raise ValidationError("Cannot perform an empty insert.")
            
        self.validate_identifier(table, list(values.keys()))
        
        cols = list(values.keys())
        placeholders = ", ".join([self.placeholder] * len(cols))
        col_str = ", ".join([f'"{c}"' for c in cols])
        sql = f"INSERT INTO \"{table}\" ({col_str}) VALUES ({placeholders});"
        
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, list(values.values()))
            row_id = cursor.lastrowid
            conn.commit()
            
            # Retrieve the inserted row
            cursor.execute(f"SELECT * FROM \"{table}\" WHERE rowid = ?;", (row_id,))
            row = cursor.fetchone()
            return dict(row) if row else values

    def aggregate(self, table, metric, column=None, filters=None, group_by=None):
        metric = metric.lower()
        if metric not in {"count", "avg", "sum", "min", "max"}:
            raise ValidationError(f"Unsupported aggregate metric '{metric}'.")
            
        self.validate_identifier(table)
        
        if column and column != "*":
            self.validate_identifier(table, [column])
        elif not column and metric != "count":
            raise ValidationError(f"Column is required for aggregate metric '{metric}'.")
            
        group_by_cols = []
        if group_by:
            if isinstance(group_by, str):
                group_by_cols = [group_by]
            elif isinstance(group_by, list):
                group_by_cols = group_by
            else:
                raise ValidationError("Group by must be a string or a list of strings.")
            self.validate_identifier(table, group_by_cols)
            
        parsed_filters = self._parse_filters(table, filters)
        where_clause, params = self._build_where_clause(parsed_filters)
        
        col_expr = "*" if not column or column == "*" else f'"{column}"'
        select_expr = f"{metric.upper()}({col_expr}) AS value"
        
        if group_by_cols:
            grp_select = ", ".join([f'"{c}"' for c in group_by_cols])
            select_expr = f"{grp_select}, {select_expr}"
            
        sql = f"SELECT {select_expr} FROM \"{table}\" {where_clause}"
        
        if group_by_cols:
            grp_clause = ", ".join([f'"{c}"' for c in group_by_cols])
            sql += f" GROUP BY {grp_clause}"
            
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]


class PostgreSQLAdapter(DatabaseAdapter):
    """PostgreSQL implementation of the DatabaseAdapter."""
    
    def __init__(self, uri):
        self.uri = uri

    @property
    def placeholder(self):
        return "%s"

    def connect(self):
        return psycopg2.connect(self.uri, cursor_factory=RealDictCursor)

    def list_tables(self):
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_type='BASE TABLE';"
                )
                return [row["table_name"] for row in cursor.fetchall()]

    def get_table_schema(self, table_name):
        tables = self.list_tables()
        if table_name not in tables:
            raise ValidationError(f"Table '{table_name}' does not exist.")
            
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s;",
                    (table_name,)
                )
                return {row["column_name"]: row["data_type"].upper() for row in cursor.fetchall()}

    def _clean_row(self, row):
        if not row:
            return row
        parsed_row = {}
        for k, v in row.items():
            if type(v).__name__ == 'Decimal':
                parsed_row[k] = float(v) if v is not None else None
            else:
                parsed_row[k] = v
        return parsed_row

    def _clean_decimals(self, rows):
        if not rows:
            return rows
        return [self._clean_row(row) for row in rows]

    def search(self, table, columns=None, filters=None, limit=20, offset=0, order_by=None, descending=False):
        self.validate_identifier(table, columns)
        if order_by:
            self.validate_identifier(table, [order_by])
            
        parsed_filters = self._parse_filters(table, filters)
        where_clause, params = self._build_where_clause(parsed_filters)
        
        select_cols = ", ".join([f'"{c}"' for c in columns]) if columns else "*"
        sql = f"SELECT {select_cols} FROM \"{table}\" {where_clause}"
        
        if order_by:
            direction = "DESC" if descending else "ASC"
            sql += f" ORDER BY \"{order_by}\" {direction}"
            
        sql += f" LIMIT {self.placeholder} OFFSET {self.placeholder}"
        params.extend([limit, offset])
        
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return self._clean_decimals(cursor.fetchall())

    def insert(self, table, values):
        if not values:
            raise ValidationError("Cannot perform an empty insert.")
            
        self.validate_identifier(table, list(values.keys()))
        
        cols = list(values.keys())
        placeholders = ", ".join([self.placeholder] * len(cols))
        col_str = ", ".join([f'"{c}"' for c in cols])
        sql = f"INSERT INTO \"{table}\" ({col_str}) VALUES ({placeholders}) RETURNING *;"
        
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, list(values.values()))
                row = cursor.fetchone()
                conn.commit()
                return self._clean_row(row) if row else values

    def aggregate(self, table, metric, column=None, filters=None, group_by=None):
        metric = metric.lower()
        if metric not in {"count", "avg", "sum", "min", "max"}:
            raise ValidationError(f"Unsupported aggregate metric '{metric}'.")
            
        self.validate_identifier(table)
        
        if column and column != "*":
            self.validate_identifier(table, [column])
        elif not column and metric != "count":
            raise ValidationError(f"Column is required for aggregate metric '{metric}'.")
            
        group_by_cols = []
        if group_by:
            if isinstance(group_by, str):
                group_by_cols = [group_by]
            elif isinstance(group_by, list):
                group_by_cols = group_by
            else:
                raise ValidationError("Group by must be a string or a list of strings.")
            self.validate_identifier(table, group_by_cols)
            
        parsed_filters = self._parse_filters(table, filters)
        where_clause, params = self._build_where_clause(parsed_filters)
        
        col_expr = "*" if not column or column == "*" else f'"{column}"'
        select_expr = f"{metric.upper()}({col_expr}) AS value"
        
        if group_by_cols:
            grp_select = ", ".join([f'"{c}"' for c in group_by_cols])
            select_expr = f"{grp_select}, {select_expr}"
            
        sql = f"SELECT {select_expr} FROM \"{table}\" {where_clause}"
        
        if group_by_cols:
            grp_clause = ", ".join([f'"{c}"' for c in group_by_cols])
            sql += f" GROUP BY {grp_clause}"
            
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return self._clean_decimals(cursor.fetchall())


def get_adapter():
    """Factory function to load adapter based on env variables."""
    db_type = os.getenv("DB_TYPE", "sqlite").lower()
    if db_type == "sqlite":
        db_path = os.getenv("SQLITE_PATH", "sqlite_lab.db")
        return SQLiteAdapter(db_path)
    elif db_type == "postgres":
        uri = os.getenv("POSTGRES_URI", "postgresql://postgres:postgres@localhost:5432/mcp_db")
        return PostgreSQLAdapter(uri)
    else:
        raise ValueError(f"Unknown DB_TYPE: {db_type}. Use 'sqlite' or 'postgres'.")
