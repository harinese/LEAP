import sqlite3
import os
from typing import Optional, Dict, Any, List

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "setu_agent.db")

def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Unified Caller Profiles (Zero Sign-up, CLI Authenticated)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS caller_profiles (
            phone TEXT PRIMARY KEY,
            name TEXT DEFAULT 'Caller',
            preferred_language TEXT DEFAULT 'kn',
            total_calls INTEGER DEFAULT 1,
            last_role TEXT DEFAULT 'DRIVER',
            reputation_score REAL DEFAULT 5.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 2. Telephony Sessions Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS calls (
            call_sid TEXT PRIMARY KEY,
            stream_sid TEXT,
            caller_phone TEXT,
            language TEXT DEFAULT 'kn',
            status TEXT DEFAULT 'IN_PROGRESS',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP
        );
    """)

    # 3. Utterances Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            call_sid TEXT,
            speaker TEXT NOT NULL,
            text TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (call_sid) REFERENCES calls(call_sid)
        );
    """)

    # 4. Ephemeral Return Trucks (Registered via Voice Call)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trucks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            call_sid TEXT,
            phone TEXT NOT NULL,
            driver_name TEXT DEFAULT 'Driver',
            truck_type TEXT NOT NULL,
            capacity_tonnes REAL NOT NULL,
            current_location TEXT NOT NULL DEFAULT 'APMC Amargol Yard',
            destination TEXT NOT NULL,
            departure_time TEXT DEFAULT 'Today evening',
            min_price REAL DEFAULT 0,
            status TEXT DEFAULT 'AVAILABLE',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (phone) REFERENCES caller_profiles(phone)
        );
    """)

    # 5. Mandi Agricultural Cargo (Posted via Voice Call or Web)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS loads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            call_sid TEXT,
            phone TEXT NOT NULL,
            shipper_name TEXT DEFAULT 'Trader',
            cargo_type TEXT NOT NULL,
            weight_tonnes REAL NOT NULL,
            pickup_location TEXT NOT NULL DEFAULT 'APMC Amargol Yard',
            destination TEXT NOT NULL,
            ready_time TEXT DEFAULT 'Ready now',
            max_budget REAL DEFAULT 0,
            status TEXT DEFAULT 'PENDING',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (phone) REFERENCES caller_profiles(phone)
        );
    """)

    # 6. Two-Party Matches & SMS Delivery Tracking
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            truck_id INTEGER NOT NULL,
            load_id INTEGER NOT NULL,
            route_score REAL NOT NULL,
            capacity_score REAL NOT NULL,
            overall_score REAL NOT NULL,
            agreed_price REAL NOT NULL,
            driver_accepted INTEGER DEFAULT 0,
            shipper_accepted INTEGER DEFAULT 1,
            status TEXT DEFAULT 'OFFERED',
            booking_token TEXT NOT NULL,
            sms_sent_driver INTEGER DEFAULT 0,
            sms_sent_shipper INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (truck_id) REFERENCES trucks(id) ON DELETE CASCADE,
            FOREIGN KEY (load_id) REFERENCES loads(id) ON DELETE CASCADE
        );
    """)

    # Indices for high-speed telephony lookups
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trucks_dest_status ON trucks(destination, status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_loads_dest_status ON loads(destination, status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);")

    conn.commit()

    # Seed initial inventory if empty
    cursor.execute("SELECT count(*) as count FROM loads;")
    if cursor.fetchone()["count"] == 0:
        seed_inventory(conn)

    conn.close()

def seed_inventory(conn: sqlite3.Connection):
    cursor = conn.cursor()
    initial_profiles = [
        ("+919448011221", "Shivanand Kulkarni", "kn", "SHIPPER"),
        ("+919448011222", "Ramesh Byadgi", "kn", "SHIPPER"),
        ("+919448011223", "Mallikarjun Traders", "kn", "SHIPPER"),
        ("+919845012341", "Manjunath Patil", "kn", "DRIVER"),
        ("+919845012342", "Suresh Gowda", "kn", "DRIVER"),
        ("+919845012343", "Basavaraj Hiremath", "kn", "DRIVER"),
    ]
    cursor.executemany("""
        INSERT OR IGNORE INTO caller_profiles (phone, name, preferred_language, last_role)
        VALUES (?, ?, ?, ?)
    """, initial_profiles)

    initial_loads = [
        ("+919448011221", "Shivanand Kulkarni", "Onion Bags", 15.0, "APMC Shed 4", "Bengaluru", "Today 18:00", 19500),
        ("+919448011222", "Ramesh Byadgi", "Dry Red Chilli", 8.5, "APMC Chilli Gate 2", "Davanagere", "Today 19:30", 5800),
        ("+919448011223", "Mallikarjun Traders", "Bellary Red Onions", 14.0, "APMC Shed 9", "Belagavi", "Today 17:30", 6500),
        ("+919448011224", "Annapurna Agro", "Pressed Cotton Bales", 22.0, "Tarihal Agro Godown", "Bengaluru", "Today 21:00", 25000),
        ("+919448011225", "Ningappa Pujar", "Maize Grains", 18.0, "Platform 3", "Pune", "Tomorrow 06:00", 23000),
    ]
    cursor.executemany("""
        INSERT INTO loads (phone, shipper_name, cargo_type, weight_tonnes, pickup_location, destination, ready_time, max_budget)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, initial_loads)

    initial_trucks = [
        ("+919845012341", "Manjunath Patil", "10-Wheeler Open Body", 16.0, "APMC Gate 1", "Belagavi", "Today 18:00", 5000),
        ("+919845012342", "Suresh Gowda", "6-Wheeler 17ft", 9.0, "Weighbridge 2", "Davanagere", "Today 19:00", 4500),
        ("+919845012343", "Basavaraj Hiremath", "12-Wheeler 24T", 24.0, "APMC Platform 1", "Bengaluru", "Today 20:30", 18000),
    ]
    cursor.executemany("""
        INSERT INTO trucks (phone, driver_name, truck_type, capacity_tonnes, current_location, destination, departure_time, min_price)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, initial_trucks)

    conn.commit()

def get_or_create_caller_profile(phone: str, default_lang: str = "kn") -> Dict[str, Any]:
    if not phone or phone == "anonymous":
        phone = "+919845099999"

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM caller_profiles WHERE phone = ?", (phone,))
    row = cursor.fetchone()

    if row:
        cursor.execute("""
            UPDATE caller_profiles
            SET total_calls = total_calls + 1, updated_at = CURRENT_TIMESTAMP
            WHERE phone = ?
        """, (phone,))
        conn.commit()
        profile = dict(row)
    else:
        cursor.execute("""
            INSERT INTO caller_profiles (phone, preferred_language, total_calls)
            VALUES (?, ?, 1)
        """, (phone, default_lang))
        conn.commit()
        profile = {
            "phone": phone,
            "name": "Caller",
            "preferred_language": default_lang,
            "total_calls": 1,
            "last_role": "DRIVER",
            "reputation_score": 5.0
        }

    conn.close()
    return profile

def update_caller_name(phone: str, name: str):
    if not name or name in ["Caller", "Driver", "Trader"]:
        return
    conn = get_connection()
    with conn:
        conn.execute("""
            UPDATE caller_profiles
            SET name = ?, updated_at = CURRENT_TIMESTAMP
            WHERE phone = ?
        """, (name, phone))
    conn.close()

def expire_stale_records():
    """Expires ephemeral AVAILABLE trucks, PENDING loads, and OFFERED matches older than 1 hour (anti-stale TTL)."""
    conn = get_connection()
    with conn:
        conn.execute("""
            UPDATE trucks
            SET status = 'EXPIRED'
            WHERE status = 'AVAILABLE' AND call_sid IS NOT NULL AND created_at < datetime('now', '-1 hour')
        """)
        conn.execute("""
            UPDATE loads
            SET status = 'EXPIRED'
            WHERE status = 'PENDING' AND call_sid IS NOT NULL AND created_at < datetime('now', '-1 hour')
        """)
        conn.execute("""
            UPDATE matches
            SET status = 'EXPIRED', updated_at = CURRENT_TIMESTAMP
            WHERE status = 'OFFERED' AND created_at < datetime('now', '-1 hour')
        """)
    conn.close()

def update_caller_role(phone: str, role: str, language: Optional[str] = None):
    conn = get_connection()
    with conn:
        if language:
            conn.execute("""
                UPDATE caller_profiles
                SET last_role = ?, preferred_language = ?, updated_at = CURRENT_TIMESTAMP
                WHERE phone = ?
            """, (role, language, phone))
        else:
            conn.execute("""
                UPDATE caller_profiles
                SET last_role = ?, updated_at = CURRENT_TIMESTAMP
                WHERE phone = ?
            """, (role, phone))
    conn.close()

def log_call_start(call_sid: str, stream_sid: str, caller_phone: str = ""):
    get_or_create_caller_profile(caller_phone)
    expire_stale_records()
    conn = get_connection()
    with conn:
        conn.execute("""
            INSERT OR REPLACE INTO calls (call_sid, stream_sid, caller_phone, status)
            VALUES (?, ?, ?, 'IN_PROGRESS')
        """, (call_sid, stream_sid, caller_phone))
    conn.close()

def log_call_end(call_sid: str):
    conn = get_connection()
    with conn:
        conn.execute("""
            UPDATE calls
            SET status = 'COMPLETED', ended_at = CURRENT_TIMESTAMP
            WHERE call_sid = ? OR stream_sid = ?
        """, (call_sid, call_sid))
    conn.close()

def save_utterance(call_sid: str, speaker: str, text: str):
    conn = get_connection()
    with conn:
        conn.execute("""
            INSERT INTO conversations (call_sid, speaker, text)
            VALUES (?, ?, ?)
        """, (call_sid, speaker, text))
    conn.close()

def register_truck(phone: str, destination: str, capacity: float, truck_type: str = "Truck",
                   driver_name: str = "Driver", min_price: float = 0, call_sid: str = "") -> int:
    get_or_create_caller_profile(phone)
    update_caller_role(phone, "DRIVER")
    if driver_name and driver_name != "Driver":
        update_caller_name(phone, driver_name)
    expire_stale_records()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO trucks (call_sid, phone, driver_name, truck_type, capacity_tonnes, destination, min_price, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'AVAILABLE')
    """, (call_sid, phone, driver_name, truck_type, capacity, destination, min_price))
    truck_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return truck_id

