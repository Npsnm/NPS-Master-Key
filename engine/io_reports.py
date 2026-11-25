import csv
from typing import List
from .models import KeyRecord, DoorCylinder, LockProfile

def export_key_cutting_schedule(keys: List[KeyRecord], profile: LockProfile, filepath: str):
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        headers = ["Key ID", "Level", "Parent ID"] + [a.name for a in profile.axes]
        writer.writerow(headers)
        for k in keys:
            row = [k.key_id, k.level, k.parent_id or "-"]
            for a in profile.axes:
                row.append("-".join(map(str, k.bitting[a.name])))
            writer.writerow(row)
