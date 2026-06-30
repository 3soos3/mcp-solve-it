"""ChassisServer — the central orchestrator for the MCP Chassis server.

Creates the MCP SDK low-level Server, wires up the middleware pipeline,
registers built-in tools, discovers extensions, and manages the server lifecycle.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from mcp import types
from mcp.server.lowlevel.server import Server as SDKServer
from mcp.server.lowlevel.server import request_ctx

from mcp_chassis.config import ServerConfig
from mcp_chassis.context import HandlerContext
from mcp_chassis.errors import (
    FSS_EXECUTION_FAILED,
    FSS_EXECUTION_INTERRUPTED,
    FSS_INTERNAL_ERROR,
    FSS_PARAM_INVALID,
    FSS_TOOL_UNAVAILABLE,
    ChassisError,
    ExtensionError,
    FSSError,
)
from mcp_chassis.middleware.pipeline import MiddlewarePipeline
from mcp_chassis.utils.fss_context import (
    fss_agent_identity,
    fss_analyst_identity,
    fss_client_identity,
    fss_investigation_id,
    fss_parameters_cai,
    fss_result_cai,
    fss_result_status,
    fss_transaction_id,
)
from mcp_chassis.utils.integrity import compute_json_cai
from mcp_chassis.utils.provenance import build_provenance_record

if TYPE_CHECKING:
    from mcp_chassis.transport.base import TransportBase

logger = logging.getLogger(__name__)

# Type aliases for tool/resource/prompt handlers
ToolHandler = Callable[[dict[str, Any], HandlerContext], Coroutine[Any, Any, Any]]
ResourceHandler = Callable[[str, HandlerContext], Coroutine[Any, Any, str]]
PromptHandler = Callable[[dict[str, Any], HandlerContext], Coroutine[Any, Any, Any]]


class ChassisServer:
    """Central orchestrator for the MCP Chassis server.

    Creates the MCP SDK low-level Server, applies the middleware pipeline
    to all incoming requests, manages tool/resource/prompt registrations,
    and handles extension auto-discovery.

    Args:
        config: The validated server configuration.
    """

    def __init__(self, config: ServerConfig) -> None:
        """Initialize the ChassisServer with validated configuration.

        Args:
            config: Server configuration.
        """
        self._config = config
        self._tools: dict[str, dict[str, Any]] = {}
        self._resources: dict[str, dict[str, Any]] = {}
        self._prompts: dict[str, dict[str, Any]] = {}
        self._transport: TransportBase | None = None
        self._middleware = MiddlewarePipeline(config.security)

        # Run init hook if configured (allows forks to set up shared state
        # like database connections or knowledge base instances before
        # extension discovery runs)
        if config.extensions.init_module:
            self._run_init_hook(config.extensions.init_module)

        # Reject token auth on stdio — there is no mechanism for a caller to
        # present a token over stdio pipes. The OS provides process-level
        # isolation instead. Token auth will be meaningful when HTTP transport
        # is implemented (the token will come from the Authorization header).
        if (
            config.security.auth.enabled
            and config.security.auth.provider == "token"
            and config.server.transport == "stdio"
        ):
            raise ValueError(
                "Token auth is not supported on stdio transport. "
                "Over stdio, the operating system provides process-level isolation. "
                "Token auth will be enforced when HTTP transport is implemented. "
                "To fix: set [security.auth] enabled = false, or use a different transport."
            )

        self._sdk_server = SDKServer(
            config.server.name,
            version=config.server.version,
        )
        self._register_sdk_handlers()

        # Register built-in health check if enabled
        if config.diagnostics.health_check_enabled:
            from mcp_chassis.diagnostics.health import register_health_check

            register_health_check(self)

        # Auto-discover extensions if enabled
        if config.extensions.auto_discover:
            self._discover_extensions()

    def _register_sdk_handlers(self) -> None:
        """Register all SDK decorator-based handlers for MCP protocol methods."""

        # NOTE: list handlers return all registered capabilities without auth
        # filtering. On stdio this is fine (single caller, OS isolation). When
        # HTTP transport is added, these must filter by caller scopes. See
        # docs/SECURITY_BACKLOG.md item 7.

        @self._sdk_server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
        async def handle_list_tools() -> list[types.Tool]:
            tools = []
            for name, info in self._tools.items():
                # Embed FSS manifest fields in inputSchema as x-fss-* extensions
                fss_meta: dict[str, Any] = {
                    "x-fss-tool-version": info.get("tool_version", "0.0.0"),
                    "x-fss-idempotent": info.get("idempotent", False),
                    "x-fss-side-effects": info.get("side_effects", False),
                    "x-fss-deterministic": info.get("deterministic", True),
                    "x-fss-known-limitations": info.get("known_limitations", ""),
                }
                if info.get("deprecated"):
                    fss_meta["x-fss-deprecated"] = True
                    fss_meta["x-fss-deprecated-in"] = info.get("deprecated_in", "")
                    fss_meta["x-fss-removal-in"] = info.get("removal_in", "")
                input_schema = {**info["input_schema"], **fss_meta}
                tools.append(
                    types.Tool(
                        name=name,
                        description=info["description"],
                        inputSchema=input_schema,
                    )
                )
            return tools

        @self._sdk_server.call_tool(validate_input=False)  # type: ignore[untyped-decorator]
        async def handle_call_tool(
            tool_name: str, arguments: dict[str, Any] | None
        ) -> types.CallToolResult:
            return await self._dispatch_tool(tool_name, arguments or {})

        @self._sdk_server.list_resources()  # type: ignore[no-untyped-call, untyped-decorator]
        async def handle_list_resources() -> list[types.Resource]:
            return [
                types.Resource(
                    uri=types.AnyUrl(uri),  # type: ignore[attr-defined]
                    name=info["name"],
                    description=info.get("description"),
                    mimeType=info.get("mime_type"),
                )
                for uri, info in self._resources.items()
            ]

        @self._sdk_server.read_resource()  # type: ignore[no-untyped-call, untyped-decorator]
        async def handle_read_resource(uri: Any) -> list[Any]:
            return await self._dispatch_resource(str(uri))

        @self._sdk_server.list_prompts()  # type: ignore[no-untyped-call, untyped-decorator]
        async def handle_list_prompts() -> list[types.Prompt]:
            return await self._build_prompt_list()

        @self._sdk_server.get_prompt()  # type: ignore[no-untyped-call, untyped-decorator]
        async def handle_get_prompt(
            name: str, arguments: dict[str, str] | None
        ) -> types.GetPromptResult:
            return await self._dispatch_prompt(name, dict(arguments) if arguments else {})

    def _run_init_hook(self, module_name: str) -> None:
        """Import and run the init hook module.

        The module must define an ``on_init(server)`` function that receives
        the ChassisServer instance. Use this to attach shared state (e.g.,
        database connections, knowledge base instances) that extensions can
        access via the server instance.

        Args:
            module_name: Fully qualified Python module name to import.
        """
        import importlib

        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            logger.error("Failed to import init module '%s': %s", module_name, exc)
            return

        on_init = getattr(module, "on_init", None)
        if on_init is None:
            logger.warning("Init module '%s' has no on_init() function", module_name)
            return

        if not callable(on_init):
            logger.warning("Init module '%s' on_init is not callable", module_name)
            return

        try:
            on_init(self)
            logger.info("Init hook '%s' completed", module_name)
        except Exception as exc:
            logger.error("Init hook '%s' raised an error: %s", module_name, exc)

    def _discover_extensions(self) -> None:
        """Auto-discover and register extensions from the extensions package."""
        try:
            from mcp_chassis.extensions import discover_extensions

            discover_extensions(self)
        except ImportError:
            logger.debug("Extensions package not available, skipping auto-discovery")
        except Exception as exc:
            logger.error("Extension discovery failed: %s", exc)

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: ToolHandler,
        *,
        rate_limit_override: dict[str, Any] | None = None,
        auth_scopes: list[str] | None = None,
        allow_overwrite: bool = False,
        # FSS-0002 §5.1 tool manifest fields
        tool_version: str = "0.0.0",
        idempotent: bool = False,
        side_effects: bool = False,
        deterministic: bool = True,
        known_limitations: str = "",
        # FSS-0006 §6.2 deprecation fields
        deprecated: bool = False,
        deprecated_in: str = "",
        removal_in: str = "",
    ) -> None:
        """Register a tool with the server.

        Args:
            name: Unique tool name.
            description: Human-readable description.
            input_schema: JSON schema for tool arguments.
            handler: Async function (arguments, context) -> result.
            rate_limit_override: Optional per-tool rate limit overrides (reserved).
            auth_scopes: Scopes required to call this tool.
            allow_overwrite: If True, silently replace an existing registration.
            tool_version: Semantic version of this tool implementation (FSS-0002 §5.1).
            idempotent: Whether repeated calls with identical params produce identical
                results and have no side effects (FSS-0002 §5.1).
            side_effects: Whether this tool modifies external state (FSS-0002 §5.1).
            deterministic: Whether results are fully determined by inputs (FSS-0002 §5.1).
            known_limitations: Conditions under which the tool may return incomplete or
                misleading results. MUST NOT be empty for production tools (FSS-0002 §5.1).
            deprecated: Whether this tool is deprecated (FSS-0006 §6.2).
            deprecated_in: Version in which this tool was deprecated.
            removal_in: Version in which this tool will be removed.
        """
        if name in self._tools:
            if not allow_overwrite:
                raise ValueError(
                    f"Tool '{name}' is already registered. "
                    "Use allow_overwrite=True to replace it intentionally."
                )
            logger.warning("Overwriting existing tool registration: '%s'", name)

        if deprecated:
            logger.warning(
                "Registering deprecated tool '%s' (deprecated in %s, removal in %s)",
                name,
                deprecated_in or "unknown",
                removal_in or "unknown",
            )

        self._tools[name] = {
            "description": description,
            "input_schema": input_schema,
            "handler": handler,
            "rate_limit_override": rate_limit_override,
            "auth_scopes": auth_scopes or [],
            "tool_version": tool_version,
            "idempotent": idempotent,
            "side_effects": side_effects,
            "deterministic": deterministic,
            "known_limitations": known_limitations,
            "deprecated": deprecated,
            "deprecated_in": deprecated_in,
            "removal_in": removal_in,
        }
        logger.debug("Registered tool '%s'", name)

    def register_resource(
        self,
        uri: str,
        handler: ResourceHandler,
        *,
        name: str | None = None,
        description: str | None = None,
        mime_type: str | None = None,
        auth_scopes: list[str] | None = None,
        allow_overwrite: bool = False,
    ) -> None:
        """Register a resource with the server.

        Args:
            uri: Unique resource URI.
            handler: Async function (uri, context) -> str content.
            name: Optional display name for the resource.
            description: Optional description.
            mime_type: Optional MIME type for the resource content.
            auth_scopes: Scopes required to read this resource.
            allow_overwrite: If True, silently replace an existing registration.
                If False (default), raise ValueError on duplicate URIs.
        """
        if uri in self._resources:
            if not allow_overwrite:
                raise ValueError(
                    f"Resource '{uri}' is already registered. "
                    "Use allow_overwrite=True to replace it intentionally."
                )
            logger.warning("Overwriting existing resource registration: '%s'", uri)
        self._resources[uri] = {
            "name": name or uri,
            "description": description,
            "mime_type": mime_type,
            "handler": handler,
            "auth_scopes": auth_scopes or [],
        }
        logger.debug("Registered resource '%s'", uri)

    def register_prompt(
        self,
        name: str,
        handler: PromptHandler,
        *,
        description: str | None = None,
        arguments: list[dict[str, Any]] | None = None,
        auth_scopes: list[str] | None = None,
        allow_overwrite: bool = False,
    ) -> None:
        """Register a prompt with the server.

        Args:
            name: Unique prompt name.
            handler: Async function (arguments, context) -> list of messages.
            description: Optional prompt description.
            arguments: Optional list of argument definitions.
            auth_scopes: Scopes required to get this prompt.
            allow_overwrite: If True, silently replace an existing registration.
                If False (default), raise ValueError on duplicate names.
        """
        if name in self._prompts:
            if not allow_overwrite:
                raise ValueError(
                    f"Prompt '{name}' is already registered. "
                    "Use allow_overwrite=True to replace it intentionally."
                )
            logger.warning("Overwriting existing prompt registration: '%s'", name)
        self._prompts[name] = {
            "description": description,
            "arguments": arguments or [],
            "handler": handler,
            "auth_scopes": auth_scopes or [],
        }
        logger.debug("Registered prompt '%s'", name)

    def list_tool_names(self) -> list[str]:
        """Return the names of all registered tools.

        Returns:
            List of tool names.
        """
        return list(self._tools.keys())

    def list_resource_uris(self) -> list[str]:
        """Return the URIs of all registered resources.

        Returns:
            List of resource URIs.
        """
        return list(self._resources.keys())

    def list_prompt_names(self) -> list[str]:
        """Return the names of all registered prompts.

        Returns:
            List of prompt names.
        """
        return list(self._prompts.keys())

    def _make_context(self) -> HandlerContext:
        """Build a HandlerContext from the current SDK request context.

        Returns:
            A HandlerContext for extension handlers.
        """
        session = None
        try:
            sdk_ctx = request_ctx.get()
            request_id = str(sdk_ctx.request_id) if sdk_ctx.request_id else str(uuid.uuid4())
            lifespan_state = sdk_ctx.lifespan_context
            session = sdk_ctx.session
        except LookupError:
            request_id = str(uuid.uuid4())
            lifespan_state = None

        return HandlerContext(
            request_id=request_id,
            correlation_id=str(uuid.uuid4()),
            server_config=self._config,
            lifespan_state=lifespan_state,
            _session=session,
        )

    def _make_error_result(self, exc: Exception, correlation_id: str = "") -> types.CallToolResult:
        """Build an error CallToolResult from an exception.

        When detailed_errors is False, only the error code and correlation ID
        are returned — internal details (limits, schema paths) are omitted.

        Args:
            exc: The exception that caused the error.
            correlation_id: Optional correlation ID for log tracing.

        Returns:
            CallToolResult with isError=True and a descriptive message.
        """
        detailed = self._config.security.detailed_errors
        if isinstance(exc, ChassisError):
            cid = exc.correlation_id
            if detailed:
                message = f"{exc.code}: {exc.args[0]} [correlation_id={cid}]"
            else:
                message = f"{exc.code}: Request failed [correlation_id={cid}]"
        else:
            message = "HANDLER_ERROR: Internal server error"
            if correlation_id:
                message += f" [correlation_id={correlation_id}]"
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=message)],
            isError=True,
        )

    async def _dispatch_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> types.CallToolResult:
        """Run middleware pipeline and dispatch to the registered tool handler.

        Implements FSS transaction lifecycle: sets context vars, computes
        CAI digests, invokes handler, embeds _provenance record in response.

        Args:
            tool_name: Name of the tool to call.
            arguments: Raw tool arguments from the client.

        Returns:
            CallToolResult with tool output (including _provenance) or FSS error.
        """
        from mcp_chassis.utils.metrics import get_metrics
        from mcp_chassis.utils.telemetry import get_telemetry

        _metrics_start = get_metrics().record_call_start(tool_name)
        _span = get_telemetry().start_span(
            "mcp.tool.call",
            **{"tool.name": tool_name},
        )

        with _span:
            result = await self._dispatch_tool_inner(tool_name, arguments)

            # Extract FSS error code from the response payload when present
            _fss_code = ""
            try:
                if result.isError and result.content:
                    _payload = json.loads(result.content[0].text)
                    _fss_code = _payload.get("error_code", "FSS_UNKNOWN")
            except Exception:
                if result.isError:
                    _fss_code = "FSS_UNKNOWN"

            try:
                _span.set_attribute("fss.error_code", _fss_code or "none")
                _span.set_attribute(
                    "fss.transaction_id",
                    str(fss_transaction_id.get() or ""),
                )
                _span.set_attribute("kb.version", str(getattr(self, "_kb_version", "") or ""))
            except Exception:
                pass

            get_metrics().record_call_end(
                tool_name,
                _metrics_start,
                fss_error_code=_fss_code,
            )

        return result

    async def _dispatch_tool_inner(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> types.CallToolResult:
        """Inner dispatch — FSS lifecycle, middleware, handler invocation."""
        # ── 1. Initialise FSS transaction context ─────────────────────
        tokens: list[Any] = []  # noqa: F841  kept for compatibility; context cleared in finally
        transaction_id = str(uuid.uuid4())
        fss_transaction_id.set(transaction_id)
        fss_result_status.set("error")  # pessimistic default

        handler_ctx = self._make_context()
        # Use the same UUID as the FSS transaction ID
        handler_ctx = type(handler_ctx)(
            request_id=handler_ctx.request_id,
            correlation_id=transaction_id,
            server_config=handler_ctx.server_config,
            lifespan_state=handler_ctx.lifespan_state,
            _session=handler_ctx._session,
        )

        def _fss_error(code: str, message: str, *, partial: bool = False) -> types.CallToolResult:
            """Build an FSS error response with provenance block.

            Does NOT reset FSS context — the caller's finally block handles that.
            """
            fss_result_status.set("error")
            err = FSSError(
                error_code=code,
                error_message=message,
                transaction_id=transaction_id,
                partial_result=partial,
            )
            try:
                provenance = build_provenance_record(
                    tool_name=tool_name,
                    tool_version=self._tools.get(tool_name, {}).get("tool_version", "0.0.0"),
                    kb_version_id=getattr(self, "_kb_version_id", None),
                    kb_version=getattr(self, "_kb_version", None),
                )
                payload = {**err.to_dict(), "_provenance": provenance}
            except Exception:
                payload = err.to_dict()
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(payload))],
                isError=True,
            )

        # ── 2. Tool existence check ────────────────────────────────────
        if tool_name not in self._tools:
            return _fss_error(
                FSS_TOOL_UNAVAILABLE,
                f"Unknown tool '{tool_name}'",
            )

        tool_info = self._tools[tool_name]
        schema = tool_info["input_schema"]
        required_scopes: list[str] = tool_info.get("auth_scopes", [])
        tool_version: str = tool_info.get("tool_version", "0.0.0")

        # ── 3. Compute parameters_cai (FSS-0005 §3.2) ─────────────────
        try:
            from mcp_chassis.utils.metrics import get_metrics as _gm

            _gm().record_request_size(tool_name, len(json.dumps(arguments).encode()))
        except Exception:
            pass

        try:
            params_cai = compute_json_cai(arguments)
            fss_parameters_cai.set(params_cai)
        except Exception as exc:
            logger.warning("parameters_cai computation failed: %s", exc)

        # ── 4. Middleware pipeline ─────────────────────────────────────
        from mcp_chassis.utils.fss_context import fss_auth_token

        request_context: dict[str, Any] = {
            "client_identity": fss_client_identity.get(),
            "token": fss_auth_token.get(),  # bearer token from HTTP Authorization header
        }

        middleware_result = await self._middleware.process_tool_request(
            tool_name=tool_name,
            arguments=arguments,
            schema=schema,
            request_context=request_context,
            required_scopes=required_scopes,
        )

        if not middleware_result.allowed:
            logger.warning(
                "Middleware blocked '%s': %s [txn=%s]",
                tool_name,
                middleware_result.error_code,
                transaction_id,
            )
            # Map chassis error codes to FSS taxonomy and record OTel block
            code = middleware_result.error_code
            if "AUTH" in code:
                fss_code = "FSS_AUTH_REQUIRED"
                _block_stage = "auth"
            elif "RATE_LIMIT" in code:
                fss_code = FSS_EXECUTION_INTERRUPTED
                _block_stage = "rate_limit"
            elif "REPLAY" in code:
                fss_code = FSS_PARAM_INVALID
                _block_stage = "replay"
            elif "IO_LIMIT" in code or "SIZE" in code:
                fss_code = FSS_PARAM_INVALID
                _block_stage = "io_limit"
            elif "SANIT" in code:
                fss_code = FSS_PARAM_INVALID
                _block_stage = "sanitization"
            else:
                fss_code = FSS_PARAM_INVALID
                _block_stage = "validation"
            try:
                from mcp_chassis.utils.metrics import get_metrics as _gm

                _gm().record_middleware_block(tool_name, _block_stage)
            except Exception:
                pass
            msg = (
                middleware_result.error_message
                if self._config.security.detailed_errors
                else f"Request blocked [correlation_id={transaction_id}]"
            )
            return _fss_error(fss_code, msg)

        sanitized_args = middleware_result.sanitized_arguments or {}

        # ── 5. Invoke the handler ──────────────────────────────────────
        try:
            handler: ToolHandler = tool_info["handler"]
            result = await handler(sanitized_args, handler_ctx)
        except TimeoutError as exc:
            logger.error("Tool '%s' timed out: %s", tool_name, exc)
            return _fss_error(FSS_EXECUTION_INTERRUPTED, "Tool execution timed out")
        except ChassisError as exc:
            logger.error("Tool '%s' raised ChassisError: %s", tool_name, exc)
            return _fss_error(FSS_EXECUTION_FAILED, str(exc.args[0]) if exc.args else "Tool error")
        except Exception as exc:
            logger.error("Tool '%s' raised unhandled error: %s", tool_name, exc)
            return _fss_error(FSS_INTERNAL_ERROR, "Internal server error")

        # ── 6. Compute result_cai and embed provenance ─────────────────
        try:
            if isinstance(result, str):
                try:
                    result_obj = json.loads(result)
                except (json.JSONDecodeError, ValueError):
                    result_obj = result
            else:
                result_obj = result

            result_cai_val = compute_json_cai(
                result_obj if isinstance(result_obj, (dict, list)) else {"_value": result_obj}
            )
            fss_result_cai.set(result_cai_val)
            fss_result_status.set("success")

            provenance = build_provenance_record(
                tool_name=tool_name,
                tool_version=tool_version,
                kb_version_id=getattr(self, "_kb_version_id", None),
                kb_version=getattr(self, "_kb_version", None),
            )

            if isinstance(result_obj, dict):
                result_obj["_provenance"] = provenance
                response_text = json.dumps(result_obj)
            else:
                response_text = json.dumps({"result": result_obj, "_provenance": provenance})

            self._middleware.check_response_size(response_text)

            try:
                from mcp_chassis.utils.metrics import get_metrics as _gm

                _gm().record_response_size(tool_name, len(response_text.encode()))
                _evidentiary = provenance.get("evidentiary_status") == "evidentiary"
                _gm().record_evidentiary(tool_name, evidentiary=_evidentiary)
            except Exception:
                pass

        except ChassisError as exc:
            logger.error("Response check failed for '%s': %s", tool_name, exc)
            return _fss_error(FSS_INTERNAL_ERROR, "Response processing error")
        except (TypeError, ValueError) as exc:
            logger.error("Tool '%s' returned non-serializable result: %s", tool_name, exc)
            return _fss_error(FSS_INTERNAL_ERROR, "Tool result could not be serialized")
        finally:
            # Explicitly reset all FSS context vars to avoid bleeding into
            # the next sequential request on the same asyncio task
            fss_transaction_id.set(None)
            fss_parameters_cai.set(None)
            fss_result_cai.set(None)
            fss_result_status.set(None)
            fss_investigation_id.set(None)
            fss_analyst_identity.set(None)
            fss_agent_identity.set(None)
            fss_client_identity.set(None)

        return types.CallToolResult(
            content=[types.TextContent(type="text", text=response_text)],
            isError=False,
        )

    def _make_middleware_mcp_error(self, middleware_result: Any) -> Exception:
        """Build an McpError from a failed MiddlewareResult, respecting detailed_errors.

        Args:
            middleware_result: The MiddlewareResult with error details.

        Returns:
            McpError with appropriate message verbosity.
        """
        from mcp.shared.exceptions import McpError

        if self._config.security.detailed_errors:
            message = f"{middleware_result.error_code}: {middleware_result.error_message}"
        else:
            message = (
                f"{middleware_result.error_code}: Request failed"
                f" [correlation_id={middleware_result.correlation_id}]"
            )
        return McpError(types.ErrorData(code=types.INVALID_REQUEST, message=message))

    async def _dispatch_resource(self, uri_str: str) -> list[Any]:
        """Run middleware pipeline and dispatch a resource read to the registered handler.

        Args:
            uri_str: The resource URI to read.

        Returns:
            List of ReadResourceContents for the SDK handler.

        Raises:
            McpError: If middleware blocks, the resource is not found, or handler fails.
        """
        from mcp.server.lowlevel.helper_types import ReadResourceContents
        from mcp.shared.exceptions import McpError

        handler_ctx = self._make_context()

        if uri_str not in self._resources:
            raise McpError(
                types.ErrorData(
                    code=types.INVALID_PARAMS,
                    message=f"Unknown resource URI: '{uri_str}'",
                )
            )

        resource_info = self._resources[uri_str]
        required_scopes: list[str] = resource_info.get("auth_scopes", [])

        # Build request context for auth (populated by transport layer for HTTP)
        request_context: dict[str, Any] = {}

        # Run middleware pipeline
        middleware_result = await self._middleware.process_resource_request(
            resource_uri=uri_str,
            request_context=request_context,
            required_scopes=required_scopes,
        )

        if not middleware_result.allowed:
            logger.warning(
                "Middleware blocked resource '%s': %s [correlation_id=%s]",
                uri_str,
                middleware_result.error_code,
                middleware_result.correlation_id,
            )
            raise self._make_middleware_mcp_error(middleware_result)

        handler: ResourceHandler = resource_info["handler"]

        try:
            content_text = await handler(uri_str, handler_ctx)
        except Exception as exc:
            logger.error("Resource handler for '%s' failed: %s", uri_str, exc)
            raise McpError(
                types.ErrorData(
                    code=types.INTERNAL_ERROR,
                    message="Resource handler error: internal server error",
                )
            ) from exc

        # Check response size
        try:
            self._middleware.check_response_size(content_text)
        except ChassisError as exc:
            logger.error("Response size check failed for resource '%s': %s", uri_str, exc)
            if self._config.security.detailed_errors:
                message = f"{exc.code}: {exc}"
            else:
                message = f"{exc.code}: Request failed [correlation_id={exc.correlation_id}]"
            raise McpError(types.ErrorData(code=types.INTERNAL_ERROR, message=message)) from exc

        mime = resource_info.get("mime_type") or "text/plain"
        return [ReadResourceContents(content=content_text, mime_type=mime)]

    async def _build_prompt_list(self) -> list[types.Prompt]:
        """Build the list of registered prompts for list_prompts response.

        Returns:
            List of Prompt objects.
        """
        prompts = []
        for name, info in self._prompts.items():
            arguments = [
                types.PromptArgument(
                    name=arg["name"],
                    description=arg.get("description"),
                    required=arg.get("required", False),
                )
                for arg in info.get("arguments", [])
            ]
            prompts.append(
                types.Prompt(
                    name=name,
                    description=info.get("description"),
                    arguments=arguments if arguments else None,
                )
            )
        return prompts

    async def _dispatch_prompt(
        self,
        prompt_name: str,
        arguments: dict[str, Any],
    ) -> types.GetPromptResult:
        """Run middleware pipeline and dispatch a prompt get to the registered handler.

        Args:
            prompt_name: Name of the prompt.
            arguments: Raw prompt arguments from the client.

        Returns:
            GetPromptResult with prompt messages.

        Raises:
            McpError: If middleware blocks, the prompt is not found, or handler fails.
        """
        from mcp.shared.exceptions import McpError

        handler_ctx = self._make_context()

        if prompt_name not in self._prompts:
            raise McpError(
                types.ErrorData(
                    code=types.INVALID_PARAMS,
                    message=f"Unknown prompt: '{prompt_name}'",
                )
            )

        prompt_info = self._prompts[prompt_name]
        required_scopes: list[str] = prompt_info.get("auth_scopes", [])

        # Build request context for auth (populated by transport layer for HTTP)
        request_context: dict[str, Any] = {}

        # Run middleware pipeline
        middleware_result = await self._middleware.process_prompt_request(
            prompt_name=prompt_name,
            arguments=arguments,
            request_context=request_context,
            required_scopes=required_scopes,
        )

        if not middleware_result.allowed:
            logger.warning(
                "Middleware blocked prompt '%s': %s [correlation_id=%s]",
                prompt_name,
                middleware_result.error_code,
                middleware_result.correlation_id,
            )
            raise self._make_middleware_mcp_error(middleware_result)

        sanitized_args = middleware_result.sanitized_arguments or {}

        handler: PromptHandler = prompt_info["handler"]

        try:
            messages_raw = await handler(sanitized_args, handler_ctx)
            messages = [
                types.PromptMessage(
                    role=msg["role"],
                    content=types.TextContent(type="text", text=msg["content"]),
                )
                for msg in messages_raw
            ]
        except (KeyError, TypeError) as exc:
            logger.error(
                "Prompt handler for '%s' returned malformed messages: %s",
                prompt_name,
                exc,
            )
            raise McpError(
                types.ErrorData(
                    code=types.INTERNAL_ERROR,
                    message="Prompt handler returned malformed messages",
                )
            ) from exc
        except Exception as exc:
            logger.error("Prompt handler for '%s' failed: %s", prompt_name, exc)
            raise McpError(
                types.ErrorData(
                    code=types.INTERNAL_ERROR,
                    message="Prompt handler error: internal server error",
                )
            ) from exc

        # Check response size on the normalized prompt payload
        description = prompt_info.get("description")
        try:
            response_payload = json.dumps(
                {
                    "description": description,
                    "messages": [
                        {"role": msg["role"], "content": {"type": "text", "text": msg["content"]}}
                        for msg in messages_raw
                    ],
                }
            )
            self._middleware.check_response_size(response_payload)
        except ChassisError as exc:
            logger.error("Response size check failed for prompt '%s': %s", prompt_name, exc)
            if self._config.security.detailed_errors:
                message = f"{exc.code}: {exc}"
            else:
                message = f"{exc.code}: Request failed [correlation_id={exc.correlation_id}]"
            raise McpError(types.ErrorData(code=types.INTERNAL_ERROR, message=message)) from exc

        return types.GetPromptResult(
            description=description,
            messages=messages,
        )

    async def run_on_streams(
        self,
        read_stream: Any,
        write_stream: Any,
    ) -> None:
        """Run the server on the given read/write streams.

        This is called by the transport layer after setting up its I/O.

        Args:
            read_stream: Incoming message stream from the transport.
            write_stream: Outgoing message stream to the transport.
        """
        init_options = self._sdk_server.create_initialization_options()
        logger.info(
            "Server '%s' v%s starting",
            self._config.server.name,
            self._config.server.version,
        )
        await self._sdk_server.run(read_stream, write_stream, init_options)

    async def run(self) -> None:
        """Start the server using the configured transport.

        Creates and starts the appropriate transport based on configuration.
        Blocks until the server shuts down.
        """
        transport_name = self._config.server.transport
        logger.info("Starting server with transport: %s", transport_name)

        if transport_name == "stdio":
            from mcp_chassis.transport.stdio import StdioTransport

            self._transport = StdioTransport()
        elif transport_name == "http":
            from mcp_chassis.transport.http import HTTPTransport

            self._transport = HTTPTransport()
        else:
            raise ExtensionError(
                f"Unknown transport: '{transport_name}'. Valid: stdio, http",
                code="UNKNOWN_TRANSPORT",
            )

        await self._transport.start(self)

    async def shutdown(self) -> None:
        """Graceful shutdown of the server.

        Propagates the shutdown request to the active transport, causing
        it to stop accepting input and exit cleanly.
        """
        logger.info("Server shutdown initiated")
        if self._transport is not None:
            await self._transport.shutdown()
