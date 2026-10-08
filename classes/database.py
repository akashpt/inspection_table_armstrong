import sqlite3
from datetime import datetime
from path import DB_PATH

def _ensure_columns(cursor, table_name, columns):
    existing_columns = {
        row[1]
        for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    }

    for column_name, column_type in columns:
        if column_name not in existing_columns:
            cursor.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
            )

def get_connection():
    return sqlite3.connect(DB_PATH)


def create_database_and_tables():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # ---------------- TABLE 1 : shift_table ----------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS shift_table (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shift TEXT,
            shift_start_time TEXT,
            shift_end_time TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # ---------------- TABLE 2 : Operator Name Table ----------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS operator_table (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # ---------------- TABLE 3 : Roll Timing Table ----------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS roll_timing_table (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            roll_id INTEGER,
            start_time TEXT,
            end_time TEXT,
            operator_name TEXT,
            machine_number TEXT,
            job_id TEXT DEFAULT NULL
        )
    """)
    
    # ---------------- TABLE 4 : Defect Report Table ----------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS defect_report_table (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER,
        result TEXT,
        defect_meter INTEGER,
        roll_id TEXT,
        machine_number TEXT,
        defect_code TEXT,
        defect_type TEXT,
        x INTEGER,
        y INTEGER,
        timestamp TEXT DEFAULT (datetime('now', 'localtime')),
        image_path TEXT
    )""")

    _ensure_columns(
        cursor,
        "roll_timing_table",
        (
            ("operator_name", "TEXT"),
            ("machine_number", "TEXT"),
            ("job_id", "TEXT DEFAULT NULL"),
        ),
    )

    default_shifts = (
        ("A", "06:00:00", "14:00:00"),
        ("B", "14:00:00", "22:00:00"),
        ("C", "22:00:00", "06:00:00"),
    )
    for shift, start_time, end_time in default_shifts:
        cursor.execute("DELETE FROM shift_table WHERE shift = ?", (shift,))
        cursor.execute(
            """
            INSERT INTO shift_table (shift, shift_start_time, shift_end_time)
            VALUES (?, ?, ?)
            """,
            (shift, start_time, end_time),
        )

    conn.commit()
    conn.close()

    print("Tables created successfully")


def get_current_shift_name():
    connection = None

    try:
        connection = sqlite3.connect(DB_PATH)
        cursor = connection.cursor()

        current_time = datetime.now().strftime("%H:%M:%S")

        rows = cursor.execute("""
            SELECT
                shift,
                shift_start_time,
                shift_end_time
            FROM shift_table
            ORDER BY id ASC
        """).fetchall()

        for shift, start_time, end_time in rows:

            # Normal shift
            # Example: 06:00 -> 14:00
            if start_time < end_time:
                if start_time <= current_time < end_time:
                    return shift

            # Night shift
            # Example: 22:00 -> 06:00
            else:
                if (
                    current_time >= start_time
                    or current_time < end_time
                ):
                    return shift

        return ""

    except Exception as error:
        print("❌ Get current shift error:", error)
        return ""

    finally:
        if connection:
            connection.close()