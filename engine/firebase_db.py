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

### 2. `app.py`

```python
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
    create_client, list_clients, save_key_system, list_client_systems, get_key_system,
    delete_key_system
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


@app.delete("/api/clients/{client_id}/systems/{system_id}")
def api_delete_client_system(
    client_id: str,
    system_id: str,
    user: Dict = Depends(require_perm("generate_systems"))
):
    status = delete_key_system(system_id, client_id=client_id)
    if status == "not_found":
        raise HTTPException(status_code=404, detail="System not found for this client.")
    return {"status": "deleted", "id": system_id}


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
```[cite: 7]

### 3. `static/index.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>NP Solutions — NPS Master Key</title>
  <style>
    :root { --bg: #0f172a; --card: #ffffff; --border: #cbd5e1; --primary: #2563eb; --primary-hover: #1d4ed8; --accent: #0ea5e9; --text: #0f172a; }
    * { box-sizing: border-box; }
    body { font-family: 'Segoe UI', system-ui, sans-serif; margin: 0; background: #f1f5f9; color: var(--text); }
    .topbar { background: var(--bg); color: white; padding: 0.85rem 2rem; display: flex; justify-content: space-between; align-items: center; border-bottom: 3px solid var(--accent); }
    .brand-cluster { display: flex; align-items: center; gap: 1rem; }
    .logo-slot { width: 52px; height: 52px; border-radius: 10px; background: linear-gradient(135deg, #2563eb, #0ea5e9); display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 1.2rem; color: white; overflow: hidden; border: 2px solid rgba(255,255,255,0.2); flex-shrink: 0; }
    .logo-slot img { width: 100%; height: 100%; object-fit: contain; background: white; }
    .brand-title h1 { margin: 0; font-size: 1.35rem; }
    .brand-title span { font-size: 0.8rem; color: #94a3b8; }
    .user-bar { display: flex; align-items: center; gap: 0.65rem; font-size: 0.85rem; }
    .pill { background: #334155; padding: 0.3rem 0.7rem; border-radius: 999px; font-weight: 600; color: #e2e8f0; }
    .pill.role { background: #0284c7; color: white; text-transform: uppercase; font-size: 0.75rem; }
    .login-wrap { max-width: 420px; margin: 4.5rem auto; background: white; padding: 2rem; border-radius: 12px; box-shadow: 0 10px 25px rgba(15,23,42,0.12); border-top: 5px solid var(--primary); }
    .login-header { display: flex; align-items: center; gap: 1rem; margin-bottom: 1.5rem; }
    .container { max-width: 1200px; margin: 1.5rem auto; padding: 0 1rem; }
    .nav-tabs { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1.25rem; }
    .tab-btn { background: white; color: #334155; border: 1px solid var(--border); padding: 0.65rem 1.1rem; border-radius: 8px; font-weight: 600; cursor: pointer; }
    .tab-btn.active { background: var(--primary); color: white; border-color: var(--primary); }
    .card { background: white; padding: 1.5rem; border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 1.25rem; border: 1px solid #e2e8f0; }
    .card h2 { margin-top: 0; font-size: 1.15rem; border-bottom: 1px solid #f1f5f9; padding-bottom: 0.5rem; }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
    .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1rem; }
    label { display: block; font-weight: 600; font-size: 0.85rem; margin-top: 0.65rem; color: #334155; }
    input, select, textarea { width: 100%; padding: 0.55rem; margin-top: 0.25rem; border: 1px solid var(--border); border-radius: 6px; font-size: 0.92rem; }
    button.primary { background: var(--primary); color: white; border: none; padding: 0.7rem 1.35rem; border-radius: 6px; font-weight: 600; cursor: pointer; margin-top: 1rem; }
    button.primary:hover { background: var(--primary-hover); }
    button.secondary { background: #475569; color: white; border: none; padding: 0.45rem 0.9rem; border-radius: 6px; font-size: 0.85rem; cursor: pointer; }
    button.danger { background: #dc2626; color: white; border: none; padding: 0.4rem 0.8rem; border-radius: 6px; font-size: 0.82rem; cursor: pointer; }
    table { width: 100%; border-collapse: collapse; margin-top: 0.75rem; font-size: 0.88rem; }
    th, td { border: 1px solid #e2e8f0; padding: 0.55rem; text-align: left; }
    th { background: #f8fafc; font-weight: 700; }
    .axis-box { border: 1px solid #cbd5e1; padding: 0.85rem; border-radius: 8px; margin-top: 0.75rem; background: #f8fafc; }
    .alert-warn { background: #fef2f2; border: 1px solid #fecaca; color: #991b1b; padding: 0.75rem; border-radius: 6px; margin-top: 0.75rem; }
    .alert-ok { background: #f0fdf4; border: 1px solid #bbf7d0; color: #166534; padding: 0.75rem; border-radius: 6px; margin-top: 0.75rem; }
    @media print {
      .topbar .user-bar, .nav-tabs, .no-print { display: none !important; }
      body { background: white; }
      .card { box-shadow: none; border: 1px solid #94a3b8; }
    }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="brand-cluster">
      <div class="logo-slot" id="headerLogoSlot">NPS</div>
      <div class="brand-title">
        <h1 id="headerCompanyName">NP Solutions</h1>
        <span>NPS Master Key • <span id="storageModeBadge">Initializing...</span></span>
      </div>
    </div>
    <div class="user-bar" id="userBar" style="display:none;">
      <span class="pill">Client: <strong id="activeClientBadge">None</strong></span>
      <span class="pill" id="userNameBadge">User</span>
      <span class="pill role" id="userRoleBadge">Role</span>
      <button class="secondary" onclick="logout()">Sign Out</button>
    </div>
  </header>

  <div id="loginView" class="login-wrap">
    <div class="login-header">
      <div class="logo-slot" id="loginLogoSlot">NPS</div>
      <div>
        <h2 style="margin:0;">NP Solutions Sign In</h2>
        <small style="color:#64748b;">Authorized Locksmith & Security Access</small>
      </div>
    </div>
    <label>Username</label>
    <input id="loginUser" value="admin" />
    <label>Password</label>
    <input id="loginPass" type="password" value="npsadmin" />
    <button class="primary" style="width:100%;" onclick="login()">Sign In to NPS Master Key</button>
    <p id="loginError" style="color:#dc2626; font-size:0.85rem; margin-top:0.75rem;"></p>
    <small style="color:#64748b; display:block; margin-top:0.75rem;">Default Admin Login: <code>admin</code> / <code>npsadmin</code></small>
  </div>

  <div id="appWorkspace" class="container" style="display:none;">
    <div class="nav-tabs">
      <button class="tab-btn active" onclick="switchTab('designer', this)">1. System & Tree Designer</button>
      <button class="tab-btn" onclick="switchTab('clients', this)">2. Client Records</button>
      <button class="tab-btn" onclick="switchTab('reverse', this)">3. Paper-System Reverse Solver</button>
      <button class="tab-btn" onclick="switchTab('bench', this)">4. Bench Pinning & Depth Reference</button>
      <button class="tab-btn" id="adminTabBtn" onclick="switchTab('admin', this)">5. Users & NP Solutions Logo</button>
    </div>

    <div id="tab-designer">
      <div class="card no-print">
        <h2>Hardware Profile & Keyway Presets</h2>
        <div class="grid-2">
          <div>
            <label>Manufacturer / Keyway Preset</label>
            <select id="presetSelect" onchange="applyPreset()"></select>
          </div>
          <div>
            <label>System / Facility Name</label>
            <input id="systemName" value="Main Facility Master System" />
          </div>
        </div>
        <div id="axesContainer"></div>
        <button class="secondary" style="margin-top:0.75rem;" onclick="addCustomAxis()">+ Add Custom Axis (Dimple / Side-Pin)</button>
      </div>

      <div class="card no-print">
        <h2>Master & Sub-Master Hierarchy Counts</h2>
        <div class="grid-3">
          <div><label>Master Cylinders (A, B, C...)</label><input id="masterCount" type="number" value="2" min="0" max="26" /></div>
          <div><label>Sub-Masters per Master (AA, AB...)</label><input id="submasterCount" type="number" value="2" min="0" max="26" /></div>
          <div><label>Change Keys per Sub-Master</label><input id="changeCount" type="number" value="3" min="1" max="100" /></div>
        </div>
        <button class="primary" onclick="generateSystem()">Generate Keys, Pinning & Security Audit</button>
      </div>

      <div id="results" class="card" style="display:none;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <h2 style="border:none; margin:0;">Key Cutting Schedule (<span id="keyTotal">0</span> Keys)</h2>
          <div class="no-print" style="display:flex; gap:0.5rem;">
            <button class="secondary" onclick="exportCSV()">Export CSV</button>
            <button class="secondary" onclick="window.print()">Print Work Order / Charts</button>
          </div>
        </div>
        <table id="keysTable"><thead><tr><th>Key ID</th><th>Level</th><th>Reports To</th><th>Bitting (By Axis)</th></tr></thead><tbody></tbody></table>

        <h2 style="margin-top:1.5rem;">Cylinder Pinning & Phantom Security Audit</h2>
        <table id="doorsTable"><thead><tr><th>Door</th><th>Operating Keys</th><th>Phantom Keys</th><th>Interchange Conflicts</th><th>Pinning Chart</th></tr></thead><tbody></tbody></table>
      </div>
    </div>

    <div id="tab-clients" style="display:none;">
      <div class="grid-2">
        <div class="card">
          <h2>Add Client / Facility Record</h2>
          <label>Company / Facility Name *</label><input id="cCompany" placeholder="e.g., Desert Valley Medical Center" />
          <label>Contact Person</label><input id="cContact" />
          <div class="grid-2">
            <div><label>Phone</label><input id="cPhone" /></div>
            <div><label>Email</label><input id="cEmail" /></div>
          </div>
          <label>Site Address</label><input id="cAddress" />
          <label>Keyway Restrictions & Security Notes</label><textarea id="cNotes" rows="2"></textarea>
          <button class="primary" onclick="saveClient()">Save Client</button>
        </div>
        <div class="card">
          <h2>Client Directory</h2>
          <table id="clientsTable"><thead><tr><th>Company</th><th>Contact</th><th>Select</th></tr></thead><tbody></tbody></table>
          <h3 style="margin-top:1.5rem;">Saved Systems for Selected Client</h3>
          <table id="savedSystemsTable"><thead><tr><th>System Name</th><th>Keyway</th><th>Created By</th><th>Action</th></tr></thead><tbody></tbody></table>
        </div>
      </div>
    </div>

    <div id="tab-reverse" style="display:none;">
      <div class="card">
        <h2>Paper-System Reverse Pinning Decoder</h2>
        <p style="color:#475569; font-size:0.9rem;">Enter physical bottom pins and master wafers from an existing cylinder to decode every working key bitting.</p>
        <div id="reverseChambers"></div>
        <button class="primary" onclick="runReverseSolver()">Decode All Working Key Bittings</button>
        <div id="reverseResults" style="margin-top:1rem;"></div>
      </div>
    </div>

    <div id="tab-bench" style="display:none;">
      <div class="grid-2">
        <div class="card">
          <h2>Single-Cylinder Bench Pinning & MACS Calculator</h2>
          <label>Cylinder Type</label>
          <select id="benchSfic"><option value="false">Standard Inline Cylinder</option><option value="true">SFIC A2 Core (Stack 23)</option></select>
          <label>MACS Limit</label><input id="benchMacs" type="number" value="7" />
          <label>Operating Key Bittings (one per line, comma-separated)</label>
          <textarea id="benchKeys" rows="4">3,1,5,2,6,4
5,3,5,4,6,2</textarea>
          <label>Control Key Bitting (SFIC only, comma-separated)</label><input id="benchCtrl" value="8,7,9,8,7,6" />
          <button class="primary" onclick="runBenchCalc()">Calculate Stack & Check MACS</button>
          <div id="benchResults" style="margin-top:1rem;"></div>
        </div>
        <div class="card">
          <h2>Locksmith Depth & Specification Quick Reference</h2>
          <table>
            <thead><tr><th>Manufacturer / Keyway</th><th>Increment</th><th>Depths</th><th>MACS</th><th>SFIC Stack</th></tr></thead>
            <tbody>
              <tr><td><strong>Schlage (C / E / Everest)</strong></td><td>.015"</td><td>0 (0.335") – 9 (0.200")</td><td>7</td><td>N/A</td></tr>
              <tr><td><strong>Kwikset (KW1 / KW10)</strong></td><td>.023"</td><td>1 (0.329") – 6 (0.214")</td><td>4</td><td>N/A</td></tr>
              <tr><td><strong>Best / Falcon SFIC (A2)</strong></td><td>.0125"</td><td>0 (0.318") – 9 (0.2055")</td><td>9</td><td>23</td></tr>
              <tr><td><strong>Best / Falcon SFIC (A4)</strong></td><td>.021"</td><td>0 (0.318") – 5 (0.213")</td><td>5</td><td>14</td></tr>
              <tr><td><strong>Yale 8 / Para</strong></td><td>.019"</td><td>0 (0.334") – 9 (0.163")</td><td>8</td><td>N/A</td></tr>
              <tr><td><strong>Sargent (LA–LC)</strong></td><td>.020"</td><td>1 (0.328") – 10 (0.148")</td><td>7</td><td>N/A</td></tr>
              <tr><td><strong>Corbin Russwin (Z-Class)</strong></td><td>.028"</td><td>1 (0.342") – 6 (0.202")</td><td>5</td><td>N/A</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <div id="tab-admin" style="display:none;">
      <div class="grid-2">
        <div class="card">
          <h2>NP Solutions Logo & Branding</h2>
          <label>Company / Shop Name</label><input id="brandNameInput" value="NP Solutions" />
          <label>Upload NP Solutions Logo (PNG, SVG, JPG)</label><input type="file" id="logoFileInput" accept="image/*" onchange="previewLogo(event)" />
          <button class="primary" onclick="saveBranding()">Save Logo & Company Name</button>
        </div>
        <div class="card">
          <h2>Create Staff User & Access Level</h2>
          <div class="grid-2">
            <div><label>Username</label><input id="newUsername" placeholder="e.g., jsmith" /></div>
            <div><label>Full Name</label><input id="newFullName" placeholder="John Smith" /></div>
          </div>
          <div class="grid-2">
            <div>
              <label>Access Level (Role)</label>
              <select id="newUserRole">
                <option value="admin">Admin (Full Control + User Management)</option>
                <option value="locksmith">Master Locksmith (Design Systems + Full Bittings)</option>
                <option value="tech">Bench Tech (Pinning Charts Only; Top Masters Masked)</option>
                <option value="viewer">Auditor / Read-Only</option>
              </select>
            </div>
            <div><label>Initial Password</label><input id="newUserPass" type="password" /></div>
          </div>
          <button class="primary" onclick="createStaffUser()">Create User Account</button>
        </div>
      </div>
      <div class="card">
        <h2>Authorized Staff & Access Levels</h2>
        <table id="usersTable"><thead><tr><th>Username</th><th>Full Name</th><th>Access Level</th><th>Status</th><th>Action</th></tr></thead><tbody></tbody></table>
      </div>
    </div>
  </div>

  <script>
    let TOKEN = localStorage.getItem("nps_token") || "";
    let CURRENT_USER = null;
    let PRESETS = {};
    let CURRENT_AXES = [];
    let IS_SFIC = false;
    let SFIC_HEIGHT = 23;
    let SELECTED_CLIENT_ID = null;
    let SELECTED_CLIENT_NAME = "None";
    let LAST_GENERATED = null;
    let UPLOADED_LOGO_DATA = "";

    function authHeaders() { return { "Content-Type": "application/json", "Authorization": `Bearer ${TOKEN}` }; }

    async function loadBranding() {
      const res = await fetch("/api/branding");
      const b = await res.json();
      const name = b.company_name || "NP Solutions";
      document.getElementById("headerCompanyName").innerText = name;
      document.getElementById("brandNameInput").value = name;
      document.getElementById("storageModeBadge").innerText = b.storage_mode || "";
      UPLOADED_LOGO_DATA = b.logo_data_url || "";
      renderLogoSlots(UPLOADED_LOGO_DATA);
    }

    function renderLogoSlots(dataUrl) {
      [document.getElementById("headerLogoSlot"), document.getElementById("loginLogoSlot")].forEach(el => {
        if (el) el.innerHTML = dataUrl ? `<img src="${dataUrl}" alt="NP Solutions Logo" />` : "NPS";
      });
    }

    function previewLogo(evt) {
      const file = evt.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = e => { UPLOADED_LOGO_DATA = e.target.result; renderLogoSlots(UPLOADED_LOGO_DATA); };
      reader.readAsDataURL(file);
    }

    async function saveBranding() {
      const res = await fetch("/api/branding", {
        method: "POST", headers: authHeaders(),
        body: JSON.stringify({ company_name: document.getElementById("brandNameInput").value, logo_data_url: UPLOADED_LOGO_DATA })
      });
      if (res.ok) { loadBranding(); alert("NP Solutions branding & logo saved!"); }
    }

    async function login() {
      const res = await fetch("/api/login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: document.getElementById("loginUser").value, password: document.getElementById("loginPass").value })
      });
      const data = await res.json();
      if (!res.ok) { document.getElementById("loginError").innerText = data.detail || "Login failed"; return; }
      TOKEN = data.token;
      localStorage.setItem("nps_token", TOKEN);
      await bootWorkspace();
    }

    async function logout() {
      await fetch("/api/logout", { method: "POST", headers: authHeaders() });
      TOKEN = ""; localStorage.removeItem("nps_token");
      document.getElementById("appWorkspace").style.display = "none";
      document.getElementById("userBar").style.display = "none";
      document.getElementById("loginView").style.display = "block";
    }

    async function bootWorkspace() {
      if (!TOKEN) return;
      const meRes = await fetch("/api/me", { headers: authHeaders() });
      if (!meRes.ok) { logout(); return; }
      CURRENT_USER = await meRes.json();

      document.getElementById("loginView").style.display = "none";
      document.getElementById("appWorkspace").style.display = "block";
      document.getElementById("userBar").style.display = "flex";
      document.getElementById("userNameBadge").innerText = CURRENT_USER.full_name;
      document.getElementById("userRoleBadge").innerText = CURRENT_USER.role;
