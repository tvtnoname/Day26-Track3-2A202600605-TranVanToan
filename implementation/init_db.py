import os
from dotenv import load_dotenv

# Load environmental variables from .env
load_dotenv()

from db import get_adapter

SCHEMA_SQL_SQLITE = """
DROP TABLE IF EXISTS enrollments;
DROP TABLE IF EXISTS students;
DROP TABLE IF EXISTS courses;

CREATE TABLE students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    cohort TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE
);

CREATE TABLE courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    instructor TEXT NOT NULL
);

CREATE TABLE enrollments (
    student_id INTEGER,
    course_id INTEGER,
    score REAL,
    PRIMARY KEY (student_id, course_id),
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
);
"""

SEED_SQL_SQLITE = """
INSERT INTO students (name, cohort, email) VALUES 
('Alice Smith', 'A1', 'alice@example.com'),
('Bob Johnson', 'A1', 'bob@example.com'),
('Charlie Brown', 'B2', 'charlie@example.com'),
('Diana Prince', 'B2', 'diana@example.com');

INSERT INTO courses (title, instructor) VALUES
('Introduction to Computer Science', 'Dr. Adams'),
('Database Systems', 'Prof. Baker'),
('Machine Learning', 'Dr. Clark');

INSERT INTO enrollments (student_id, course_id, score) VALUES
(1, 1, 95.0),
(1, 2, 88.5),
(2, 1, 79.0),
(2, 3, 91.0),
(3, 2, 85.0),
(3, 3, 73.5),
(4, 1, 98.0),
(4, 3, 90.0);
"""

SCHEMA_SQL_POSTGRES = """
DROP TABLE IF EXISTS enrollments CASCADE;
DROP TABLE IF EXISTS students CASCADE;
DROP TABLE IF EXISTS courses CASCADE;

CREATE TABLE students (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    cohort VARCHAR(20) NOT NULL,
    email VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE courses (
    id SERIAL PRIMARY KEY,
    title VARCHAR(100) NOT NULL,
    instructor VARCHAR(100) NOT NULL
);

CREATE TABLE enrollments (
    student_id INTEGER,
    course_id INTEGER,
    score NUMERIC(5, 2),
    PRIMARY KEY (student_id, course_id),
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
);
"""

SEED_SQL_POSTGRES = """
INSERT INTO students (id, name, cohort, email) VALUES 
(1, 'Alice Smith', 'A1', 'alice@example.com'),
(2, 'Bob Johnson', 'A1', 'bob@example.com'),
(3, 'Charlie Brown', 'B2', 'charlie@example.com'),
(4, 'Diana Prince', 'B2', 'diana@example.com');

INSERT INTO courses (id, title, instructor) VALUES
(1, 'Introduction to Computer Science', 'Dr. Adams'),
(2, 'Database Systems', 'Prof. Baker'),
(3, 'Machine Learning', 'Dr. Clark');

INSERT INTO enrollments (student_id, course_id, score) VALUES
(1, 1, 95.0),
(1, 2, 88.5),
(2, 1, 79.0),
(2, 3, 91.0),
(3, 2, 85.0),
(3, 3, 73.5),
(4, 1, 98.0),
(4, 3, 90.0);

-- Adjust sequence values after manual IDs insertion
SELECT setval('students_id_seq', (SELECT MAX(id) FROM students));
SELECT setval('courses_id_seq', (SELECT MAX(id) FROM courses));
"""

def create_database():
    db_type = os.getenv("DB_TYPE", "sqlite").lower()
    print(f"Initializing {db_type.upper()} database...")
    
    adapter = get_adapter()
    
    # We will get a raw connection to run scripts
    conn = adapter.connect()
    try:
        cursor = conn.cursor()
        if db_type == "sqlite":
            # sqlite3 execute_script (executescript) handles multiple statements separated by semicolon
            script = SCHEMA_SQL_SQLITE + "\n" + SEED_SQL_SQLITE
            cursor.executescript(script)
        else:
            # psycopg2 needs separate executions or run script
            cursor.execute(SCHEMA_SQL_POSTGRES)
            cursor.execute(SEED_SQL_POSTGRES)
        conn.commit()
        print("Database schema created and seeded successfully!")
    except Exception as e:
        conn.rollback()
        print(f"Error initializing database: {e}")
        raise e
    finally:
        conn.close()

if __name__ == "__main__":
    create_database()
