import os
import itertools
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict, Optional

from engine.models import AxisConfig, LockProfile, DoorCylinder
from engine.presets import KEYWAY_PRESETS
from engine.generator import generate_hierarchical_system, is_macs_valid
from engine.solver import calculate_chamber_stack, get_valid_shear_heights, find_phantom_and_interchange_keys
from engine.auth import verify_password, generate_session_token, has_permission

os.environ["GOOGLE_CLOUD_PROJECT"] = (
    os.getenv("GOOGLE_CLOUD_PROJECT")
    or os.getenv("GCLOUD_PROJECT")
    or "nps-master-key"
)

from engine.firebase_db import (
    init_db, get_settings, update_setting, get_user_by_username, create_session,
    get_user_by_token, delete_session, list_users, create_user, update_user_role_or_status,
    create_client, list_clients, save_key_system, list_client_systems, get_key_system
)

STORAGE_MODE = "Firebase Cloud (Firestore)"

init_db()
app = FastAPI(title="NP Solutions — NPS Master Key")
app.mount("/static", StaticFiles(directory="static"), name="static")

def get_current_user(authorization: Optional[str] = Header(None)) -> Dict:
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
    user = get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated. Please sign in.")
    return user

def require_perm(perm: str):
    def checker(user: Dict = Depends(get_current_user)):
        if not has_permission(user["role"], perm):
            raise HTTPException(status_code=403, detail=f"Access denied: '{user['role']}' role lacks '{perm}' permission.")
        return user
    return checker

class LoginInput(BaseModel):
    username: str
    password: str

class NewUserInput(BaseModel):
    username: str
    full_name: str
    role: str
    password: str

class UserUpdateInput(BaseModel):
    role: str
    is_active: int

class BrandingInput(BaseModel):
    company_name: str
    logo_data_url: str

class ClientInput(BaseModel):
    company_name: str
    contact_name: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    notes: str = ""

class AxisInput(BaseModel):
    name: str
    pin_count: int
    min_depth: int
    max_depth: int
    macs: int
    step_size: int

class SystemRequest(BaseModel):
    client_id: Optional[str] = None
    system_name: str = "Main Facility System"
    keyway_code: str = "Custom"
    profile_name: str
    is_sfic: bool
    sfic_stack_height: int = 23
    axes: List[AxisInput]
    top_master_bitting: Dict[str, List[int]]
    control_bitting: Optional[Dict[str, List[int]]] = None
    master_count: int = 2
    submasters_per_master: int = 2
    changes_per_submaster: int = 3

class ReversePinInput(BaseModel):
    chambers: List[Dict]

class BenchCalcInput(BaseModel):
    is_sfic: bool
    sfic_stack_height: int = 23
    max_depth: int = 9
    macs: int = 7
    operating_bittings: List[List[int]]
    control_bitting: Optional[List[int]] = None

@app.get("/")
def serve_ui():
    return FileResponse("static/index.html")

@app.get("/api/branding")
def api_get_branding():
    settings = get_settings()
    settings["storage_mode"] = STORAGE_MODE
    return settings

@app.post("/api/branding")
def api_update_branding(data: BrandingInput, user: Dict = Depends(require_perm("manage_branding"))):
    update_setting("company_name", data.company_name)
    update_setting("logo_data_url", data.logo_data_url)
    return {"status": "updated"}

