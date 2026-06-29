"""Image configuration dataclasses for the three solve-it-mcp image variants.

Each ImageConfig captures everything the test suite needs to know about a
variant: its expected env vars, whether the KB is bundled or mounted, exact
counts (for pinned releases), and minimum thresholds (for rolling builds).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── Volume / env shorthands ───────────────────────────────────────────────────

SOLVEIT_VOL = "SOLVE_IT_DATA_PATH:/tmp/app-cache/solve-it:ro,Z"
FAST_FAIL = "SOLVE_IT_DATA_URL=http://0.0.0.0/fail"
DEGRADED = "MCP_APP_INIT_REQUIRED=false"


@dataclass(frozen=True)
class ImageConfig:
    """All test-relevant facts about one image variant.

    Attributes:
        tag:              Short label used as pytest ID ("live", "monthly", "version").
        image:            Default podman image name (overridable via CLI).
        mode:             Expected value of SOLVE_IT_MODE env var inside the container.
        forensic:         Expected FORENSIC_METADATA value ("true" / "false").
        has_bundled_kb:   True when the KB is baked into the image (no volume needed).
        expected_version: Exact SOLVE_IT_VERSION string, or None for rolling builds.
        exact_counts:     Pinned KB counts (techniques/weaknesses/mitigations), or None.
        min_counts:       Minimum acceptable counts for >= threshold checks.
        default_volumes:  Volume mounts applied by default when creating a client.
        default_extra_env: Extra env vars applied by default (e.g. FAST_FAIL for :live).
    """

    tag: str
    image: str
    mode: str
    forensic: bool
    has_bundled_kb: bool
    expected_version: str | None
    exact_counts: dict[str, int] | None
    min_counts: dict[str, int]
    default_volumes: tuple[str, ...] = field(default_factory=tuple)
    default_extra_env: tuple[str, ...] = field(default_factory=tuple)


LIVE = ImageConfig(
    tag="live",
    image="solve-it-mcp:live",
    mode="live",
    forensic=False,
    has_bundled_kb=False,
    expected_version=None,
    exact_counts=None,
    min_counts={"techniques": 100, "weaknesses": 100, "mitigations": 100},
    default_volumes=(SOLVEIT_VOL,),
    default_extra_env=(FAST_FAIL,),
)

MONTHLY = ImageConfig(
    tag="monthly",
    image="solve-it-mcp:monthly",
    mode="monthly",
    forensic=False,
    has_bundled_kb=True,
    expected_version=None,  # SHA label verified separately
    exact_counts=None,
    min_counts={"techniques": 150, "weaknesses": 200, "mitigations": 100},
)

VERSION = ImageConfig(
    tag="version",
    image="solve-it-mcp:version",
    mode="release",
    forensic=True,
    has_bundled_kb=True,
    expected_version="v0.2026-06",
    exact_counts={"techniques": 182, "weaknesses": 307, "mitigations": 257},
    min_counts={"techniques": 182, "weaknesses": 307, "mitigations": 257},
)

ALL: list[ImageConfig] = [LIVE, MONTHLY, VERSION]
BUNDLED: list[ImageConfig] = [MONTHLY, VERSION]
BY_TAG: dict[str, ImageConfig] = {c.tag: c for c in ALL}
