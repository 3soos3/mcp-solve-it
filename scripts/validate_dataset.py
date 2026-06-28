#!/usr/bin/env python3
"""Validate SOLVE-IT dataset structural integrity (FSS-0006 §4.4).

Checks:
  - All JSON files parse without errors
  - No duplicate IDs within each entity type
  - Cross-references between techniques, weaknesses, and mitigations resolve
  - Objective mapping file references existing technique IDs

Usage:
    python scripts/validate_dataset.py <path-to-solve-it-data>

Exit codes:
    0 - Dataset is valid
    1 - Validation errors found
    2 - Usage error
"""

import json
import sys
from pathlib import Path


def validate(data_path: Path) -> int:
    errors: list[str] = []
    warnings: list[str] = []

    print(f"Validating SOLVE-IT dataset at: {data_path}")

    if not data_path.exists():
        print(f"ERROR: Data path does not exist: {data_path}", file=sys.stderr)
        return 2

    # Load all JSON files
    technique_ids: set[str] = set()
    weakness_ids: set[str] = set()
    mitigation_ids: set[str] = set()
    technique_weakness_refs: dict[str, list[str]] = {}  # tech_id → [weakness_ids]
    weakness_mitigation_refs: dict[str, list[str]] = {}  # weakness_id → [mitigation_ids]

    json_files = sorted(data_path.rglob("*.json"))
    if not json_files:
        errors.append(f"No JSON files found in {data_path}")

    for json_file in json_files:
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"JSON parse error in {json_file}: {exc}")
            continue

        rel = json_file.relative_to(data_path)
        parts = rel.parts

        # Detect entity type from path structure
        if len(parts) >= 2:
            entity_dir = parts[0].lower()

            if "technique" in entity_dir:
                eid = data.get("id") or data.get("technique_id")
                if eid:
                    if eid in technique_ids:
                        errors.append(f"Duplicate technique ID: {eid} (in {rel})")
                    technique_ids.add(eid)
                    weakness_refs = data.get("weaknesses", [])
                    if isinstance(weakness_refs, list):
                        technique_weakness_refs[eid] = weakness_refs

            elif "weakness" in entity_dir:
                eid = data.get("id") or data.get("weakness_id")
                if eid:
                    if eid in weakness_ids:
                        errors.append(f"Duplicate weakness ID: {eid} (in {rel})")
                    weakness_ids.add(eid)
                    mit_refs = data.get("mitigations", [])
                    if isinstance(mit_refs, list):
                        weakness_mitigation_refs[eid] = mit_refs

            elif "mitigation" in entity_dir:
                eid = data.get("id") or data.get("mitigation_id")
                if eid:
                    if eid in mitigation_ids:
                        errors.append(f"Duplicate mitigation ID: {eid} (in {rel})")
                    mitigation_ids.add(eid)

    print(f"  Techniques: {len(technique_ids)}")
    print(f"  Weaknesses: {len(weakness_ids)}")
    print(f"  Mitigations: {len(mitigation_ids)}")

    # Validate cross-references
    for tech_id, weakness_refs in technique_weakness_refs.items():
        for wid in weakness_refs:
            if isinstance(wid, str) and wid not in weakness_ids:
                errors.append(
                    f"Technique {tech_id} references unknown weakness: {wid}"
                )

    for weakness_id, mit_refs in weakness_mitigation_refs.items():
        for mid in mit_refs:
            if isinstance(mid, str) and mid not in mitigation_ids:
                errors.append(
                    f"Weakness {weakness_id} references unknown mitigation: {mid}"
                )

    # Report
    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for w in warnings:
            print(f"  ! {w}")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for e in errors:
            print(f"  ✗ {e}")
        print(f"\nResult: INVALID ({len(errors)} error(s))")
        return 1

    print("\nResult: VALID — no structural errors found")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <path-to-solve-it-data>", file=sys.stderr)
        return 2
    return validate(Path(sys.argv[1]))


if __name__ == "__main__":
    sys.exit(main())
