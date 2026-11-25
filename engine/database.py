import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional
from .auth import hash_password

DB_PATH = "nps_records.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'tech',
            password_hash TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cur.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            contact_name TEXT,
            phone TEXT,
            email TEXT,
            address TEXT,
            notes TEXT,
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS key_systems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            system_name TEXT NOT NULL,
            keyway_code TEXT,
            profile_json TEXT NOT NULL,
            keys_json TEXT NOT NULL,
            doors_json TEXT NOT NULL,
            created_by TEXT,
            created_at TEXT,
            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
        )
    """)
    if cur.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO users (username, full_name, role, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            ("admin", "NP Solutions Admin", "admin", hash_password("npsadmin"), datetime.utcnow().isoformat())
        )
    cur.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('company_name', 'NP Solutions')")
    cur.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('logo_data_url', '')")
    conn.commit()
    conn.close()

def get_settings() -> Dict[str, str]:
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}

def update_setting(key: str, value: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def get_user_by_username(username: str) -> Optional[Dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE username = ? AND is_active = 1", (username.strip().lower(),)).fetchone()
    conn.close()
    return dict(row) if row else None

def create_session(token: str, user_id: str):
    conn = get_conn()
    conn.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)", (token, int(user_id), datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def get_user_by_token(token: str) -> Optional[Dict]:
    if not token:
        return None
    conn = get_conn()
    row = conn.execute("""
        SELECT u.id, u.username, u.full_name, u.role, u.is_active
        FROM sessions s JOIN users u ON s.user_id = u.id
        WHERE s.token = ? AND u.is_active = 1
    """, (token,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["id"] = str(d["id"])
    return d

def delete_session(token: str):
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()

def list_users() -> List[Dict]:
    conn = get_conn()
    rows = conn.execute("SELECT id, username, full_name, role, is_active, created_at FROM users ORDER BY id ASC").fetchall()
    conn.close()
    res = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        res.append(d)
    return res

def create_user(username: str, full_name: str, role: str, password: str) -> str:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (username, full_name, role, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
        (username.strip().lower(), full_name.strip(), role, hash_password(password), datetime.utcnow().isoformat())
    )
    uid = str(cur.lastrowid)
    conn.commit()
    conn.close()
    return uid

def update_user_role_or_status(user_id: str, role: str, is_active: int):
    conn = get_conn()
    conn.execute("UPDATE users SET role = ?, is_active = ? WHERE id = ?", (role, is_active, int(user_id)))
    conn.commit()
    conn.close()

def create_client(data: Dict) -> str:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO clients (company_name, contact_name, phone, email, address, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        data["company_name"], data.get("contact_name", ""), data.get("phone", ""),
        data.get("email", ""), data.get("address", ""), data.get("notes", ""),
        datetime.utcnow().isoformat()
    ))
    cid = str(cur.lastrowid)
    conn.commit()
    conn.close()
    return cid

def list_clients() -> List[Dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM clients ORDER BY company_name ASC").fetchall()
    conn.close()
    res = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        res.append(d)
    return res

def save_key_system(client_id: str, system_name: str, keyway_code: str, profile: Dict, keys: List[Dict], doors: List[Dict], created_by: str) -> str:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO key_systems (client_id, system_name, keyway_code, profile_json, keys_json, doors_json, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        int(client_id), system_name, keyway_code,
        json.dumps(profile), json.dumps(keys), json.dumps(doors),
        created_by, datetime.utcnow().isoformat()
    ))
    sid = str(cur.lastrowid)
    conn.commit()
    conn.close()
    return sid

def list_client_systems(client_id: str) -> List[Dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, client_id, system_name, keyway_code, created_by, created_at FROM key_systems WHERE client_id = ? ORDER BY id DESC",
        (int(client_id),)
    ).fetchall()
    conn.close()
    res = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        d["client_id"] = str(d["client_id"])
        res.append(d)
    return res

def get_key_system(system_id: str) -> Optional[Dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM key_systems WHERE id = ?", (int(system_id),)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["id"] = str(d["id"])
    d["client_id"] = str(d["client_id"])
    d["profile"] = json.loads(d.pop("profile_json"))
    d["keys"] = json.loads(d.pop("keys_json"))
    d["doors"] = json.loads(d.pop("doors_json"))
    return d
