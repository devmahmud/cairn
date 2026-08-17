"""Per-role model config (BLUEPRINT.md §3.6, §8 step 5).

Different graph nodes want different model behavior for the same underlying
provider: `classify` wants a fast, deterministic (temperature 0), short-
timeout call; `answer`/`rag` want a more conversational temperature and a
longer timeout to allow for a full generation. `agents/llm.py`'s `get_llm()`
is the one place that turns a `role` string into a concrete `ChatOpenAI` --
this module is just the lookup table it reads.

Deliberately not exposed as per-role `.env` knobs (`CLASSIFY_MODEL=...`
etc.) -- `OPENAI_MODEL` is the one model identity this template asks a
deployer to configure (matching `core/config.py`'s `Settings`); the roles
below vary temperature/timeout on top of that single model, not the model
name itself. A client that genuinely wants a cheaper/faster model for
`classify` and a stronger one for `answer` can override `_ROLE_CONFIGS`
below in their fork -- that's exactly the kind of code-level divergence
`client.config.yaml` (§3.14) doesn't cover and isn't meant to.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.config import settings


@dataclass(frozen=True, slots=True)
class RoleConfig:
    model: str
    temperature: float
    timeout: float


# Every role shares `settings.OPENAI_MODEL` today (see the module docstring
# for why) but temperature/timeout are tuned per role:
# - `classify` -- deterministic, forced-tool-call, cheap-and-fast. A tight
#   timeout because a slow classify shouldn't stall the whole turn -- the
#   fallback ladder (§3.6, `agents/chat/nodes/classify.py`) degrades to
#   `unclear` on any failure, including a timeout.
# - `answer` / `rag` -- a little generation temperature, a longer timeout
#   (full-response generation, possibly with retrieved context).
# - `tool` -- deterministic tool-selection, a mid-length timeout that also
#   has to cover the bound tools' own execution time within the same node
#   (`agents/chat/nodes/tool.py`'s bounded loop).
_ROLE_CONFIGS: dict[str, RoleConfig] = {
    "classify": RoleConfig(model=settings.OPENAI_MODEL, temperature=0.0, timeout=8.0),
    "answer": RoleConfig(model=settings.OPENAI_MODEL, temperature=0.3, timeout=30.0),
    "rag": RoleConfig(model=settings.OPENAI_MODEL, temperature=0.2, timeout=30.0),
    "tool": RoleConfig(model=settings.OPENAI_MODEL, temperature=0.0, timeout=20.0),
}


def role_config(role: str) -> RoleConfig:
    try:
        return _ROLE_CONFIGS[role]
    except KeyError:
        raise ValueError(
            f"Unknown agent role {role!r}. Known roles: {sorted(_ROLE_CONFIGS)}."
        ) from None
