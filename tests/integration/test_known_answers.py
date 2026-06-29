"""Known-Answer Tests (KATs) against real SOLVE-IT data (FSS-0006 §4.2).

These tests verify that specific tool outputs match values derived by
inspecting the raw SOLVE-IT JSON files directly — NOT by running the tool
first and recording the output. Expected values are pinned to:

    SOLVE-IT git tag: v0.2026-06
    Data path:        SOLVE_IT_DATA_PATH
    KB counts:        181 techniques, 307 weaknesses, 256 mitigations
                      (enable_extensions=False, base KB only)

Run with:
    pytest tests/integration/test_known_answers.py -v -m kat

Skip if SOLVE-IT data is unavailable:
    pytest -m "not kat"
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

# ── SOLVE-IT data path ────────────────────────────────────────────────────────

_SOLVEIT_PATH = os.environ.get(
    "SOLVE_IT_DATA_PATH",
    "SOLVE_IT_DATA_PATH",
)

pytestmark = [pytest.mark.kat, pytest.mark.integration]


@pytest.fixture(scope="module")
def kb() -> Any:
    """Load the SOLVE-IT KnowledgeBase from the local data path."""
    data_path = Path(_SOLVEIT_PATH)
    if not data_path.exists():
        pytest.skip(
            f"SOLVE-IT data not found at {_SOLVEIT_PATH}. "
            "Set SOLVE_IT_DATA_PATH to the repo root and re-run."
        )
    sys.path.insert(0, str(data_path))
    try:
        from solve_it_library import KnowledgeBase  # type: ignore[import]
    except ImportError:
        pytest.skip("solve_it_library not importable from SOLVE_IT_DATA_PATH")

    return KnowledgeBase(
        base_path=str(data_path),
        mapping_file="solve-it.json",
        enable_extensions=False,
    )


# ── Technique KATs ────────────────────────────────────────────────────────────

class TestTechniqueKATs:
    """Known-answer tests for solveit_get_technique equivalent."""

    def test_dft_1001_name(self, kb: Any) -> None:
        t = kb.get_technique("DFT-1001")
        assert t["name"] == "Triage"

    def test_dft_1001_weaknesses(self, kb: Any) -> None:
        # Expected: derived from data/techniques/DFT-1001.json
        t = kb.get_technique("DFT-1001")
        assert t["weaknesses"] == ["DFW-1001", "DFW-1002", "DFW-1003"]

    def test_dft_1001_references_contain_dfcite_1115(self, kb: Any) -> None:
        t = kb.get_technique("DFT-1001")
        cite_ids = [r["DFCite_id"] for r in t.get("references", [])]
        assert "DFCite-1115" in cite_ids

    def test_nonexistent_technique_returns_none(self, kb: Any) -> None:
        assert kb.get_technique("DFT-9999") is None

    def test_technique_count_base_kb(self, kb: Any) -> None:
        # Base KB (enable_extensions=False), v0.2026-06
        assert len(kb.list_techniques()) == 181

    def test_all_technique_ids_are_strings(self, kb: Any) -> None:
        # list_techniques() returns a list of ID strings (e.g. "DFT-1001")
        for t in kb.list_techniques():
            assert isinstance(t, str) and t.startswith("DFT-"), f"Unexpected: {t}"


# ── Weakness KATs ─────────────────────────────────────────────────────────────

class TestWeaknessKATs:
    """Known-answer tests for solveit_get_weakness equivalent."""

    def test_dfw_1001_name(self, kb: Any) -> None:
        # Expected: from data/weaknesses/DFW-1001.json
        w = kb.get_weakness("DFW-1001")
        assert w["name"] == "Excluding a device that contains relevant information"

    def test_dfw_1001_has_no_mitigations_in_base_kb(self, kb: Any) -> None:
        w = kb.get_weakness("DFW-1001")
        assert w.get("mitigations", []) == []

    def test_nonexistent_weakness_returns_none(self, kb: Any) -> None:
        assert kb.get_weakness("DFW-9999") is None

    def test_weakness_count_base_kb(self, kb: Any) -> None:
        assert len(kb.list_weaknesses()) == 307

    def test_all_weakness_ids_are_strings(self, kb: Any) -> None:
        for w in kb.list_weaknesses():
            assert isinstance(w, str) and w.startswith("DFW-"), f"Unexpected: {w}"


# ── Mitigation KATs ───────────────────────────────────────────────────────────

class TestMitigationKATs:
    """Known-answer tests for solveit_get_mitigation equivalent."""

    def test_dfm_1001_name(self, kb: Any) -> None:
        # Expected: from data/mitigations/DFM-1001.json
        m = kb.get_mitigation("DFM-1001")
        assert m["name"] == (
            "Review of all triage results that are relied on during the full "
            "digital forensic examination"
        )

    def test_nonexistent_mitigation_returns_none(self, kb: Any) -> None:
        assert kb.get_mitigation("DFM-9999") is None

    def test_mitigation_count_base_kb(self, kb: Any) -> None:
        assert len(kb.list_mitigations()) == 256

    def test_all_mitigation_ids_are_strings(self, kb: Any) -> None:
        for m in kb.list_mitigations():
            assert isinstance(m, str) and m.startswith("DFM-"), f"Unexpected: {m}"


# ── Relationship KATs ─────────────────────────────────────────────────────────

class TestRelationshipKATs:
    """Known-answer tests for relationship traversal tools."""

    def test_weaknesses_for_dft_1001(self, kb: Any) -> None:
        # Expected: DFT-1001 links to DFW-1001, DFW-1002, DFW-1003
        w = kb.get_weaknesses_for_technique("DFT-1001")
        ids = [x["id"] if isinstance(x, dict) else x for x in w]
        assert "DFW-1001" in ids
        assert "DFW-1002" in ids
        assert "DFW-1003" in ids
        assert len(ids) == 3

    def test_mitigations_for_dfw_1002(self, kb: Any) -> None:
        # Expected: DFW-1002 is mitigated by DFM-1007 and DFM-1008
        m = kb.get_mitigations_for_weakness("DFW-1002")
        ids = [x["id"] if isinstance(x, dict) else x for x in m]
        assert "DFM-1007" in ids
        assert "DFM-1008" in ids
        assert len(ids) == 2

    def test_techniques_for_dfw_1001(self, kb: Any) -> None:
        # DFW-1001 should link back to at least DFT-1001
        t = kb.get_techniques_for_weakness("DFW-1001")
        ids = [x["id"] if isinstance(x, dict) else x for x in t]
        assert "DFT-1001" in ids

    def test_mitigations_for_dfw_1001_is_empty(self, kb: Any) -> None:
        # DFW-1001 has no mitigations in the base KB
        m = kb.get_mitigations_for_weakness("DFW-1001")
        assert len(m) == 0


# ── Search KATs ───────────────────────────────────────────────────────────────

class TestSearchKATs:
    """Known-answer tests for solveit_search equivalent."""

    def test_search_triage_finds_dft_1001(self, kb: Any) -> None:
        results = kb.search(keywords="triage")
        ids: list[str] = []
        for category in results.values() if isinstance(results, dict) else [results]:
            for item in (category if isinstance(category, list) else []):
                item_id = item.get("id") if isinstance(item, dict) else getattr(item, "id", None)
                if item_id:
                    ids.append(item_id)
        assert "DFT-1001" in ids, f"DFT-1001 not found in triage search: {ids[:5]}"

    def test_search_nonexistent_returns_empty(self, kb: Any) -> None:
        results = kb.search(keywords="xyzzy_no_match_9a8b7c")
        total = sum(
            len(v) for v in results.values()
            if isinstance(results, dict) and isinstance(v, list)
        ) if isinstance(results, dict) else 0
        assert total == 0, f"Expected no results for nonsense query, got: {results}"

    def test_search_and_logic_more_restrictive(self, kb: Any) -> None:
        or_results = kb.search(keywords="memory acquisition", search_logic="OR")
        and_results = kb.search(keywords="memory acquisition", search_logic="AND")

        def count(r: Any) -> int:
            if isinstance(r, dict):
                return sum(len(v) for v in r.values() if isinstance(v, list))
            return len(r) if isinstance(r, list) else 0

        assert count(and_results) <= count(or_results), \
            "AND search should return ≤ results than OR search"


# ── Citation KATs ─────────────────────────────────────────────────────────────

class TestCitationKATs:
    """Known-answer tests for citation resolution."""

    def test_dfcite_1001_exists(self, kb: Any) -> None:
        c = kb.get_citation("DFCite-1001")
        assert c is not None, "DFCite-1001 should exist in the KB"

    def test_citation_has_bibtex_or_url(self, kb: Any) -> None:
        c = kb.get_citation("DFCite-1001")
        assert c is not None
        has_ref = "bibtex" in c or "url" in c or "reference" in c
        assert has_ref, f"Citation should have a bibliographic field: {list(c.keys())}"

    def test_nonexistent_citation_returns_none(self, kb: Any) -> None:
        assert kb.get_citation("DFCite-9999") is None

    def test_resolve_inline_citation(self, kb: Any) -> None:
        text = "See [DFCite-1001] for details."
        resolved = kb.resolve_inline_citations(text)
        assert "[DFCite-1001]" not in resolved, \
            f"Citation marker should be resolved: {resolved!r}"
        assert len(resolved) > 0
