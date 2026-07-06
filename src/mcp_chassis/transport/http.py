"""HTTP/SSE transport implementation for the MCP Chassis server.

Uses the official MCP SDK's StreamableHTTPSessionManager for MCP 2025-11-25
spec-compliant HTTP transport with SSE streaming, session management, and
proper lifecycle handling.

Requires optional dependencies:
    pip install -e ".[http]"
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from mcp_chassis.transport.base import TransportBase

if TYPE_CHECKING:
    from mcp_chassis.server import ChassisServer

logger = logging.getLogger(__name__)

# FSS-0010 §3.1: investigation context travels in _meta._fss (JSON-RPC body).
# Only transport-level headers remain here.
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
            'Install them with: pip install -e ".[http]"\n'
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
        self._uvicorn_server: object | None = (
            None  # uvicorn.Server, typed as object to avoid import  # noqa: E501
        )

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
                logger.warning(
                    "Invalid MCP_PORT value '%s', using default %d", env_port, _DEFAULT_PORT
                )  # noqa: E501
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
            event_store=None,  # No resumability for now; add an event store later
            json_response=False,  # Use SSE streams (spec-compliant)
            stateless=self._stateless,
        )

        @contextlib.asynccontextmanager
        async def lifespan(app: Starlette) -> AsyncIterator[None]:  # type: ignore[type-arg]
            logger.info("Starting MCP HTTP session manager")
            async with session_manager.run():
                logger.info("MCP HTTP server ready: http://%s:%d%s", host, port, self._base_path)
                yield
            logger.info("MCP HTTP session manager stopped")

        async def _extract_fss_headers(request: Request) -> None:
            """Extract transport-level FSS headers from Starlette request.

            FSS-0010 §3.1: investigation context now travels in _meta._fss
            (JSON-RPC body) and is read by server.py via request_ctx.meta.
            Only the replay-prevention timestamp remains as an HTTP header
            (FSS-0003 §7.3).

            Args:
                request: The incoming Starlette request.
            """
            from mcp_chassis.utils.fss_context import fss_request_timestamp

            request_timestamp = request.headers.get(_HEADER_REQUEST_TIMESTAMP)
            if request_timestamp:
                fss_request_timestamp.set(request_timestamp)
            request.state.request_timestamp = request_timestamp

        async def health_check(request: Request) -> JSONResponse:
            """Health check endpoint for Kubernetes liveness probes.

            Args:
                request: The incoming request.

            Returns:
                JSON response with server status.
            """
            await _extract_fss_headers(request)
            return JSONResponse(
                {
                    "status": "ok",
                    "name": server_name,
                    "version": server_version,
                }
            )

        async def readiness_check(request: Request) -> JSONResponse:
            """Readiness check endpoint for Kubernetes readiness probes.

            Args:
                request: The incoming request.

            Returns:
                JSON response with server readiness status.
            """
            await _extract_fss_headers(request)
            return JSONResponse(
                {
                    "status": "ok",
                    "name": server_name,
                    "version": server_version,
                }
            )

        async def fss_jwks(request: Request) -> JSONResponse:
            """Serve the FSS JWKS document (FSS-0005 §6.5).

            Lists the active Ed25519 public key(s) with kid, x, and revocation
            fields. The document is served for the lifetime of the server so
            signed provenance records remain verifiable after container restart.

            Args:
                request: The incoming request.

            Returns:
                JSON response with JWKS document.
            """
            try:
                from mcp_chassis.utils.integrity import build_jwks, load_signing_key

                key = load_signing_key()
                if key is not None:
                    return JSONResponse(build_jwks(key))
            except Exception as exc:
                logger.debug("JWKS generation failed: %s", exc)
            # Return empty JWKS when signing is not configured
            return JSONResponse({"keys": []})

        async def fss_deployment_record(request: Request) -> JSONResponse:
            """Serve the FSS deployment record (FSS-0009 §4).

            Args:
                request: The incoming request.

            Returns:
                JSON response with deployment record.
            """
            from datetime import UTC, datetime
            try:
                from mcp_chassis.utils.integrity import _compute_key_id, load_signing_key
                key = load_signing_key()
            except Exception:
                key = None

            key_kid = ""
            key_type = "ephemeral"
            if key is not None:
                try:
                    key_kid = _compute_key_id(key)
                except Exception:
                    pass
                key_path = (
                    os.environ.get("FSS_SIGNING_KEY_PATH")
                    or os.environ.get("FSS_SIGNING_KEY_B64")
                    or os.environ.get("FSS_KEY_DIR")
                )
                key_type = "provisioned" if key_path else "ephemeral"

            _conf_level = os.environ.get("FSS_CONFORMANCE_LEVEL", "1")
            _spec_ver = os.environ.get("FSS_SPEC_VERSION", "1.0")
            _assessed_under = (
                os.environ.get("FSS_ASSESSED_UNDER")
                or f"FSS-0009v{_spec_ver}L{_conf_level}"
            )
            _fit_issuers_env = os.environ.get("FSS_FIT_TRUSTED_ISSUERS", "")
            record: dict = {
                "fss_schema": "fss-deployment-v1",
                "server_identity": os.environ.get("FSS_SERVER_IDENTITY", server_name),
                "server_profile": os.environ.get("FSS_SERVER_PROFILE", "A"),
                "conformance_level": int(_conf_level),
                "assessed_under": _assessed_under,
                "deployment_date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "deployment_operator": os.environ.get("FSS_DEPLOYMENT_OPERATOR", ""),
                "server_version": server_version,
                "tls_termination": "deployment_layer",
                "tls_minimum_version": "1.3",
                "authentication_mode": "none",
                "replay_prevention": "timestamp",
                "rate_limiting": True,
                "signing_key_kid": key_kid,
                "signing_key_type": key_type,
                "signing_jwks_url": "/.well-known/fss-jwks.json",
                "image_digest": os.environ.get("IMAGE_DIGEST", ""),
                "audit_log_location": "none",
                "audit_log_format": "n/a",
                "security_log_location": os.environ.get("FSS_SECURITY_LOG", "stderr"),
                "retention_policy": {
                    "retention_period": os.environ.get("FSS_RETENTION_PERIOD", "P7Y"),
                    "retention_basis": os.environ.get("FSS_RETENTION_BASIS", "legal_obligation"),
                    "post_closure_pseudonymization": (
                        os.environ.get("FSS_POST_CLOSURE_PSEUDONYMIZATION", "false").lower()
                        == "true"
                    ),
                },
                "fit_issuers": [i.strip() for i in _fit_issuers_env.split(",") if i.strip()],
            }
            return JSONResponse(record)

        async def mcp_handler(scope: object, receive: object, send: object) -> None:
            """MCP endpoint — wraps the session manager to extract FSS headers.

            Args:
                scope: ASGI scope dict.
                receive: ASGI receive callable.
                send: ASGI send callable.
            """
            # Extract transport-level headers from ASGI scope.
            # FSS-0010 §3.1: investigation context is in the JSON-RPC body
            # (_meta._fss), read by server.py via request_ctx.meta.
            if isinstance(scope, dict):
                from mcp_chassis.utils.fss_context import (
                    fss_auth_token,
                    fss_fit_token,
                    fss_investigation_id,
                    fss_request_timestamp,
                    fss_session_id,
                )

                raw_headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
                headers_dict = {k.lower(): v.decode("latin-1") for k, v in raw_headers}

                request_timestamp = headers_dict.get(_HEADER_REQUEST_TIMESTAMP)
                if request_timestamp:
                    fss_request_timestamp.set(request_timestamp)

                auth_header = headers_dict.get("authorization", "")
                if auth_header:
                    has_bearer = auth_header.lower().startswith("bearer ")
                    token = auth_header[7:].strip() if has_bearer else auth_header.strip()
                    fss_auth_token.set(token)

                fit_token = headers_dict.get("x-fit-token", "")
                if fit_token:
                    fss_fit_token.set(fit_token)

                investigation_id = headers_dict.get("x-investigation-id", "")
                if investigation_id:
                    fss_investigation_id.set(investigation_id)

                session_id = headers_dict.get("mcp-session-id", "")
                if not session_id:
                    # Stateless mode: no Mcp-Session-Id issued. Use client
                    # IP:port as a per-connection discriminator so one client's
                    # rate-limit bucket does not bleed into another's.
                    client = scope.get("client") or ("", 0)
                    session_id = f"{client[0]}:{client[1]}"
                fss_session_id.set(session_id)

                scope.setdefault("state", {})  # type: ignore[union-attr]
                scope["state"]["request_timestamp"] = request_timestamp  # type: ignore[index]
                scope["state"]["fit_token"] = fit_token  # type: ignore[index]
                scope["state"]["investigation_id"] = investigation_id  # type: ignore[index]

                # W3C trace context propagation — attach incoming traceparent/tracestate
                # so spans created during this request become children of the caller's trace.
                from mcp_chassis.utils.telemetry import get_telemetry
                _tm = get_telemetry()
                if _tm.enabled:
                    from opentelemetry import context as _otel_ctx
                    from opentelemetry import propagate as _propagate
                    _ctx = _propagate.extract(headers_dict)
                    _token = _otel_ctx.attach(_ctx)
                    try:
                        await session_manager.handle_request(scope, receive, send)
                    finally:
                        _otel_ctx.detach(_token)
                    return

            await session_manager.handle_request(scope, receive, send)

        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import Response as StarletteResponse

        class _BearerTokenMiddleware(BaseHTTPMiddleware):
            """Extract Authorization: Bearer <token> and store in fss_auth_token."""

            async def dispatch(self, request: Request, call_next: object) -> StarletteResponse:
                from mcp_chassis.utils.fss_context import fss_auth_token

                auth = request.headers.get("authorization", "")
                if auth:
                    has_bearer = auth.lower().startswith("bearer ")
                    token = auth[7:].strip() if has_bearer else auth.strip()
                    fss_auth_token.set(token)
                return await call_next(request)  # type: ignore[call-arg]

        middleware = [
            Middleware(
                CORSMiddleware,
                allow_origins=cors_origins,
                allow_methods=["GET", "POST", "OPTIONS"],
                allow_headers=["*"],
                expose_headers=["*"],
            ),
            Middleware(_BearerTokenMiddleware),
        ]

        app = Starlette(
            debug=False,
            routes=[
                Route("/health", health_check, methods=["GET"]),
                Route("/ready", readiness_check, methods=["GET"]),
                # Kubernetes-style aliases
                Route("/healthz", health_check, methods=["GET"]),
                Route("/readyz", readiness_check, methods=["GET"]),
                # FSS JWKS endpoint for public key discovery (FSS-0005 §6.5)
                Route("/.well-known/fss-jwks.json", fss_jwks, methods=["GET"]),
                # FSS deployment record endpoint (FSS-0009 §4)
                Route("/.well-known/fss-deployment.json", fss_deployment_record, methods=["GET"]),
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
        if mcp_transport_env and mcp_transport_env.lower() not in (
            "http",
            "streamable-http",
            "sse",
        ):  # noqa: E501
            logger.warning(
                "MCP_TRANSPORT env var is '%s' but HTTP transport was explicitly selected; "
                "proceeding with HTTP.",
                mcp_transport_env,
            )

        host = self._resolve_host(server)
        port = self._resolve_port(server)

        logger.info("Starting HTTP transport on %s:%d", host, port)
        logger.info("MCP endpoint: http://%s:%d%s", host, port, self._base_path)
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
