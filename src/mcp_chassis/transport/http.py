"""HTTP/SSE transport implementation for the MCP Chassis server.

Uses the official MCP SDK's StreamableHTTPSessionManager for MCP 2025-11-25
spec-compliant HTTP transport with SSE streaming, session management, and
proper lifecycle handling.

Requires optional dependencies:
    pip install -e ".[http]"
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
import contextlib
from typing import TYPE_CHECKING

from mcp_chassis.transport.base import TransportBase

if TYPE_CHECKING:
    from mcp_chassis.server import ChassisServer

logger = logging.getLogger(__name__)

# FSS investigation context headers (FSS-0002 §4.2–4.3)
_HEADER_INVESTIGATION_ID = "x-investigation-id"
_HEADER_ANALYST_IDENTITY = "x-analyst-identity"
_HEADER_AGENT_IDENTITY = "x-agent-identity"
# Replay prevention header (FSS-0003 §7.3)
_HEADER_REQUEST_TIMESTAMP = "x-request-timestamp"

_DEFAULT_HOST = "0.0.0.0"
_DEFAULT_PORT = 8080
_DEFAULT_BASE_PATH = "/mcp"


def _check_http_deps() -> None:
    """Verify that HTTP optional dependencies are installed.

    Raises:
        ImportError: If starlette or uvicorn are not available.
    """
    missing = []
    try:
        import starlette  # noqa: F401
    except ImportError:
        missing.append("starlette>=0.37.0")
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        missing.append("uvicorn[standard]>=0.27.0")

    if missing:
        raise ImportError(
            "HTTP transport requires additional dependencies. "
            "Install them with: pip install -e \".[http]\"\n"
            f"Missing: {', '.join(missing)}"
        )


class HTTPTransport(TransportBase):
    """HTTP/SSE transport using the MCP SDK's StreamableHTTPSessionManager.

    Serves MCP requests over HTTP with full SSE streaming support. Reads
    host/port from the server's config if available, falling back to defaults
    or environment variable overrides.

    CORS origins are configurable via the MCP_CORS_ORIGINS environment variable
    (comma-separated list). Defaults to ["*"].

    Custom FSS headers (X-Investigation-ID, X-Analyst-Identity, X-Agent-Identity)
    are extracted from each request and stored in Starlette request state for
    future wiring to context variables.

    Args:
        host: Override bind address. Defaults to MCP_HOST env var or "0.0.0.0".
        port: Override bind port. Defaults to MCP_PORT env var or 8080.
        base_path: MCP endpoint path prefix. Defaults to "/mcp".
        stateless: Run in stateless mode (no session affinity). Defaults to True.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        base_path: str = _DEFAULT_BASE_PATH,
        stateless: bool = True,
    ) -> None:
        """Initialise the HTTPTransport.

        Args:
            host: Optional bind address override.
            port: Optional bind port override.
            base_path: MCP endpoint path prefix.
            stateless: Whether to run in stateless mode.
        """
        self._host_override = host
        self._port_override = port
        self._base_path = base_path
        self._stateless = stateless
        self._uvicorn_server: object | None = None  # uvicorn.Server, typed as object to avoid import

    def _resolve_host(self, server: ChassisServer) -> str:
        """Resolve the bind address in priority order.

        Priority: constructor override > MCP_HOST env var > server config > default.

        Args:
            server: The ChassisServer instance (for config access).

        Returns:
            Resolved host string.
        """
        if self._host_override is not None:
            return self._host_override
        env_host = os.environ.get("MCP_HOST")
        if env_host:
            return env_host
        # ServerConfig does not have an HTTP-specific host field yet; use default.
        return _DEFAULT_HOST

    def _resolve_port(self, server: ChassisServer) -> int:
        """Resolve the bind port in priority order.

        Priority: constructor override > MCP_PORT env var > server config > default.

        Args:
            server: The ChassisServer instance (for config access).

        Returns:
            Resolved port integer.
        """
        if self._port_override is not None:
            return self._port_override
        env_port = os.environ.get("MCP_PORT")
        if env_port:
            try:
                return int(env_port)
            except ValueError:
                logger.warning("Invalid MCP_PORT value '%s', using default %d", env_port, _DEFAULT_PORT)
        return _DEFAULT_PORT

    def _resolve_cors_origins(self) -> list[str]:
        """Resolve allowed CORS origins from environment or default.

        Returns:
            List of allowed origin strings.
        """
        env_origins = os.environ.get("MCP_CORS_ORIGINS")
        if env_origins:
            origins = [o.strip() for o in env_origins.split(",") if o.strip()]
            if origins:
                return origins
        return ["*"]

    def _build_app(self, server: ChassisServer, host: str, port: int) -> object:
        """Construct the Starlette ASGI application.

        Args:
            server: The ChassisServer instance.
            host: Resolved bind address (used in log messages).
            port: Resolved bind port (used in log messages).

        Returns:
            Starlette ASGI application.
        """
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.applications import Starlette
        from starlette.middleware import Middleware
        from starlette.middleware.cors import CORSMiddleware
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Mount, Route

        server_name = server._config.server.name
        server_version = server._config.server.version
        cors_origins = self._resolve_cors_origins()

        # Session manager wraps the SDK low-level server
        session_manager = StreamableHTTPSessionManager(
            app=server._sdk_server,
            event_store=None,   # No resumability for now; add an event store later
            json_response=False,  # Use SSE streams (spec-compliant)
            stateless=self._stateless,
        )

        @contextlib.asynccontextmanager
        async def lifespan(app: Starlette) -> AsyncIterator[None]:  # type: ignore[type-arg]
            logger.info("Starting MCP HTTP session manager")
            async with session_manager.run():
                logger.info(
                    "MCP HTTP server ready: http://%s:%d%s", host, port, self._base_path
                )
                yield
            logger.info("MCP HTTP session manager stopped")

        async def _extract_fss_headers(request: Request) -> None:
            """Extract FSS context headers, set context vars, store in request state.

            Args:
                request: The incoming Starlette request.
            """
            from mcp_chassis.utils.fss_context import (
                fss_investigation_id,
                fss_analyst_identity,
                fss_agent_identity,
                fss_request_timestamp,
            )

            investigation_id = request.headers.get(_HEADER_INVESTIGATION_ID)
            analyst_identity = request.headers.get(_HEADER_ANALYST_IDENTITY)
            agent_identity = request.headers.get(_HEADER_AGENT_IDENTITY)
            request_timestamp = request.headers.get(_HEADER_REQUEST_TIMESTAMP)

            # Set FSS context vars so _dispatch_tool and middleware can read them
            if investigation_id:
                fss_investigation_id.set(investigation_id)
            if analyst_identity:
                fss_analyst_identity.set(analyst_identity)
            if agent_identity:
                fss_agent_identity.set(agent_identity)
            if request_timestamp:
                fss_request_timestamp.set(request_timestamp)

            request.state.investigation_id = investigation_id
            request.state.analyst_identity = analyst_identity
            request.state.agent_identity = agent_identity
            request.state.request_timestamp = request_timestamp

            if investigation_id or analyst_identity or agent_identity:
                logger.debug(
                    "FSS headers: investigation_id=%s analyst_identity=%s agent_identity=%s",
                    investigation_id,
                    analyst_identity,
                    agent_identity,
                )

        async def health_check(request: Request) -> JSONResponse:
            """Health check endpoint for Kubernetes liveness probes.

            Args:
                request: The incoming request.

            Returns:
                JSON response with server status.
            """
            await _extract_fss_headers(request)
            return JSONResponse({
                "status": "ok",
                "name": server_name,
                "version": server_version,
            })

        async def readiness_check(request: Request) -> JSONResponse:
            """Readiness check endpoint for Kubernetes readiness probes.

            Args:
                request: The incoming request.

            Returns:
                JSON response with server readiness status.
            """
            await _extract_fss_headers(request)
            return JSONResponse({
                "status": "ok",
                "name": server_name,
                "version": server_version,
            })

        async def mcp_handler(scope: object, receive: object, send: object) -> None:
            """MCP endpoint — wraps the session manager to extract FSS headers.

            Args:
                scope: ASGI scope dict.
                receive: ASGI receive callable.
                send: ASGI send callable.
            """
            # Extract FSS headers from ASGI scope and set context vars
            if isinstance(scope, dict):
                from mcp_chassis.utils.fss_context import (
                    fss_investigation_id,
                    fss_analyst_identity,
                    fss_agent_identity,
                    fss_request_timestamp,
                )

                raw_headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
                headers_dict = {k.lower(): v.decode("latin-1") for k, v in raw_headers}
                investigation_id = headers_dict.get(_HEADER_INVESTIGATION_ID)
                analyst_identity = headers_dict.get(_HEADER_ANALYST_IDENTITY)
                agent_identity = headers_dict.get(_HEADER_AGENT_IDENTITY)
                request_timestamp = headers_dict.get(_HEADER_REQUEST_TIMESTAMP)

                if investigation_id:
                    fss_investigation_id.set(investigation_id)
                if analyst_identity:
                    fss_analyst_identity.set(analyst_identity)
                if agent_identity:
                    fss_agent_identity.set(agent_identity)
                if request_timestamp:
                    fss_request_timestamp.set(request_timestamp)

                if investigation_id or analyst_identity or agent_identity:
                    logger.debug(
                        "FSS headers on MCP request: investigation_id=%s "
                        "analyst_identity=%s agent_identity=%s",
                        investigation_id,
                        analyst_identity,
                        agent_identity,
                    )
                scope.setdefault("state", {})  # type: ignore[union-attr]
                scope["state"]["investigation_id"] = investigation_id  # type: ignore[index]
                scope["state"]["analyst_identity"] = analyst_identity  # type: ignore[index]
                scope["state"]["agent_identity"] = agent_identity  # type: ignore[index]
                scope["state"]["request_timestamp"] = request_timestamp  # type: ignore[index]

            await session_manager.handle_request(scope, receive, send)

        middleware = [
            Middleware(
                CORSMiddleware,
                allow_origins=cors_origins,
                allow_methods=["GET", "POST", "OPTIONS"],
                allow_headers=["*"],
                expose_headers=["*"],
            )
        ]

        app = Starlette(
            debug=False,
            routes=[
                Route("/health", health_check, methods=["GET"]),
                Route("/ready", readiness_check, methods=["GET"]),
                # Kubernetes-style aliases
                Route("/healthz", health_check, methods=["GET"]),
                Route("/readyz", readiness_check, methods=["GET"]),
                # MCP streamable-HTTP endpoint; the SDK handles GET and POST
                Mount(self._base_path, app=mcp_handler),
            ],
            middleware=middleware,
            lifespan=lifespan,
        )

        logger.info(
            "MCP HTTP app created: base_path=%s, stateless=%s, cors_origins=%s",
            self._base_path,
            self._stateless,
            cors_origins,
        )
        return app

    async def start(self, server: ChassisServer) -> None:
        """Start the HTTP server and block until shutdown.

        Checks for the MCP_TRANSPORT environment variable for compatibility,
        builds the Starlette app, and runs it under Uvicorn.

        Args:
            server: The ChassisServer instance to serve requests for.

        Raises:
            ImportError: If starlette or uvicorn are not installed.
        """
        _check_http_deps()

        import uvicorn

        # Compatibility: honour MCP_TRANSPORT env var if set, but we are already
        # in the HTTP transport so just log it rather than re-routing.
        mcp_transport_env = os.environ.get("MCP_TRANSPORT")
        if mcp_transport_env and mcp_transport_env.lower() not in ("http", "streamable-http", "sse"):
            logger.warning(
                "MCP_TRANSPORT env var is '%s' but HTTP transport was explicitly selected; "
                "proceeding with HTTP.",
                mcp_transport_env,
            )

        host = self._resolve_host(server)
        port = self._resolve_port(server)

        logger.info("Starting HTTP transport on %s:%d", host, port)
        logger.info(
            "MCP endpoint: http://%s:%d%s", host, port, self._base_path
        )
        logger.info("Health check: http://%s:%d/health", host, port)

        app = self._build_app(server, host, port)

        uvicorn_config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="info",
        )
        self._uvicorn_server = uvicorn.Server(uvicorn_config)
        await self._uvicorn_server.serve()  # type: ignore[union-attr]

    async def shutdown(self) -> None:
        """Gracefully shut down the HTTP server.

        Signals Uvicorn to stop accepting new connections and drain
        in-progress requests before exiting.
        """
        logger.info("HTTP transport shutdown requested")
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True  # type: ignore[union-attr]
