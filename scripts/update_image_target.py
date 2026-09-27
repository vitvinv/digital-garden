#!/usr/bin/env python3
"""Fold a Studio-generated image-target set back into the canonical name.

8th Wall Studio's "update from source" flow generates a NEW target set with a
numeric suffix (e.g. `thesunkengarden-target-2.json` + resources) and repoints
the scene at it. This script merges that set into the canonical base name:

  1. overwrite the canonical `_luminance/_original/_cropped/_thumbnail` files
     with the new set's files (the tracking data lives in the luminance image
     and `properties`, the name is just a label),
  2. rewrite the new json's `name`, `imagePath` and `resources` to the
     canonical base and save it as `<canonical>.json`,
  3. repoint every `.expanse.json` imageTarget.name back to the canonical name,
  4. delete the suffixed set.

app.js and the scene keep referencing the canonical name — nothing else in the
project changes when a target is updated from source.

Usage:
  python scripts/update_image_target.py <garden-dir> <canonical-base> [new-base]
  python scripts/update_image_target.py thesunkenblimp-garden thesunkengarden-target            # auto-detect new set
  python scripts/update_image_target.py thesunkenblimp-garden thesunkengarden-target thesunkengarden-target-2
  add --dry-run to preview
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

RESOURCE_KEYS = ("originalImage", "croppedImage", "thumbnailImage", "luminanceImage")
NUMERIC_SUFFIX_RE = re.compile(r"^(?P<base>.+?)[-_\s]?\d+$")


def find_new_set(targets_dir: Path, canonical: str) -> str:
    """Newest json in targets_dir whose name is the canonical name + numeric suffix."""
    candidates = []
    for json_path in targets_dir.glob("*.json"):
        stem = json_path.stem
        if stem == canonical:
            continue
        match = NUMERIC_SUFFIX_RE.match(stem)
        if not match or match.group("base") != canonical:
            continue
        try:
            created = json.loads(json_path.read_text(encoding="utf-8")).get("created", 0)
        except (json.JSONDecodeError, OSError):
            created = json_path.stat().st_mtime * 1000
        candidates.append((created, stem))
    if not candidates:
        raise SystemExit(
            f"ERROR: no generated set for '{canonical}' found in {targets_dir}/. "
            "Add the updated source image in 8th Wall Studio first (it creates "
            f"'{canonical}-2.json' or similar), then re-run this script."
        )
    candidates.sort(reverse=True)
    return candidates[0][1]


def repair_missing_resources(targets_dir: Path, canonical: str, dry_run: bool) -> int:
    """Rewrite resources entries that point at missing files to existing
    canonical-named files. Handles Studio's 'update from source' variant that
    versions the resource FILES (-1) but keeps the canonical target name."""
    json_path = targets_dir / f"{canonical}.json"
    target = json.loads(json_path.read_text(encoding="utf-8"))
    fixed = 0
    for key, file_name in target.get("resources", {}).items():
        if (targets_dir / file_name).exists():
            continue
        suffix = Path(file_name).suffix
        canonical_file = f"{canonical}_{key.replace('Image', '').lower()}{suffix}"
        if not (targets_dir / canonical_file).exists():
            print(f"ERROR: neither {file_name} nor {canonical_file} exists in {targets_dir}/")
            return 1
        print(f"  {key}: {file_name} -> {canonical_file} (file was missing)")
        target["resources"][key] = canonical_file
        fixed += 1
    if target.get("imagePath") and not (garden_dir_path(targets_dir) / target["imagePath"]).exists():
        target["imagePath"] = f"image-targets/{target['resources']['luminanceImage']}"
        print(f"  imagePath -> {target['imagePath']}")
        fixed += 1
    if fixed and not dry_run:
        target["updated"] = int(time.time() * 1000)
        json_path.write_text(json.dumps(target, indent=2) + "\n", encoding="utf-8")
    print(f"Repaired {fixed} reference(s)." if fixed else "Nothing to repair — all resources resolve.")
    return 0


def garden_dir_path(targets_dir: Path) -> Path:
    return targets_dir.parent


def main() -> int:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    if len(args) < 2:
        print(__doc__)
        return 1
    garden_dir = Path(args[0])
    canonical = args[1]
    targets_dir = garden_dir / "image-targets"
    if not (targets_dir / f"{canonical}.json").exists():
        print(f"ERROR: {targets_dir / (canonical + '.json')} not found.")
        return 1

    if "--repair" in args:
        return repair_missing_resources(targets_dir, canonical, dry_run)

    new_base = args[2] if len(args) > 2 else find_new_set(targets_dir, canonical)
    new_json_path = targets_dir / f"{new_base}.json"
    target = json.loads(new_json_path.read_text(encoding="utf-8"))
    if target.get("name") != new_base:
        print(f"ERROR: {new_json_path} declares name={target.get('name')!r}, expected {new_base!r}.")
        return 1

    print(f"Canonical: {canonical}")
    print(f"Generated: {new_base} (created {target.get('created')})")

    # 1-2. Copy the new set's files over the canonical names, rewriting identity.
    resources = {}
    for key, file_name in target.get("resources", {}).items():
        suffix = Path(file_name).suffix  # .jpg / .png — keep whatever Studio produced
        canonical_file = f"{canonical}_{key.replace('Image', '').lower()}{suffix}"
        resources[key] = f"{canonical}_{key.replace('Image', '').lower()}{suffix}"
        src = targets_dir / file_name
        dst = targets_dir / canonical_file
        for stale in targets_dir.glob(f"{canonical}_{key.replace('Image', '').lower()}.*"):
            if stale.name != canonical_file and not dry_run:
                stale.unlink()  # old extension (png vs jpg) must not linger
        print(f"  {file_name} -> {dst.name}")
        if not dry_run:
            src.replace(dst)

    target["name"] = canonical
    target["imagePath"] = f"image-targets/{resources['luminanceImage']}"
    target["updated"] = int(time.time() * 1000)
    canonical_json = targets_dir / f"{canonical}.json"
    print(f"  {new_json_path.name} -> {canonical_json.name} (name/imagePath/resources rewritten)")
    if not dry_run:
        canonical_json.write_text(json.dumps(target, indent=2) + "\n", encoding="utf-8")
        new_json_path.unlink(missing_ok=True)

    # 3. Repoint the scene back to the canonical target name.
    scene_path = garden_dir / "src" / ".expanse.json"
    n_fixed = 0
    if scene_path.exists():
        scene_text = scene_path.read_text(encoding="utf-8")
        repoint_re = re.compile(
            r'("imageTarget"\s*:\s*\{\s*"name"\s*:\s*")' + re.escape(new_base) + '(")'
        )
        scene_text, n_fixed = repoint_re.subn(r"\g<1>" + canonical + r"\g<2>", scene_text)
        if n_fixed:
            print(f"  .expanse.json: {n_fixed} imageTarget reference(s) repointed")
            if not dry_run:
                scene_path.write_text(scene_text, encoding="utf-8")
        else:
            print("  .expanse.json: no references to repoint")
    else:
        print(f"  .expanse.json not found ({scene_path}) — scene not repointed")

    print("Done." + (" (dry run — nothing written)" if dry_run else " Now: npm run build && push."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
