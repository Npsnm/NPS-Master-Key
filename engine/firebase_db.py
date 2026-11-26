import os
from datetime import datetime
from typing import Dict, List, Optional
import firebase_admin
from firebase_admin import credentials, firestore
from .auth import hash_password

CRED_PATH = os.getenv("FIREBASE_CREDENTIALS", "firebase_key.json")
PROJECT_ID = (
    os.getenv("GOOGLE_CLOUD_PROJECT")
    or os.getenv("GCLOUD_PROJECT")
    or "nps-master-key"
)


def _init_firestore():
    options = {"projectId": PROJECT_ID} if PROJECT_ID else None

    if os.path.exists(CRED_PATH):
        if not firebase_admin._apps:
            cred = credentials.Certificate(CRED_PATH)
            firebase_admin.initialize_app(cred, options=options)
        return firestore.client()

    if not firebase_admin._apps:
        firebase_admin.initialize_app(options=options)
    return firestore.client()


db = _init_firestore()


def init_db():
    if db is None:
        raise RuntimeError(
            f"Failed to initialize Firestore client for project '{PROJECT_ID}'."
        )
    users_ref = db.collection("users")
    if not list(users_ref.limit(1).stream()):
        users_ref.document("admin").set({
            "id": "admin",
            "username": "admin",
            "full_name": "NP Solutions Admin",
            "role": "admin",
            "password_hash": hash_password("npsadmin"),
            "is_active": 1,
            "created_at": datetime.utcnow().isoformat(),
        })
    settings_ref = db.collection("app_settings").document("branding")
    if not settings_ref.get().exists:
        settings_ref.set({"company_name": "NP Solutions", "logo_data_url": ""})


def get_settings() -> Dict[str, str]:
    doc = db.collection("app_settings").document("branding").get()
    return doc.to_dict() if doc.exists else {"company_name": "NP Solutions", "logo_data_url": ""}


def update_setting(key: str, value: str):
    db.collection("app_settings").document("branding").set({key: value}, merge=True)


def get_user_by_username(username: str) -> Optional[Dict]:
    doc = db.collection("users").document(username.strip().lower()).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    return data if data.get("is_active", 1) == 1 else None


def create_session(token: str, user_id: str):
    db.collection("sessions").document(token).set({
        "token": token,
        "user_id": str(user_id),
        "created_at": datetime.utcnow().isoformat(),
    })


def get_user_by_token(token: str) -> Optional[Dict]:
    if not token:
        return None
    s_doc = db.collection("sessions").document(token).get()
    if not s_doc.exists:
        return None
    user_id = s_doc.to_dict().get("user_id")
    u_doc = db.collection("users").document(str(user_id)).get()
    if not u_doc.exists:
        return None
    u = u_doc.to_dict()
    if u.get("is_active", 1) != 1:
        return None
    return {
        "id": u["id"],
        "username": u["username"],
        "full_name": u["full_name"],
        "role": u["role"],
        "is_active": u["is_active"],
    }


def delete_session(token: str):
    db.collection("sessions").document(token).delete()


def list_users() -> List[Dict]:
    results = []
    for d in db.collection("users").stream():
        u = d.to_dict()
        u.pop("password_hash", None)
        results.append(u)
    return results


def create_user(username: str, full_name: str, role: str, password: str) -> str:
    uname = username.strip().lower()
    doc_ref = db.collection("users").document(uname)
    if doc_ref.get().exists:
        raise ValueError("Username already exists.")
    doc_ref.set({
        "id": uname,
        "username": uname,
        "full_name": full_name.strip(),
        "role": role,
        "password_hash": hash_password(password),
        "is_active": 1,
        "created_at": datetime.utcnow().isoformat(),
    })
    return uname


def update_user_role_or_status(user_id: str, role: str, is_active: int):
    db.collection("users").document(str(user_id)).update({"role": role, "is_active": is_active})


def create_client(data: Dict) -> str:
    doc_ref = db.collection("clients").document()
    doc_ref.set({
        "id": doc_ref.id,
        "company_name": data["company_name"],
        "contact_name": data.get("contact_name", ""),
        "phone": data.get("phone", ""),
        "email": data.get("email", ""),
        "address": data.get("address", ""),
        "notes": data.get("notes", ""),
        "created_at": datetime.utcnow().isoformat(),
    })
    return doc_ref.id


def list_clients() -> List[Dict]:
    return [d.to_dict() for d in db.collection("clients").order_by("company_name").stream()]


def save_key_system(
    client_id: str,
    system_name: str,
    keyway_code: str,
    profile: Dict,
    keys: List[Dict],
    doors: List[Dict],
    created_by: str,
) -> str:
    doc_ref = db.collection("key_systems").document()
    doc_ref.set({
        "id": doc_ref.id,
        "client_id": str(client_id),
        "system_name": system_name,
        "keyway_code": keyway_code,
        "profile": profile,
        "keys": keys,
        "doors": doors,
        "created_by": created_by,
        "created_at": datetime.utcnow().isoformat(),
    })
    return doc_ref.id


def list_client_systems(client_id: str) -> List[Dict]:
    docs = db.collection("key_systems").where("client_id", "==", str(client_id)).stream()
    systems = [
        {
            "id": d.to_dict()["id"],
            "client_id": d.to_dict()["client_id"],
            "system_name": d.to_dict()["system_name"],
            "keyway_code": d.to_dict()["keyway_code"],
            "created_by": d.to_dict().get("created_by", "-"),
            "created_at": d.to_dict().get("created_at", ""),
        }
        for d in docs
    ]
    return sorted(systems, key=lambda x: x["created_at"], reverse=True)


def get_key_system(system_id: str) -> Optional[Dict]:
    doc = db.collection("key_systems").document(str(system_id)).get()
    return doc.to_dict() if doc.exists else None


def delete_key_system(system_id: str, client_id: Optional[str] = None) -> str:
    doc_ref = db.collection("key_systems").document(str(system_id))
    doc = doc_ref.get()
    if not doc.exists:
        return "not_found"
    if client_id is not None:
        data = doc.to_dict() or {}
        if str(data.get("client_id", "")) != str(client_id):
            return "not_found"
    doc_ref.delete()
    return "deleted"
```[cite: 8]