def register_load(phone: str, destination: str, weight: float, cargo: str = "Agri Produce",
                  shipper_name: str = "Trader", max_budget: float = 0, call_sid: str = "") -> int:
    get_or_create_caller_profile(phone)
    update_caller_role(phone, "SHIPPER")
    if shipper_name and shipper_name != "Trader":
        update_caller_name(phone, shipper_name)
    expire_stale_records()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO loads (call_sid, phone, shipper_name, cargo_type, weight_tonnes, destination, max_budget, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')
    """, (call_sid, phone, shipper_name, cargo, weight, destination, max_budget))
    load_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return load_id

def get_all_trucks():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM trucks ORDER BY created_at DESC LIMIT 20").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_loads():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM loads ORDER BY created_at DESC LIMIT 20").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_matches():
    conn = get_connection()
    query = """
        SELECT m.*, 
               t.driver_name, t.phone as driver_phone, t.truck_type, t.capacity_tonnes,
               l.shipper_name, l.phone as shipper_phone, l.cargo_type, l.weight_tonnes, l.pickup_location, l.destination
        FROM matches m
        JOIN trucks t ON m.truck_id = t.id
        JOIN loads l ON m.load_id = l.id
        ORDER BY m.created_at DESC LIMIT 20
    """
    rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_profiles():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM caller_profiles ORDER BY updated_at DESC LIMIT 20").fetchall()
    conn.close()
    return [dict(r) for r in rows]