@app.post("/api/login")
def api_login(creds: LoginInput):
    user = get_user_by_username(creds.username)
    if not user or not verify_password(creds.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    token = generate_session_token()
    create_session(token, str(user["id"]))
    return {
        "token": token,
        "user": {"id": str(user["id"]), "username": user["username"], "full_name": user["full_name"], "role": user["role"]}
    }

@app.post("/api/logout")
def api_logout(authorization: Optional[str] = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        delete_session(authorization.split(" ", 1)[1].strip())
    return {"status": "logged_out"}

@app.get("/api/me")
def api_me(user: Dict = Depends(get_current_user)):
    return user

@app.get("/api/users")
def api_list_users(user: Dict = Depends(require_perm("manage_users"))):
    return list_users()

@app.post("/api/users")
def api_create_user(new_u: NewUserInput, user: Dict = Depends(require_perm("manage_users"))):
    if new_u.role not in ("admin", "locksmith", "tech", "viewer"):
        raise HTTPException(status_code=400, detail="Invalid role.")
    try:
        uid = create_user(new_u.username, new_u.full_name, new_u.role, new_u.password)
        return {"id": str(uid)}
    except Exception:
        raise HTTPException(status_code=400, detail="Username already exists or invalid data.")

@app.patch("/api/users/{user_id}")
def api_patch_user(user_id: str, upd: UserUpdateInput, user: Dict = Depends(require_perm("manage_users"))):
    update_user_role_or_status(user_id, upd.role, upd.is_active)
    return {"status": "updated"}

@app.get("/api/presets")
def get_presets(user: Dict = Depends(get_current_user)):
    return {
        code: {
            "name": p.name,
            "is_sfic": p.is_sfic,
            "sfic_stack_height": p.sfic_stack_height,
            "axes": [a.__dict__ for a in p.axes]
        }
        for code, p in KEYWAY_PRESETS.items()
    }

@app.get("/api/clients")
def api_list_clients(user: Dict = Depends(get_current_user)):
    return list_clients()

@app.post("/api/clients")
def api_create_client(client: ClientInput, user: Dict = Depends(require_perm("manage_clients"))):
    cid = create_client(client.dict())
    return {"id": str(cid)}

@app.get("/api/clients/{client_id}/systems")
def api_client_systems(client_id: str, user: Dict = Depends(get_current_user)):
    return list_client_systems(client_id)

def _mask_sensitive_keys(keys: List[Dict], role: str) -> List[Dict]:
    if has_permission(role, "view_top_masters"):
        return keys
    masked = []
    for k in keys:
        copy_k = dict(k)
        if copy_k["level"] in ("Grand Master", "Master", "Control"):
            copy_k["bitting"] = {ax: ["*"] * len(cuts) for ax, cuts in copy_k["bitting"].items()}
        masked.append(copy_k)
    return masked

@app.get("/api/systems/{system_id}")
def api_get_system(system_id: str, user: Dict = Depends(get_current_user)):
    sys_data = get_key_system(system_id)
    if not sys_data:
        raise HTTPException(status_code=404, detail="System not found")
    sys_data["keys"] = _mask_sensitive_keys(sys_data["keys"], user["role"])
    return sys_data

@app.post("/api/generate")
def api_generate(req: SystemRequest, user: Dict = Depends(require_perm("generate_systems"))):
    try:
        axes = [AxisConfig(**a.dict()) for a in req.axes]
        profile = LockProfile(
            name=req.profile_name,
            is_sfic=req.is_sfic,
            sfic_stack_height=req.sfic_stack_height,
            axes=axes
        )
        keys = generate_hierarchical_system(
            profile=profile,
            top_master_bitting=req.top_master_bitting,
            control_bitting=req.control_bitting,
            master_count=req.master_count,
            submasters_per_master=req.submasters_per_master,
            changes_per_submaster=req.changes_per_submaster
        )

        key_map = {k.key_id: k for k in keys}
        doors = []
        audits = []

        change_keys = [k for k in keys if k.level == "Change"]
        for idx, ck in enumerate(change_keys, start=1):
            chain = []
            curr = ck
            while curr:
                chain.append(curr.key_id)
                curr = key_map.get(curr.parent_id) if curr.parent_id else None
            chain.reverse()

            door = DoorCylinder(
                door_id=f"D{idx:03d}",
                door_name=f"Door {idx:03d} ({ck.key_id})",
                assigned_key_ids=chain
            )
            for a_idx, axis in enumerate(profile.axes):
                stacks = []
                for c in range(axis.pin_count):
                    op_cuts = [key_map[kid].bitting[axis.name][c] for kid in chain]
                    ctrl_cut = key_map["CTRL"].bitting[axis.name][c] if profile.is_sfic else None
                    stacks.append(calculate_chamber_stack(op_cuts, ctrl_cut, profile, a_idx))
                door.pin_stacks[axis.name] = stacks

            doors.append(door)
            audits.append(find_phantom_and_interchange_keys(door, keys, profile))

        keys_serialized = [k.__dict__ for k in keys]
        doors_serialized = [d.__dict__ for d in doors]

        saved_id = None
        if req.client_id:
            saved_id = save_key_system(
                client_id=str(req.client_id),
                system_name=req.system_name,
                keyway_code=req.keyway_code,
                profile={"name": profile.name, "is_sfic": profile.is_sfic, "axes": [a.__dict__ for a in profile.axes]},
                keys=keys_serialized,
                doors=doors_serialized,
                created_by=user["username"]
            )

        return {
            "saved_system_id": str(saved_id) if saved_id else None,
            "keys": _mask_sensitive_keys(keys_serialized, user["role"]),
            "doors": doors_serialized,
            "audits": audits
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/tools/reverse-pin")
def api_reverse_pin(req: ReversePinInput, user: Dict = Depends(get_current_user)):
    chamber_heights = [get_valid_shear_heights(ch) for ch in req.chambers]
    combos = list(itertools.product(*chamber_heights))
    return {
        "total_working_keys": len(combos),
        "bittings": [list(c) for c in combos[:250]],
        "truncated": len(combos) > 250
    }

@app.post("/api/tools/bench-calc")
def api_bench_calc(req: BenchCalcInput, user: Dict = Depends(get_current_user)):
    try:
        pin_count = len(req.operating_bittings[0])
        dummy_profile = LockProfile(
            name="Bench",
            is_sfic=req.is_sfic,
            sfic_stack_height=req.sfic_stack_height,
            axes=[AxisConfig(name="Primary", pin_count=pin_count, min_depth=0, max_depth=req.max_depth, macs=req.macs, step_size=1)]
        )
        stacks = []
        for c in range(pin_count):
            op_cuts = [b[c] for b in req.operating_bittings]
            ctrl_cut = req.control_bitting[c] if (req.is_sfic and req.control_bitting) else None
            stacks.append(calculate_chamber_stack(op_cuts, ctrl_cut, dummy_profile, 0))

        macs_warnings = [
            f"Key #{i+1} ({'-'.join(map(str, b))}) violates MACS {req.macs}"
            for i, b in enumerate(req.operating_bittings)
            if not is_macs_valid(b, req.macs)
        ]
        return {"stacks": stacks, "macs_warnings": macs_warnings}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
```[cite: 2]

---

### 2. Full `engine/firebase_db.py` (Copy & Paste)

```python
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
