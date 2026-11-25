from typing import Dict
from .models import AxisConfig, LockProfile

KEYWAY_PRESETS: Dict[str, LockProfile] = {
    "schlage_6": LockProfile(
        name="Schlage Classic (C/E) - 6 Pin Inline",
        is_sfic=False,
        axes=[AxisConfig(name="Primary", pin_count=6, min_depth=0, max_depth=9, macs=7, step_size=2)]
    ),
    "schlage_5": LockProfile(
        name="Schlage Classic (C/E) - 5 Pin Inline",
        is_sfic=False,
        axes=[AxisConfig(name="Primary", pin_count=5, min_depth=0, max_depth=9, macs=7, step_size=2)]
    ),
    "kwikset_5": LockProfile(
        name="Kwikset (KW1) - 5 Pin Inline",
        is_sfic=False,
        axes=[AxisConfig(name="Primary", pin_count=5, min_depth=1, max_depth=6, macs=4, step_size=2)]
    ),
    "best_sfic_a2_6": LockProfile(
        name="Best / Falcon SFIC A2 - 6 Pin",
        is_sfic=True,
        sfic_stack_height=23,
        axes=[AxisConfig(name="Primary", pin_count=6, min_depth=0, max_depth=9, macs=9, step_size=1)]
    ),
    "best_sfic_a2_7": LockProfile(
        name="Best / Falcon SFIC A2 - 7 Pin",
        is_sfic=True,
        sfic_stack_height=23,
        axes=[AxisConfig(name="Primary", pin_count=7, min_depth=0, max_depth=9, macs=9, step_size=1)]
    ),
    "yale_8_6": LockProfile(
        name="Yale 8 / Para - 6 Pin Inline",
        is_sfic=False,
        axes=[AxisConfig(name="Primary", pin_count=6, min_depth=0, max_depth=9, macs=8, step_size=2)]
    ),
    "corbin_russwin_6": LockProfile(
        name="Corbin Russwin (Z-Class) - 6 Pin Inline",
        is_sfic=False,
        axes=[AxisConfig(name="Primary", pin_count=6, min_depth=1, max_depth=6, macs=5, step_size=1)]
    ),
    "sargent_6": LockProfile(
        name="Sargent (LA-LC) - 6 Pin Inline",
        is_sfic=False,
        axes=[AxisConfig(name="Primary", pin_count=6, min_depth=1, max_depth=10, macs=7, step_size=2)]
    ),
    "hybrid_dimple_side": LockProfile(
        name="Custom High-Security (6 Inline + 4 Dimple + 3 Side-Pin)",
        is_sfic=False,
        axes=[
            AxisConfig(name="Primary Inline", pin_count=6, min_depth=1, max_depth=9, macs=7, step_size=2),
            AxisConfig(name="Dimple Top", pin_count=4, min_depth=1, max_depth=5, macs=4, step_size=1),
            AxisConfig(name="Side Bar", pin_count=3, min_depth=1, max_depth=4, macs=3, step_size=1),
        ]
    )
}
