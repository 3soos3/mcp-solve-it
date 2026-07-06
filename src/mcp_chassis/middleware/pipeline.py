"""Security middleware pipeline for the MCP Chassis server.

Chains security checks in a defined order:
  I/O limits → Auth → Rate limit → Sanitize → Validate

Each step either passes through or returns an error result.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from mcp_chassis.config import SecurityConfig
from mcp_chassis.errors import (
    AuthError,
    ChassisError,
    IOLimitError,
    RateLimitError,
    SanitizationError,
    ValidationError,
)
from mcp_chassis.security.auth import AuthProvider, create_auth_provider
from mcp_chassis.security.io_limits import check_request_size, check_response_size
from mcp_chassis.security.rate_limiter import RateLimiter
from mcp_chassis.security.sanitization import sanitize_input
from mcp_chassis.security.validation import ValidationLimits, raise_if_invalid

logger = logging.getLogger(__name__)

# Nonce cache for replay prevention (FSS-0003 §7.3).
# Maps timestamp string → acceptance epoch (float). Asyncio is single-threaded
# so no lock is needed. Entries are evicted in _evict_seen_timestamps.
_seen_timestamps: dict[str, float] = {}


def _evict_seen_timestamps(now_epoch: float, window_seconds: int) -> None:
    cutoff = now_epoch - window_seconds * 2
    for k in [k for k, v in _seen_timestamps.items() if v < cutoff]:
        del _seen_timestamps[k]


@dataclass
class MiddlewareResult:
    """Result from middleware pipeline processing.

    Attributes:
        allowed: Whether the request passed all middleware checks.
        sanitized_arguments: The sanitized arguments (only valid when allowed=True).
        error_code: Machine-readable error code (only when allowed=False).
        error_message: Human-readable error message (only when allowed=False).
        correlation_id: Correlation ID from the error for log tracing.
    """

    allowed: bool
    sanitized_arguments: dict[str, Any] | None = None
    error_code: str = ""
    error_message: str = ""
    correlation_id: str = ""

    @classmethod
    def ok(cls, sanitized_arguments: dict[str, Any]) -> MiddlewareResult:
        """Create a successful middleware result.

        Args:
            sanitized_arguments: The validated and sanitized arguments.

        Returns:
            MiddlewareResult with allowed=True.
        """
        return cls(allowed=True, sanitized_arguments=sanitized_arguments)

    @classmethod
    def error(cls, exc: ChassisError) -> MiddlewareResult:
        """Create an error middleware result from a ChassisError.

        Args:
            exc: The error that caused the failure.

        Returns:
            MiddlewareResult with allowed=False and error details.
        """
        return cls(
            allowed=False,
            error_code=exc.code,
            error_message=str(exc),
            correlation_id=exc.correlation_id,
        )


class MiddlewarePipeline:
    """Chains security middleware checks for tool, resource, and prompt requests.

    Applies checks in order: I/O limits → Auth → Rate limit → Sanitize → Validate.
    Short-circuits on the first failure.

    Args:
        config: Security configuration for all middleware components.
    """

    def __init__(self, config: SecurityConfig) -> None:
        """Initialize all middleware from configuration.

        Args:
            config: Security configuration.
        """
        self._config = config
        self._rate_limiter = RateLimiter(config.rate_limits)
        # Resolve effective auth mode: prefer mode (FSS L2-03), fall back to provider
        auth_mode = (
            config.auth.mode
            if config.auth.mode != "none"
            else (config.auth.provider if config.auth.enabled else "none")
        )
        self._auth_provider: AuthProvider = create_auth_provider(
            auth_mode,
            token=config.auth.token,
            auth_config=config.auth,
        )
        self._validation_limits = ValidationLimits(
            max_string_length=config.input_validation.max_string_length,
            max_array_length=config.input_validation.max_array_length,
            max_object_depth=config.input_validation.max_object_depth,
        )
        self._sanitization_level = config.input_sanitization.level

    async def _run_auth(
        self,
        name: str,
        request_context: dict[str, Any],
        required_scopes: list[str],
    ) -> MiddlewareResult | None:
        """Run authentication and authorization checks.

        Args:
            name: Name of the tool/resource/prompt (for logging and scope check).
            request_context: Request metadata for auth checks.
            required_scopes: Scopes required for access.

        Returns:
            MiddlewareResult.error on failure, or None if auth passes.
        """
        try:
            result = await self._auth_provider.authenticate(request_context)
            if not result.authenticated or result.identity is None:
                raise AuthError(f"Authentication failed: {result.reason}")
            authorized = await self._auth_provider.authorize(result.identity, name, required_scopes)
            if not authorized:
                raise AuthError(f"Authorization failed: lacks required scopes for '{name}'")
            if result.identity.id != "local":
                from mcp_chassis.utils.fss_context import fss_client_identity
                fss_client_identity.set(result.identity.id)
        except AuthError as exc:
            logger.warning("Auth check failed for '%s'", name)
            try:
                from mcp_chassis.utils.metrics import get_metrics

                get_metrics().record_auth_failure(self._auth_provider.__class__.__name__)
            except Exception:
                pass
            return MiddlewareResult.error(exc)
        return None

    async def _run_fit(self, tool_name: str) -> MiddlewareResult | None:
        """Run FIT validation (FSS-0006 §8). Optional at L2, required at L5."""
        import os

        from mcp_chassis.utils.fss_context import (
            fss_client_identity,
            fss_fit_aud,
            fss_fit_issuer,
            fss_fit_jti,
            fss_fit_legal_authority,
            fss_fit_purpose,
            fss_fit_token,
            fss_fit_valid_until,
            fss_investigation_id,
            fss_investigation_id_verified,
            fss_invocation_type,
            fss_tool_authorization_verified,
        )

        fit_token = fss_fit_token.get()
        investigation_id = fss_investigation_id.get()
        fit_enforce = os.environ.get("FSS_FIT_ENFORCE", "false").lower() == "true"

        # L5 enforcement: investigation_id present → FIT required
        if fit_enforce and investigation_id and not fit_token:
            err = AuthError(
                "FIT required for investigation-scoped tool calls", code="FSS_AUTH_DENIED"
            )
            return MiddlewareResult.error(err)

        if not fit_token:
            return None  # No FIT presented — proceed without FIT validation

        # Validate the FIT
        from mcp_chassis.security.fit import FITVerificationError, verify_fit
        client_identity = fss_client_identity.get()
        invocation_type = fss_invocation_type.get() or "agent_supervised"
        server_identity = os.environ.get("FSS_SERVER_IDENTITY", "")

        try:
            claims = await verify_fit(
                token=fit_token,
                tool_name=tool_name,
                investigation_id=investigation_id,
                client_identity=client_identity,
                invocation_type=invocation_type,
                server_identity=server_identity,
            )
        except FITVerificationError as exc:
            logger.warning("FIT verification failed at step %d: %s", exc.step, exc)
            try:
                from mcp_chassis.logging_config import log_security_event
                log_security_event("fit_verification_failed", error_detail=str(exc))
            except Exception:
                pass
            err = AuthError(str(exc), code="FSS_AUTH_DENIED")
            return MiddlewareResult.error(err)

        # Store FIT claims in context vars
        fss_fit_jti.set(claims.jti)
        fss_fit_issuer.set(claims.issuer)
        fss_fit_valid_until.set(claims.valid_until)
        fss_fit_aud.set(claims.aud)
        fss_fit_legal_authority.set(claims.legal_authority)
        fss_fit_purpose.set(claims.purpose)
        fss_investigation_id_verified.set(bool(claims.investigation_id))
        fss_tool_authorization_verified.set(bool(claims.authorized_tools))
        return None

    def _run_rate_limit(self, name: str) -> MiddlewareResult | None:
        """Run rate limit check.

        Args:
            name: Name of the tool/resource/prompt (used as rate limit key).

        Returns:
            MiddlewareResult.error on failure, or None if rate limit passes.
        """
        try:
            rate_result = self._rate_limiter.check(name)
            if not rate_result.allowed:
                raise RateLimitError(rate_result.reason, retry_after=rate_result.retry_after)
        except RateLimitError as exc:
            logger.warning("Rate limit exceeded for '%s'", name)
            return MiddlewareResult.error(exc)
        return None

    def _check_replay(self) -> MiddlewareResult | None:
        """Check X-Request-Timestamp against replay window (FSS-0003 §7.3).

        Rejects requests whose timestamp is outside the configured window OR
        whose timestamp was already seen (nonce deduplication). Only active
        for HTTP transport (where the header is available). Stdio passes.

        Returns:
            MiddlewareResult.error if rejected, None if allowed.
        """
        import datetime

        from mcp_chassis.errors import FSS_REPLAY_REJECTED
        from mcp_chassis.utils.fss_context import fss_request_timestamp

        if self._config.replay_window_seconds <= 0:
            return None

        timestamp_str = fss_request_timestamp.get()
        if not timestamp_str:
            return None  # No header present — stdio or client didn't send it

        reason: str | None = None
        try:
            request_time = datetime.datetime.fromisoformat(timestamp_str)
            if request_time.tzinfo is None:
                request_time = request_time.replace(tzinfo=datetime.UTC)
            now = datetime.datetime.now(datetime.UTC)
            delta = abs((now - request_time).total_seconds())
            if delta > self._config.replay_window_seconds:
                reason = (
                    f"Request timestamp outside replay window "
                    f"({delta:.0f}s > {self._config.replay_window_seconds}s)"
                )
            elif timestamp_str in _seen_timestamps:
                reason = f"Duplicate X-Request-Timestamp — replay detected ({timestamp_str!r})"
            else:
                # Accept: record timestamp in nonce cache and evict old entries
                _seen_timestamps[timestamp_str] = now.timestamp()
                _evict_seen_timestamps(now.timestamp(), self._config.replay_window_seconds)
        except (ValueError, TypeError) as exc:
            logger.warning("Invalid X-Request-Timestamp '%s': %s", timestamp_str, exc)
            return None

        if reason is None:
            return None

        err = RateLimitError(reason, code=FSS_REPLAY_REJECTED)
        try:
            from mcp_chassis.logging_config import log_security_event

            log_security_event("replay_rejected", error_detail=reason)
        except Exception:
            pass
        try:
            from mcp_chassis.utils.metrics import get_metrics

            get_metrics().record_replay_rejection()
        except Exception:
            pass
        return MiddlewareResult.error(err)

    async def process_tool_request(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        schema: dict[str, Any],
        request_context: dict[str, Any],
        required_scopes: list[str] | None = None,
    ) -> MiddlewareResult:
        """Run all middleware checks on an incoming tool call.

        Order: Replay → I/O limits → Auth → Rate limit → Sanitize → Validate.

        Args:
            tool_name: Name of the tool being invoked.
            arguments: Raw tool arguments from the client.
            schema: JSON schema for the tool's input.
            request_context: Request metadata for auth checks.
            required_scopes: Scopes required for this tool (empty = no scope requirement).

        Returns:
            MiddlewareResult with sanitized args or error details.
        """
        # Step 0: Replay prevention (HTTP only, skipped if no timestamp header)
        if err := self._check_replay():
            return err

        # Step 1: I/O limit check on serialized arguments
        try:
            serialized = json.dumps(arguments)
            check_request_size(serialized, self._config.io_limits.max_request_size)
        except IOLimitError as exc:
            logger.warning("I/O limit check failed for tool '%s'", tool_name)
            return MiddlewareResult.error(exc)

        # Step 2: Auth check
        if err := await self._run_auth(tool_name, request_context, required_scopes or []):
            return err

        # Step 2.5: FIT validation (L5; RECOMMENDED at L2)
        if err := await self._run_fit(tool_name):
            return err

        # Step 3: Rate limit check
        if err := self._run_rate_limit(tool_name):
            return err

        # Step 4: Input sanitization (before validation so validators see clean data)
        sanitized: dict[str, Any] = arguments
        if self._config.input_sanitization.enabled:
            try:
                sanitized = sanitize_input(
                    arguments,
                    self._sanitization_level,
                )
            except SanitizationError as exc:
                logger.warning("Sanitization failed for tool '%s'", tool_name)
                return MiddlewareResult.error(exc)

        # Step 5: Input validation (operates on sanitized data)
        if self._config.input_validation.enabled:
            try:
                raise_if_invalid(sanitized, schema, self._validation_limits)
            except ValidationError as exc:
                logger.warning("Validation failed for tool '%s'", tool_name)
                return MiddlewareResult.error(exc)

        return MiddlewareResult.ok(sanitized)

    async def process_resource_request(
        self,
        resource_uri: str,
        request_context: dict[str, Any],
        required_scopes: list[str] | None = None,
    ) -> MiddlewareResult:
        """Run middleware checks on an incoming resource read.

        Order: Auth → Rate limit.
        Resources have no arguments payload, so I/O limits, sanitization,
        and validation are skipped on the request side. Response size is
        checked separately after the handler returns.

        Args:
            resource_uri: URI of the resource being read.
            request_context: Request metadata for auth checks.
            required_scopes: Scopes required for this resource.

        Returns:
            MiddlewareResult indicating whether the request is allowed.
        """
        # Step 1: Auth check
        if err := await self._run_auth(resource_uri, request_context, required_scopes or []):
            return err

        # Step 2: Rate limit check
        if err := self._run_rate_limit(resource_uri):
            return err

        return MiddlewareResult.ok({})

    async def process_prompt_request(
        self,
        prompt_name: str,
        arguments: dict[str, Any],
        request_context: dict[str, Any],
        required_scopes: list[str] | None = None,
    ) -> MiddlewareResult:
        """Run middleware checks on an incoming prompt get.

        Order: I/O limits → Auth → Rate limit → Sanitize.
        Prompts don't have JSON schemas, so validation is skipped.

        Args:
            prompt_name: Name of the prompt being requested.
            arguments: Raw prompt arguments from the client.
            request_context: Request metadata for auth checks.
            required_scopes: Scopes required for this prompt.

        Returns:
            MiddlewareResult with sanitized args or error details.
        """
        # Step 1: I/O limit check on serialized arguments
        try:
            serialized = json.dumps(arguments)
            check_request_size(serialized, self._config.io_limits.max_request_size)
        except IOLimitError as exc:
            logger.warning("I/O limit check failed for prompt '%s'", prompt_name)
            return MiddlewareResult.error(exc)

        # Step 2: Auth check
        if err := await self._run_auth(prompt_name, request_context, required_scopes or []):
            return err

        # Step 3: Rate limit check
        if err := self._run_rate_limit(prompt_name):
            return err

        # Step 4: Input sanitization
        sanitized: dict[str, Any] = arguments
        if self._config.input_sanitization.enabled:
            try:
                sanitized = sanitize_input(arguments, self._sanitization_level)
            except SanitizationError as exc:
                logger.warning("Sanitization failed for prompt '%s'", prompt_name)
                return MiddlewareResult.error(exc)

        return MiddlewareResult.ok(sanitized)

    def check_response_size(self, response_data: str) -> None:
        """Check response payload size against the configured limit.

        Args:
            response_data: Serialized response string.

        Raises:
            IOLimitError: If the response exceeds the configured max size.
        """
        check_response_size(response_data, self._config.io_limits.max_response_size)
