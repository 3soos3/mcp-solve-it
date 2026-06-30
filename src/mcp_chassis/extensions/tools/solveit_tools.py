"""SOLVE-IT MCP tool extensions.

Registers tools that expose the SOLVE-IT knowledge base to LLM clients.
Requires the init hook (``solveit_init.py``) to have loaded the
KnowledgeBase onto ``server._kb`` before this module's ``register()``
runs.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from mcp_chassis.extensions.batch import register_simple_tools

if TYPE_CHECKING:
    from mcp_chassis.context import HandlerContext
    from mcp_chassis.server import ChassisServer

logger = logging.getLogger(__name__)


# ── Status tool (always registered, even on degraded startup) ──────────


def _register_status_tool(server: ChassisServer) -> None:
    """Register solveit_status — always available, even if KB failed."""
    kb = getattr(server, "_kb", None)
    kb_error = getattr(server, "_kb_error", None)

    async def _handle(arguments: dict[str, Any], context: HandlerContext) -> str:
        await context.log_debug("solveit_status called")
        if kb is None:
            return json.dumps(
                {
                    "status": "error",
                    "error": kb_error or "Knowledge base not loaded",
                }
            )
        report: dict[str, Any] = {
            "status": "ok",
            "techniques": len(kb.list_techniques()),
            "weaknesses": len(kb.list_weaknesses()),
            "mitigations": len(kb.list_mitigations()),
            "citations": len(kb.citations),
        }
        if kb.has_extensions():
            report["extensions"] = kb.list_loaded_extensions()
        return json.dumps(report)

    server.register_tool(
        name="solveit_status",
        description=(
            "SOLVE-IT knowledge base status. Returns item counts (techniques, "
            "weaknesses, mitigations, citations) and loaded extensions when "
            "healthy, or error details if the KB failed to load. "
            "Call this if tools are returning errors to diagnose the issue."
        ),
        input_schema={"type": "object", "properties": {}},
        handler=_handle,
    )


# ── Database description tool ──────────────────────────────────────────


def _register_database_description_tool(server: ChassisServer, kb: Any) -> None:
    """Register solveit_get_database_description — orientation tool."""

    async def _handle(arguments: dict[str, Any], context: HandlerContext) -> str:
        await context.log_debug("solveit_get_database_description called")
        try:
            mappings: list[str] = []
            try:
                mappings = kb.list_available_mappings()
            except Exception:
                pass

            description = {
                "database_name": "SOLVE-IT Digital Forensics Knowledge Base",
                "description": (
                    "A systematic digital forensics knowledge base inspired by MITRE ATT&CK"
                ),
                "purpose": (
                    "Provides comprehensive mapping of digital forensic investigation "
                    "techniques, weaknesses, and mitigations"
                ),
                "entity_types": {
                    "techniques": (
                        "Digital forensic investigation methods (DFT-1001, DFT-1002, …)"
                    ),
                    "weaknesses": (
                        "Potential problems or limitations of techniques (DFW-1001, DFW-1002, …)"
                    ),
                    "mitigations": ("Ways to address weaknesses (DFM-1001, DFM-1002, …)"),
                    "objectives": (
                        "Investigation workflow phases that group techniques "
                        "(e.g. 'Acquire data', 'Preserve digital evidence')"
                    ),
                    "citations": (
                        "Academic and industry references cited by techniques "
                        "and weaknesses (DFCite-XXXX)"
                    ),
                },
                "statistics": {
                    "techniques": len(kb.list_techniques()),
                    "weaknesses": len(kb.list_weaknesses()),
                    "mitigations": len(kb.list_mitigations()),
                    "citations": len(kb.citations),
                },
                "available_mappings": mappings,
                "available_operations": [
                    "Search across techniques, weaknesses, and mitigations by "
                    "keyword (solveit_search)",
                    "Retrieve detailed information by ID "
                    "(solveit_get_technique, solveit_get_weakness, "
                    "solveit_get_mitigation)",
                    "Explore relationships between components "
                    "(solveit_get_weaknesses_for_technique, "
                    "solveit_get_mitigations_for_weakness, …)",
                    "Resolve citations (DFCite-XXXX) to full bibliographic "
                    "text (solveit_get_citation, "
                    "solveit_resolve_inline_citations)",
                    "Work with different objective mappings "
                    "(solveit_list_available_mappings, "
                    "solveit_load_objective_mapping)",
                    "Bulk retrieval operations "
                    "(solveit_list_techniques, solveit_list_weaknesses, "
                    "solveit_list_mitigations)",
                ],
            }
            return json.dumps(description, indent=2)
        except Exception as exc:
            return json.dumps({"error": f"Failed to retrieve database description: {exc}"})

    server.register_tool(
        name="solveit_get_database_description",
        description=(
            "Call this first to understand the SOLVE-IT knowledge base before "
            "using other tools. Returns the database structure, entity types "
            "(techniques DFT-XXXX, weaknesses DFW-XXXX, mitigations DFM-XXXX, "
            "citations DFCite-XXXX), available objective mappings, and item "
            "counts. Use this to orient yourself before searching or retrieving "
            "specific items."
        ),
        input_schema={"type": "object", "properties": {}},
        handler=_handle,
    )


# ── Batch tools (get-by-ID and list-all) ──────────────────────────────

_BATCH_TOOLS: list[dict[str, Any]] = [
    {
        "name": "solveit_get_technique",
        "description": (
            "Get full details for a technique by its DFT-XXXX ID. "
            "The response includes name, description, subtechniques, and a "
            "'weaknesses' list of DFW-XXXX IDs. References appear as "
            "DFCite-XXXX IDs — call solveit_get_citation to resolve them to "
            "full bibliographic text. Use solveit_get_weaknesses_for_technique "
            "to get weakness details in one step instead of resolving each "
            "DFW-XXXX manually."
        ),
        "method": "get_technique",
        "param": "technique_id",
        "param_description": "The technique ID (e.g. DFT-1001).",
        "param_schema": {"type": "string", "minLength": 1},
        "not_found_check": True,
        "tool_version": "1.0.0",
        "idempotent": True,
        "side_effects": False,
        "deterministic": True,
        "known_limitations": (
            "Coverage is limited to techniques documented in the active SOLVE-IT "
            "KB version. Emerging techniques not yet included will not be found. "
            "Sub-technique content depends on whether the parent technique has "
            "been fully populated in the KB."
        ),
    },
    {
        "name": "solveit_get_weakness",
        "description": (
            "Get full details for a weakness by its DFW-XXXX ID. "
            "The 'name' field is the primary description of what can go wrong. "
            "The response includes ASTM error categories and a 'mitigations' "
            "list of DFM-XXXX IDs. Use solveit_get_mitigations_for_weakness "
            "to resolve those IDs to full mitigation details in one step."
        ),
        "method": "get_weakness",
        "param": "weakness_id",
        "param_description": "The weakness ID (e.g. DFW-1001).",
        "param_schema": {"type": "string", "minLength": 1},
        "not_found_check": True,
        "known_limitations": (
            "Coverage is limited to weaknesses documented in the active SOLVE-IT KB "
            "version. ASTM error category assignments reflect the KB author's "
            "classification and may not cover all interpretations. Weaknesses "
            "specific to highly specialised tools or jurisdictions may be absent."
        ),
    },
    {
        "name": "solveit_get_mitigation",
        "description": (
            "Get full details for a mitigation by its DFM-XXXX ID. "
            "The 'name' field is the primary description of the recommended "
            "action. Use solveit_get_weaknesses_for_mitigation or "
            "solveit_get_techniques_for_mitigation to understand which "
            "weaknesses and techniques this mitigation addresses."
        ),
        "method": "get_mitigation",
        "param": "mitigation_id",
        "param_description": "The mitigation ID (e.g. DFM-1001).",
        "param_schema": {"type": "string", "minLength": 1},
        "not_found_check": True,
        "known_limitations": (
            "Coverage is limited to mitigations documented in the active KB. "
            "The effectiveness of a mitigation in practice depends on the specific "
            "case context, available tools, and jurisdiction. Absence of a mitigation "
            "entry does not mean no remedy exists — it may simply not yet be "
            "documented in the KB."
        ),
    },
    {
        "name": "solveit_list_techniques",
        "description": (
            "Get all techniques as a concise ID+name list (~180 entries). "
            "Use this to browse the full catalogue or find IDs before calling "
            "solveit_get_technique. Prefer solveit_search when you have "
            "keywords — this returns everything."
        ),
        "method": "get_all_techniques_with_name_and_id",
        "known_limitations": (
            "Returns only IDs and names — no descriptions, weaknesses, or "
            "references. Call solveit_get_technique for full detail on a specific "
            "entry. The list reflects the KB snapshot loaded at server startup; "
            "newly added techniques require a server restart to appear."
        ),
    },
    {
        "name": "solveit_list_weaknesses",
        "description": (
            "Get all weaknesses as a concise ID+name list. "
            "Use this to browse all known weaknesses or find IDs before calling "
            "solveit_get_weakness. Prefer solveit_search when you have "
            "keywords — this returns everything."
        ),
        "method": "get_all_weaknesses_with_name_and_id",
        "known_limitations": (
            "Returns only IDs and names. Call solveit_get_weakness for full "
            "detail. The ASTM error category is not included in this listing. "
            "The list reflects the KB at startup time."
        ),
    },
    {
        "name": "solveit_list_mitigations",
        "description": (
            "Get all mitigations as a concise ID+name list. "
            "Use this to browse all available mitigations or find IDs before "
            "calling solveit_get_mitigation. Prefer solveit_search when you "
            "have keywords — this returns everything."
        ),
        "method": "get_all_mitigations_with_name_and_id",
        "known_limitations": (
            "Returns only IDs and names. Call solveit_get_mitigation for full "
            "detail including which weaknesses the mitigation addresses. "
            "The list reflects the KB at startup time."
        ),
    },
    {
        "name": "solveit_list_objectives",
        "description": (
            "List all investigation objectives (workflow phases) from the "
            "currently loaded mapping. Objectives group techniques by "
            "investigation goal — e.g. 'Acquire data', "
            "'Preserve digital evidence'. "
            "Use solveit_get_techniques_for_objective to get the techniques "
            "under a specific objective. Use solveit_load_objective_mapping "
            "to switch between frameworks (solve-it, carrier, dfrws)."
        ),
        "method": "list_objectives",
        "known_limitations": (
            "Results depend on the currently loaded objective mapping file. "
            "Different mappings (solve-it.json, carrier.json, dfrws.json) "
            "organise the same techniques into different phases with different "
            "objective names. Call solveit_list_available_mappings to see all "
            "available frameworks."
        ),
    },
    {
        "name": "solveit_get_techniques_for_objective",
        "description": (
            "Get all techniques belonging to a specific investigation "
            "objective (workflow phase). "
            "Use solveit_list_objectives first to get the exact objective "
            "names. "
            "Use this to answer 'what techniques are available for this phase "
            "of the investigation?' "
            "Forward direction: complements "
            "solveit_get_objectives_for_technique (reverse direction)."
        ),
        "method": "get_techniques_for_objective",
        "param": "objective_name",
        "param_description": "The objective name (e.g. 'Acquire data').",
        "param_schema": {"type": "string", "minLength": 1},
        "known_limitations": (
            "Objective names are case-sensitive and must exactly match those "
            "returned by solveit_list_objectives. Results vary between mapping "
            "files — the same technique may belong to different objectives in "
            "different frameworks."
        ),
    },
]


# ── Relationship tools ─────────────────────────────────────────────────

_RELATIONSHIP_TOOLS: list[dict[str, Any]] = [
    {
        "tool_name": "solveit_get_weaknesses_for_technique",
        "description": (
            "Get all weaknesses for a technique (DFT-XXXX) with full details "
            "in one call. More efficient than calling solveit_get_weakness for "
            "each DFW-XXXX ID from solveit_get_technique. "
            "Use this to answer 'what can go wrong with this technique?' "
            "Forward direction: complements "
            "solveit_get_techniques_for_weakness (reverse direction)."
        ),
        "lookup_method": "get_technique",
        "relation_method": "get_weaknesses_for_technique",
        "param_name": "technique_id",
        "param_description": "The technique ID (e.g. DFT-1001).",
        "known_limitations": (
            "Only weaknesses explicitly documented in the KB for this technique "
            "are returned. Context-specific weaknesses that are not yet captured "
            "in the KB will not appear. An empty list means no weaknesses are "
            "currently documented, not that none exist."
        ),
    },
    {
        "tool_name": "solveit_get_mitigations_for_weakness",
        "description": (
            "Get all mitigations for a weakness (DFW-XXXX) with full details "
            "in one call. More efficient than resolving each DFM-XXXX ID from "
            "solveit_get_weakness individually. "
            "Use this to answer 'how can this weakness be addressed?' "
            "Forward direction: complements "
            "solveit_get_weaknesses_for_mitigation (reverse direction)."
        ),
        "lookup_method": "get_weakness",
        "relation_method": "get_mitigations_for_weakness",
        "param_name": "weakness_id",
        "param_description": "The weakness ID (e.g. DFW-1001).",
        "known_limitations": (
            "An empty list means no mitigations are currently documented for this "
            "weakness in the KB, not that the weakness is unaddressable. "
            "Effectiveness of any listed mitigation depends on the specific case, "
            "available tools, and legal context."
        ),
    },
    {
        "tool_name": "solveit_get_techniques_for_weakness",
        "description": (
            "Find all techniques that can exhibit a specific weakness "
            "(DFW-XXXX). "
            "Use this for reverse lookup — e.g. 'which techniques are affected "
            "by this limitation?' "
            "Reverse direction: complements "
            "solveit_get_weaknesses_for_technique (forward direction)."
        ),
        "lookup_method": "get_weakness",
        "relation_method": "get_techniques_for_weakness",
        "param_name": "weakness_id",
        "param_description": "The weakness ID (e.g. DFW-1001).",
        "known_limitations": (
            "Only techniques with explicit technique→weakness links in the KB are "
            "returned. A weakness may apply to additional techniques that have not "
            "yet had this association documented."
        ),
    },
    {
        "tool_name": "solveit_get_weaknesses_for_mitigation",
        "description": (
            "Find all weaknesses that a mitigation (DFM-XXXX) addresses. "
            "Use this for reverse lookup — e.g. 'which weaknesses does this "
            "control fix?' "
            "Reverse direction: complements "
            "solveit_get_mitigations_for_weakness (forward direction)."
        ),
        "lookup_method": "get_mitigation",
        "relation_method": "get_weaknesses_for_mitigation",
        "param_name": "mitigation_id",
        "param_description": "The mitigation ID (e.g. DFM-1001).",
        "known_limitations": (
            "Derived from weakness→mitigation links in the KB. A mitigation may "
            "address weaknesses not yet listed if those associations have not been "
            "documented. Does not imply the mitigation is complete or sufficient "
            "for all listed weaknesses."
        ),
    },
    {
        "tool_name": "solveit_get_techniques_for_mitigation",
        "description": (
            "Find all techniques indirectly linked to a mitigation (DFM-XXXX) "
            "via their shared weaknesses. "
            "Use this to understand the scope of impact of a control — "
            "e.g. 'which techniques benefit from applying this mitigation?' "
            "Reverse direction: complements "
            "solveit_get_mitigations_for_technique (forward direction)."
        ),
        "lookup_method": "get_mitigation",
        "relation_method": "get_techniques_for_mitigation",
        "param_name": "mitigation_id",
        "param_description": "The mitigation ID (e.g. DFM-1001).",
        "known_limitations": (
            "Derived via weakness intermediaries: technique→weakness→mitigation. "
            "Techniques whose weaknesses are not yet linked to this mitigation in "
            "the KB will be absent even if the mitigation logically applies to them."
        ),
    },
]


def _register_relationship_tools(server: ChassisServer, kb: Any) -> None:
    """Register relationship tools with ID validation."""
    for defn in _RELATIONSHIP_TOOLS:
        tool_name = defn["tool_name"]
        description = defn["description"]
        lookup = getattr(kb, defn["lookup_method"])
        relation = getattr(kb, defn["relation_method"])
        param_name = defn["param_name"]
        param_description = defn["param_description"]

        async def _handle(
            arguments: dict[str, Any],
            context: HandlerContext,
            _tool_name: str = tool_name,
            _lookup: Any = lookup,
            _relation: Any = relation,
            _param: str = param_name,
        ) -> str:
            await context.log_debug(f"{_tool_name} called")
            item_id = arguments[_param]
            if _lookup(item_id) is None:
                return json.dumps({"error": "not_found", "id": item_id})
            return json.dumps(_relation(item_id))

        server.register_tool(
            name=tool_name,
            description=description,
            input_schema={
                "type": "object",
                "properties": {
                    param_name: {
                        "type": "string",
                        "description": param_description,
                        "minLength": 1,
                    },
                },
                "required": [param_name],
            },
            handler=_handle,
            known_limitations=defn.get("known_limitations", ""),
        )


# ── Cross-traversal shortcut ───────────────────────────────────────────


def _register_mitigations_for_technique_tool(server: ChassisServer, kb: Any) -> None:
    """Register solveit_get_mitigations_for_technique."""

    async def _handle(arguments: dict[str, Any], context: HandlerContext) -> str:
        await context.log_debug("solveit_get_mitigations_for_technique called")
        technique_id = arguments["technique_id"]
        try:
            if kb.get_technique(technique_id) is None:
                return json.dumps({"error": "not_found", "id": technique_id})
            mitigation_ids = kb.get_mit_list_for_technique(technique_id)
            return json.dumps({"technique_id": technique_id, "mitigations": mitigation_ids})
        except Exception as exc:
            return json.dumps({"error": f"Failed to retrieve mitigations for technique: {exc}"})

    server.register_tool(
        name="solveit_get_mitigations_for_technique",
        description=(
            "Get all mitigations for a technique in one call, skipping the "
            "weakness intermediary. "
            "Shortcut for the technique → weaknesses → mitigations traversal. "
            "Use this when you want to know how to address limitations of a "
            "technique without needing to inspect individual weaknesses first."
        ),
        known_limitations=(
            "Traverses technique→weakness→mitigation links. A technique with "
            "no documented weaknesses will return an empty list. Ordering of "
            "mitigations is not guaranteed. Mitigations are returned as IDs "
            "only — call solveit_get_mitigation for full details."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "technique_id": {
                    "type": "string",
                    "description": "The technique ID (e.g. DFT-1001).",
                    "minLength": 1,
                },
            },
            "required": ["technique_id"],
        },
        handler=_handle,
    )


# ── Objective / mapping tools ──────────────────────────────────────────


def _register_objectives_and_mapping_tools(server: ChassisServer, kb: Any) -> None:
    """Register reverse-objective lookup and mapping switch tools."""

    # solveit_get_objectives_for_technique
    async def _handle_obj_for_tech(arguments: dict[str, Any], context: HandlerContext) -> str:
        await context.log_debug("solveit_get_objectives_for_technique called")
        technique_id = arguments["technique_id"]
        try:
            objectives = kb.get_objectives_for_technique(technique_id)
            return json.dumps(objectives)
        except Exception as exc:
            return json.dumps({"error": f"Failed to retrieve objectives for technique: {exc}"})

    server.register_tool(
        name="solveit_get_objectives_for_technique",
        description=(
            "Find which investigation objectives (workflow phases) a technique "
            "belongs to. "
            "Use this for reverse lookup — e.g. 'at what stage of an "
            "investigation is this technique used?' "
            "Also handles subtechniques by returning the parent technique's "
            "objectives. "
            "Reverse direction: complements "
            "solveit_get_techniques_for_objective (forward direction)."
        ),
        known_limitations=(
            "Results depend on the currently loaded objective mapping. "
            "Subtechniques return the parent's objectives, so the ID in the "
            "result may differ from the requested ID. If the technique is not "
            "assigned to any objective in the active mapping, an empty list is "
            "returned."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "technique_id": {
                    "type": "string",
                    "description": "The technique ID (e.g. DFT-1001).",
                    "minLength": 1,
                },
            },
            "required": ["technique_id"],
        },
        handler=_handle_obj_for_tech,
    )

    # solveit_list_available_mappings
    async def _handle_list_mappings(arguments: dict[str, Any], context: HandlerContext) -> str:
        await context.log_debug("solveit_list_available_mappings called")
        try:
            mappings = kb.list_available_mappings()
            return json.dumps(mappings)
        except Exception as exc:
            return json.dumps({"error": f"Failed to list mappings: {exc}"})

    server.register_tool(
        name="solveit_list_available_mappings",
        description=(
            "List all available objective mapping files. "
            "Each mapping organises the same techniques into different "
            "investigation frameworks: solve-it.json (default SOLVE-IT "
            "framework), carrier.json (carrier/network context), dfrws.json "
            "(DFRWS framework). "
            "Use solveit_load_objective_mapping to switch between them."
        ),
        known_limitations=(
            "Lists only mapping files present in the SOLVE-IT data directory at "
            "server startup. Custom or third-party mapping files must be placed "
            "in the data directory and the server restarted before they appear here."
        ),
        input_schema={"type": "object", "properties": {}},
        handler=_handle_list_mappings,
    )

    # solveit_load_objective_mapping
    async def _handle_load_mapping(arguments: dict[str, Any], context: HandlerContext) -> str:
        await context.log_debug("solveit_load_objective_mapping called")
        filename = arguments["filename"]
        try:
            success = kb.load_objective_mapping(filename)
            current = getattr(kb, "current_mapping_name", filename)
            if success:
                return json.dumps(
                    {
                        "success": True,
                        "message": f"Successfully loaded mapping: {filename}",
                        "current_mapping": current,
                    }
                )
            return json.dumps(
                {
                    "success": False,
                    "message": f"Failed to load mapping: {filename}",
                    "current_mapping": current,
                }
            )
        except Exception as exc:
            return json.dumps({"error": f"Failed to load mapping: {exc}"})

    server.register_tool(
        name="solveit_load_objective_mapping",
        description=(
            "Switch to a different investigation framework mapping. "
            "Use solveit_list_available_mappings to see valid filenames. "
            "After loading, solveit_list_objectives and "
            "solveit_get_techniques_for_objective will reflect the new "
            "framework. "
            "Use this when the user asks about techniques in the context of a "
            "specific framework (carrier, dfrws)."
        ),
        known_limitations=(
            "The mapping switch affects all subsequent calls to "
            "solveit_list_objectives and solveit_get_techniques_for_objective "
            "in the current session. The change is not persistent across server "
            "restarts — the default mapping (solve-it.json) is reloaded on each "
            "start. Only mappings listed by solveit_list_available_mappings can "
            "be loaded."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "Mapping filename to load "
                        "(e.g. 'carrier.json', 'dfrws.json', 'solve-it.json')."
                    ),
                    "minLength": 1,
                },
            },
            "required": ["filename"],
        },
        handler=_handle_load_mapping,
    )


# ── Search tool ────────────────────────────────────────────────────────

_VALID_SEARCH_LOGIC = {"AND", "OR"}


def _register_search_tool(server: ChassisServer, kb: Any) -> None:
    """Register solveit_search with schema based on [app.search] config."""
    app_cfg = getattr(server, "_app_config", None)
    if app_cfg is not None:
        search_config = {
            "enable_item_types_filter": app_cfg.search.enable_item_types_filter,
            "enable_substring_match": app_cfg.search.enable_substring_match,
            "enable_search_logic": app_cfg.search.enable_search_logic,
        }
    else:
        search_config = server._config.app.get("search", {})

    properties: dict[str, Any] = {
        "keywords": {
            "type": "string",
            "description": (
                "Keywords to search for. Use quotes for exact phrases "
                "(e.g. '\"memory acquisition\"'). Multiple words are combined "
                "using search_logic (AND by default)."
            ),
            "minLength": 1,
        },
    }
    required = ["keywords"]

    if search_config.get("enable_item_types_filter", True):
        properties["item_types"] = {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["techniques", "weaknesses", "mitigations"],
            },
            "description": ("Filter results to specific types. Default: all types are searched."),
        }

    if search_config.get("enable_substring_match", True):
        properties["substring_match"] = {
            "type": "boolean",
            "description": (
                "If true, allow partial word matches. Default: false "
                "(word-boundary matching). Use true for partial-term or "
                "prefix searches."
            ),
        }

    if search_config.get("enable_search_logic", True):
        properties["search_logic"] = {
            "type": "string",
            "enum": ["AND", "OR"],
            "description": (
                "'AND' (default) requires all terms to match — use for precise "
                "queries. 'OR' requires any term to match — use for broader "
                "discovery."
            ),
        }

    async def _handle(arguments: dict[str, Any], context: HandlerContext) -> str:
        await context.log_debug("solveit_search called")
        keywords = arguments["keywords"]
        item_types = arguments.get("item_types")
        substring_match = arguments.get("substring_match", False)
        search_logic = arguments.get("search_logic", "AND")

        if search_logic not in _VALID_SEARCH_LOGIC:
            return json.dumps(
                {
                    "error": (f"Invalid search_logic '{search_logic}'. Must be AND or OR."),
                }
            )

        result = kb.search(
            keywords=keywords,
            item_types=item_types,
            substring_match=substring_match,
            search_logic=search_logic,
        )
        try:
            from mcp_chassis.utils.metrics import get_metrics

            get_metrics().record_search_results(len(result) if isinstance(result, list) else 0)
        except Exception:
            pass
        return json.dumps(result)

    server.register_tool(
        name="solveit_search",
        description=(
            "Search SOLVE-IT by keyword when you don't know the exact ID. "
            "Searches name and description fields across techniques, weaknesses, "
            "and mitigations. Returns matching items sorted by relevance. "
            "Use this as the starting point for discovery — then call "
            "solveit_get_technique, solveit_get_weakness, or "
            "solveit_get_mitigation with the IDs from the results. "
            "Prefer 'AND' logic for precise queries, 'OR' for broader "
            "exploration."
        ),
        known_limitations=(
            "Keyword matching only — semantic similarity and synonym expansion are "
            "not evaluated. A query term must appear verbatim (or as a word "
            "boundary match) in the name or description field to produce a hit. "
            "Acronyms and alternative phrasings not present in the KB text will "
            "not match. Use 'OR' logic or try multiple phrasings to improve recall."
        ),
        input_schema={
            "type": "object",
            "properties": properties,
            "required": required,
        },
        handler=_handle,
    )


# ── Full-detail tools (config-gated, large payloads) ──────────────────

_FULL_DETAIL_WARNING = (
    "WARNING: Returns the complete dataset which may be very large "
    "(~25,000–32,000 tokens). Use the concise listing tool instead "
    "unless you specifically need full detail for all items."
)

_FULL_DETAIL_TOOLS: list[dict[str, str]] = [
    {
        "name": "solveit_list_techniques_full_detail",
        "description": f"List ALL techniques with full detail. {_FULL_DETAIL_WARNING}",
        "method": "get_all_techniques_with_full_detail",
    },
    {
        "name": "solveit_list_weaknesses_full_detail",
        "description": f"List ALL weaknesses with full detail. {_FULL_DETAIL_WARNING}",
        "method": "get_all_weaknesses_with_full_detail",
    },
    {
        "name": "solveit_list_mitigations_full_detail",
        "description": f"List ALL mitigations with full detail. {_FULL_DETAIL_WARNING}",
        "method": "get_all_mitigations_with_full_detail",
    },
]


def _register_full_detail_tools(server: ChassisServer, kb: Any) -> None:
    """Register full-detail listing tools (config-gated)."""
    for defn in _FULL_DETAIL_TOOLS:
        tool_name = defn["name"]
        method = getattr(kb, defn["method"])

        async def _handle(
            arguments: dict[str, Any],
            context: HandlerContext,
            _name: str = tool_name,
            _method: Any = method,
        ) -> str:
            await context.log_debug(f"{_name} called")
            return json.dumps(_method())

        server.register_tool(
            name=tool_name,
            description=defn["description"],
            input_schema={"type": "object", "properties": {}},
            handler=_handle,
        )


# ── Extension info tool ────────────────────────────────────────────────


def _register_extension_info_tool(server: ChassisServer, kb: Any) -> None:
    """Register solveit_list_loaded_extensions."""

    async def _handle(arguments: dict[str, Any], context: HandlerContext) -> str:
        await context.log_debug("solveit_list_loaded_extensions called")
        return json.dumps(kb.list_loaded_extensions())

    server.register_tool(
        name="solveit_list_loaded_extensions",
        description="List all loaded SOLVE-IT-X extensions and their details.",
        known_limitations=(
            "Only extensions loaded at server startup are listed. Extensions "
            "cannot be added or removed at runtime — a server restart is required. "
            "An empty list means the server started with enable_extensions=false "
            "or no extensions were found in the data directory."
        ),
        input_schema={"type": "object", "properties": {}},
        handler=_handle,
    )


# ── Citation tools ─────────────────────────────────────────────────────


def _register_citation_tools(server: ChassisServer, kb: Any) -> None:
    """Register citation lookup, listing, and inline-resolution tools."""

    async def _handle_get(arguments: dict[str, Any], context: HandlerContext) -> str:
        await context.log_debug("solveit_get_citation called")
        citation_id = arguments["citation_id"]
        citation = kb.get_citation(citation_id)
        if citation is None:
            return json.dumps({"error": "not_found", "id": citation_id})
        return json.dumps({**citation, "id": citation_id})

    server.register_tool(
        name="solveit_get_citation",
        description=(
            "Resolve a DFCite-XXXX citation ID to its full bibliographic "
            "reference text. "
            "Technique and weakness responses contain DFCite-XXXX IDs in their "
            "'references' field — call this to get the actual source title, "
            "authors, and publication details. "
            "Use this when a user asks about the evidence or sources behind a "
            "technique or weakness. "
            "Use solveit_resolve_inline_citations to batch-replace multiple "
            "[DFCite-XXXX] markers in text more efficiently."
        ),
        known_limitations=(
            "Returns the citation as stored in the KB (typically BibTeX or a URL). "
            "Completeness and accuracy of citation metadata depend on the KB "
            "authors. Not all referenced works have full bibliographic details — "
            "some entries may contain only a URL or a partial reference."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "citation_id": {
                    "type": "string",
                    "description": "The citation ID (e.g. DFCite-1001).",
                    "minLength": 1,
                },
            },
            "required": ["citation_id"],
        },
        handler=_handle_get,
    )

    async def _handle_list(arguments: dict[str, Any], context: HandlerContext) -> str:
        await context.log_debug("solveit_list_citations called")
        return json.dumps([{"id": cid} for cid in sorted(kb.citations)])

    server.register_tool(
        name="solveit_list_citations",
        description=(
            "List all citation IDs (DFCite-XXXX) in the SOLVE-IT knowledge "
            "base. Use solveit_get_citation to resolve a specific ID to its "
            "full bibliographic text."
        ),
        known_limitations=(
            "Returns IDs only — not titles or authors. Call solveit_get_citation "
            "to resolve individual IDs. Cross-referencing which techniques or "
            "weaknesses use a specific citation requires calling those detail "
            "tools separately."
        ),
        input_schema={"type": "object", "properties": {}},
        handler=_handle_list,
    )

    async def _handle_resolve(arguments: dict[str, Any], context: HandlerContext) -> str:
        await context.log_debug("solveit_resolve_inline_citations called")
        text = arguments["text"]
        try:
            resolved = kb.resolve_inline_citations(text)
            return json.dumps({"resolved_text": resolved})
        except Exception as exc:
            return json.dumps({"error": f"Failed to resolve inline citations: {exc}"})

    server.register_tool(
        name="solveit_resolve_inline_citations",
        description=(
            "Replace [DFCite-XXXX] citation markers in text with full "
            "Harvard-style citations. "
            "Technique and weakness descriptions often contain [DFCite-XXXX] "
            "markers — call this to expand them into readable references in "
            "one step. "
            "More efficient than calling solveit_get_citation for each marker "
            "individually."
        ),
        known_limitations=(
            "Only [DFCite-XXXX] markers with a matching ID in the KB are resolved; "
            "unrecognised markers are left unchanged. The resolved text uses a "
            "short-form parenthetical reference, not a full inline bibliography. "
            "Full bibliographic text is available via solveit_get_citation."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        "Text containing [DFCite-XXXX] citation markers to "
                        "resolve. Each marker is replaced with a Harvard-style "
                        "inline citation."
                    ),
                    "minLength": 1,
                },
            },
            "required": ["text"],
        },
        handler=_handle_resolve,
    )


# ── Entry point ────────────────────────────────────────────────────────


def register(server: ChassisServer) -> None:
    """Register all SOLVE-IT tools.

    Always registers solveit_status. Registers all other tools only
    when the KB loaded successfully (server._kb is not None).

    Args:
        server: The ChassisServer instance with ``_kb`` and ``_kb_error``
            attributes set by the init hook.
    """
    _register_status_tool(server)

    kb = getattr(server, "_kb", None)
    if kb is None:
        logger.warning("SOLVE-IT KB not loaded — only solveit_status registered")
        return

    app_cfg = getattr(server, "_app_config", None)

    # Orientation tool (1)
    _register_database_description_tool(server, kb)

    # Batch-registered tools: detail lookups + concise lists + objectives (8)
    register_simple_tools(server, kb, _BATCH_TOOLS)

    # Relationship tools: forward and reverse (5)
    _register_relationship_tools(server, kb)

    # Cross-traversal shortcut: technique → mitigations (1)
    _register_mitigations_for_technique_tool(server, kb)

    # Objective reverse lookup + mapping switch tools (3)
    _register_objectives_and_mapping_tools(server, kb)

    # Search tool (1, schema configurable via [app.search])
    _register_search_tool(server, kb)

    # Full-detail tools (3, config-gated — large payloads)
    enable_full_detail = (
        app_cfg.enable_full_detail_tools
        if app_cfg is not None
        else server._config.app.get("enable_full_detail_tools", False)
    )
    if enable_full_detail:
        _register_full_detail_tools(server, kb)

    # Extension info tool (1)
    _register_extension_info_tool(server, kb)

    # Citation tools: get, list, resolve inline (3)
    _register_citation_tools(server, kb)
