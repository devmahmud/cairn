"""Cost/abuse controls: rate limiting + concurrency cap (BLUEPRINT.md §3.10, §3.13).

Off/generous by default for local dev; wired (not dormant) into
`modules/chat/router.py` (`rate_limit.py`) and
`modules/chat/chat_stream.py` (`concurrency.py`). The per-turn wall-clock
budget (`TURN_BUDGET_SECONDS`) and the graph-hop cap (`MAX_GRAPH_HOPS`)
live with the agent runtime instead (`agents/chat/agent.py`,
`agents/chat/nodes/tool.py`) -- both predate this module (§8 step 5) and
aren't duplicated here.
"""

from __future__ import annotations
