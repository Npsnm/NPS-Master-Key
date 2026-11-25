import itertools
from typing import List, Dict
from .models import LockProfile, KeyRecord, DoorCylinder

def calculate_chamber_stack(
    operating_cuts: List[int],
    control_cut: int | None,
    profile: LockProfile,
    axis_index: int = 0
) -> Dict:
    axis = profile.axes[axis_index]
    unique_cuts = sorted(set(operating_cuts))

    bottom_pin = unique_cuts[0]
    master_pins = [unique_cuts[i] - unique_cuts[i - 1] for i in range(1, len(unique_cuts))]

    stack = {
        "bottom": bottom_pin,
        "masters": master_pins,
        "valid_operating_heights": unique_cuts
    }

    if profile.is_sfic:
        if control_cut is None:
            raise ValueError("SFIC systems require a Control key cut.")
        highest_op = unique_cuts[-1]
        if control_cut < highest_op:
            all_shears = sorted(set(operating_cuts + [control_cut]))
            bottom_pin = all_shears[0]
            wafers = [all_shears[i] - all_shears[i - 1] for i in range(1, len(all_shears))]
            stack["bottom"] = bottom_pin
            stack["masters"] = wafers
            stack["control_buildup"] = 0
            driver_pin = profile.sfic_stack_height - all_shears[-1]
        else:
            buildup = control_cut - highest_op
            stack["control_buildup"] = buildup
            driver_pin = profile.sfic_stack_height - control_cut

        if driver_pin < 0:
            raise ValueError(f"SFIC stack exceeds max stack height ({profile.sfic_stack_height}).")
        stack["driver"] = driver_pin
    else:
        highest_op = unique_cuts[-1]
        stack["driver"] = (axis.max_depth + 4) - highest_op

    return stack

def get_valid_shear_heights(chamber_stack: Dict) -> List[int]:
    bottom = chamber_stack["bottom"]
    masters = chamber_stack["masters"]
    valid_heights = {bottom}

    for r in range(1, len(masters) + 1):
        for combo in itertools.combinations(masters, r):
            valid_heights.add(bottom + sum(combo))

    return sorted(valid_heights)

def find_phantom_and_interchange_keys(
    door: DoorCylinder,
    all_system_keys: List[KeyRecord],
    profile: LockProfile
) -> Dict:
    axis_combinations = {}
    total_theoretical_keys = 1

    for axis in profile.axes:
        stacks = door.pin_stacks[axis.name]
        chamber_heights = [get_valid_shear_heights(s) for s in stacks]
        combos = list(itertools.product(*chamber_heights))
        axis_combinations[axis.name] = set(combos)
        total_theoretical_keys *= len(combos)

    unauthorized_interchanges = []
    for key in all_system_keys:
        if key.key_id in door.assigned_key_ids or key.level == "Control":
            continue

        opens_all_axes = True
        for axis in profile.axes:
            key_tuple = tuple(key.bitting[axis.name])
            if key_tuple not in axis_combinations[axis.name]:
                opens_all_axes = False
                break

        if opens_all_axes:
            unauthorized_interchanges.append(key.key_id)

    phantom_count = total_theoretical_keys - len(
        [k for k in door.assigned_key_ids if k != "CTRL"]
    )

    return {
        "door_id": door.door_id,
        "door_name": door.door_name,
        "total_working_bittings": total_theoretical_keys,
        "phantom_key_count": max(0, phantom_count),
        "unauthorized_interchange_keys": unauthorized_interchanges
    }
