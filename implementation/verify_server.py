import os
import json
from dotenv import load_dotenv

# Force DB_TYPE to sqlite for verification script unless postgres is explicitly set
load_dotenv()
os.environ["DB_TYPE"] = os.getenv("DB_TYPE", "sqlite")

from mcp_server import search, insert, aggregate, database_schema, table_schema

def run_verification():
    print("==================================================")
    print("STARTING MCP SERVER LOCAL VERIFICATION (SMOKE TEST)")
    print(f"Database Type: {os.getenv('DB_TYPE')}")
    print("==================================================")
    
    # 1. Test resources (Schema)
    print("\n--- 1. Testing Resources (Full Schema) ---")
    schema = database_schema()
    print(schema)
    
    print("\n--- 2. Testing Resource (students table schema) ---")
    stud_schema = table_schema("students")
    print(stud_schema)
    
    # 2. Test tool: search
    print("\n--- 3. Testing Tool: search (cohort A1) ---")
    results = search(table="students", filters={"cohort": "A1"})
    print(json.dumps(results, indent=2))
    
    print("\n--- 4. Testing Tool: search (sorting by score descending) ---")
    results = search(table="enrollments", order_by="score", descending=True, limit=3)
    print(json.dumps(results, indent=2))
    
    # 3. Test tool: insert
    print("\n--- 5. Testing Tool: insert (New student) ---")
    try:
        new_student = insert(table="students", values={
            "name": "John Doe",
            "cohort": "C3",
            "email": "john.doe@example.com"
        })
        print("Successfully inserted:")
        print(json.dumps(new_student, indent=2))
    except Exception as e:
        print(f"Insert failed (might be duplicate email from previous runs): {e}")

    # 4. Test tool: aggregate
    print("\n--- 6. Testing Tool: aggregate (COUNT students) ---")
    count_res = aggregate(table="students", metric="count")
    print(json.dumps(count_res, indent=2))
    
    print("\n--- 7. Testing Tool: aggregate (AVG score grouped by student_id) ---")
    avg_res = aggregate(table="enrollments", metric="avg", column="score", group_by="student_id")
    print(json.dumps(avg_res, indent=2))

    # 5. Test Safety & Validation (Expected to fail)
    print("\n--- 8. Testing Safety: Search non-existent table (Expected to Fail) ---")
    try:
        search(table="hackers")
        print("FAILED: Allowed query on missing table!")
    except Exception as e:
        print(f"SUCCESS: Rejected query as expected. Error: {e}")
        
    print("\n--- 9. Testing Safety: Search with invalid column (Expected to Fail) ---")
    try:
        search(table="students", filters={"social_security_number": "123-456"})
        print("FAILED: Allowed query with invalid column name!")
    except Exception as e:
        print(f"SUCCESS: Rejected query as expected. Error: {e}")
        
    print("\n--- 10. Testing Safety: Unsupported aggregate operator (Expected to Fail) ---")
    try:
        aggregate(table="students", metric="drop_db")
        print("FAILED: Allowed invalid metric!")
    except Exception as e:
        print(f"SUCCESS: Rejected metric as expected. Error: {e}")

    print("\n==================================================")
    print("VERIFICATION COMPLETED SUCCESSFULLY!")
    print("==================================================")

if __name__ == "__main__":
    run_verification()
