import itertools
import string
from typing import List, Dict
from .models import LockProfile, KeyRecord

def is_macs_valid(bitting: List[int], macs: int) -> bool:
    for i in range(len(bitting) - 1):
        if abs(bitting[i] - bitting[i + 1]) > macs:
            return False
    return True

def generate_kba_candidates(top_master_bitting: List[int], axis_cfg) -> List[List[int]]:
    chamber_options = []
    for tm_cut in top_master_bitting:
        cuts = [
            d for d in range(axis_cfg.min_depth, axis_cfg.max_depth + 1)
            if d != tm_cut and (d - tm_cut) % axis_cfg.step_size == 0
        ]
        chamber_options.append(cuts)

    valid_bittings = []
    for combo in itertools.product(*chamber_options):
        bitting = list(combo)
        if is_macs_valid(bitting, axis_cfg.macs):
            valid_bittings.append(bitting)

    return valid_bittings

def _index_to_letters(idx: int) -> str:
    letters = string.ascii_uppercase
    res = ""
    while idx >= 0:
        res = letters[idx % 26] + res
        idx = idx // 26 - 1
    return res

def generate_hierarchical_system(
    profile: LockProfile,
    top_master_bitting: Dict[str, List[int]],
    control_bitting: Dict[str, List[int]] | None,
    master_count: int,
    submasters_per_master: int,
    changes_per_submaster: int
) -> List[KeyRecord]:
    keys: List[KeyRecord] = [
        KeyRecord(key_id="GM", level="Grand Master", parent_id=None, bitting=top_master_bitting)
    ]

    if profile.is_sfic and control_bitting:
        keys.append(
            KeyRecord(key_id="CTRL", level="Control", parent_id=None, bitting=control_bitting)
        )

    if master_count == 0:
        total_needed = max(1, changes_per_submaster)
    else:
        effective_subs = max(1, submasters_per_master)
        total_needed = master_count + (master_count * submasters_per_master) + (master_count * effective_subs * changes_per_submaster)

    axis_pools = {}
    for axis in profile.axes:
        pool = generate_kba_candidates(top_master_bitting[axis.name], axis)
        if len(pool) < total_needed:
            raise ValueError(
                f"Axis '{axis.name}' only supports {len(pool)} MACS-valid combinations, "
                f"but your tree requires {total_needed} keys. Reduce key counts or widen depth/MACS."
            )
        axis_pools[axis.name] = iter(pool)

    def next_bitting() -> Dict[str, List[int]]:
        return {axis.name: next(axis_pools[axis.name]) for axis in profile.axes}

    if master_count == 0:
        for c in range(changes_per_submaster):
            keys.append(KeyRecord(key_id=f"AA{c + 1}", level="Change", parent_id="GM", bitting=next_bitting()))
        return keys

    for m_idx in range(master_count):
        m_code = _index_to_letters(m_idx)
        keys.append(KeyRecord(key_id=m_code, level="Master", parent_id="GM", bitting=next_bitting()))

        if submasters_per_master == 0:
            for c_idx in range(changes_per_submaster):
                keys.append(KeyRecord(
                    key_id=f"{m_code}{c_idx + 1}",
                    level="Change",
                    parent_id=m_code,
                    bitting=next_bitting()
                ))
        else:
            for s_idx in range(submasters_per_master):
                s_code = f"{m_code}{_index_to_letters(s_idx)}"
                keys.append(KeyRecord(key_id=s_code, level="Sub-Master", parent_id=m_code, bitting=next_bitting()))

                for c_idx in range(changes_per_submaster):
                    keys.append(KeyRecord(
                        key_id=f"{s_code}{c_idx + 1}",
                        level="Change",
                        parent_id=s_code,
                        bitting=next_bitting()
                    ))

    return keys
