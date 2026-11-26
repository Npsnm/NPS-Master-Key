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
