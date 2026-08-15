"""Strip the AR scene down to the entry (Garden) space.

Removes spaces: BMO Bites, Magic Photos, Toggle SLAM, Space Selector
and every object outside the entry space tree. Those spaces referenced
deleted custom components (Pause Video on Image Target Lost, Coconut
Spawner, Toggle SLAM on Found), a missing camera, missing image targets
and missing assets - which crash the runtime at startup.

Usage: python scripts/strip_scene.py [--dry-run] [--write]
"""
import json
import sys
from pathlib import Path

SCENE = Path(__file__).resolve().parent.parent / "digital-garden-AR" / "src" / ".expanse.json"


def main():
    dry = "--dry-run" in sys.argv
    write = "--write" in sys.argv
    if not (dry or write):
        print("pass --dry-run to inspect or --write to save")
        sys.exit(1)

    scene = json.loads(SCENE.read_text(encoding="utf-8"))
    objs, spaces = scene["objects"], scene["spaces"]
    entry = scene["entrySpaceId"]
    print(f"entry space: {spaces[entry]['name']}")

    keep = set()
    def walk(parent):
        for k, o in objs.items():
            if o.get("parentId") == parent and k not in keep:
                keep.add(k)
                walk(k)
    walk(entry)

    print(f"objects before: {len(objs)}  after: {len(keep)}  spaces before: {len(spaces)}  after: 1")

    for k in sorted(keep):
        o = objs[k]
        comps = [c.get("name") for c in (o.get("components") or {}).values()]
        print(f"  {str(o.get('name', '?'))[:44]:46} parent={str(o.get('parentId',''))[:8]} comps={comps}")

    if dry:
        return

    # keep entry space only
    new_spaces = {entry: spaces[entry]}
    new_objs = {k: objs[k] for k in keep}

    # drop references to removed spaces as parentIds (should not happen)
    for o in new_objs.values():
        p = o.get("parentId")
        if p not in new_spaces and p not in new_objs:
            print(f"WARN: object {o.get('name')} parent {p} not kept - removing parentId")
            o.pop("parentId", None)

    scene["objects"] = new_objs
    scene["spaces"] = new_spaces
    SCENE.write_text(json.dumps(scene, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {SCENE}")


if __name__ == "__main__":
    main()
