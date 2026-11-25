from dataclasses import dataclass, field
from typing import List, Dict, Optional

@dataclass
class AxisConfig:
    name: str
    pin_count: int
    min_depth: int
    max_depth: int
    macs: int
    step_size: int = 2
    min_master_pin: int = 2

@dataclass
class LockProfile:
    name: str
    is_sfic: bool = False
    sfic_stack_height: int = 23
    axes: List[AxisConfig] = field(default_factory=list)

@dataclass
class KeyRecord:
    key_id: str
    level: str
    parent_id: Optional[str]
    bitting: Dict[str, List[int]]

@dataclass
class DoorCylinder:
    door_id: str
    door_name: str
    assigned_key_ids: List[str]
    pin_stacks: Dict[str, List[Dict]] = field(default_factory=dict)
