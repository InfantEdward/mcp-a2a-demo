from __future__ import annotations

from dataclasses import dataclass, asdict
from threading import Lock
from typing import Dict


@dataclass
class TokenCounters:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0


class TokenTracker:
    def __init__(self):
        self._lock = Lock()
        self._by_agent: Dict[str, TokenCounters] = {}

    def record(
        self,
        agent: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
    ) -> None:
        with self._lock:
            counters = self._by_agent.setdefault(agent, TokenCounters())
            counters.input_tokens += max(0, int(input_tokens))
            counters.output_tokens += max(0, int(output_tokens))
            counters.total_tokens += max(0, int(total_tokens))
            counters.calls += 1

    def snapshot(self) -> dict:
        with self._lock:
            by_agent = {agent: asdict(counters) for agent, counters in self._by_agent.items()}
            overall = TokenCounters()
            for counters in self._by_agent.values():
                overall.input_tokens += counters.input_tokens
                overall.output_tokens += counters.output_tokens
                overall.total_tokens += counters.total_tokens
                overall.calls += counters.calls
            return {"agents": by_agent, "overall": asdict(overall)}

    def merge_snapshot(self, snapshot: dict) -> None:
        """
        Merge absolute per-agent counters from another process snapshot.
        This overwrites counters for those agent keys with the received totals.
        """
        agents = snapshot.get("agents", {}) if isinstance(snapshot, dict) else {}
        if not isinstance(agents, dict):
            return

        with self._lock:
            for agent, counters in agents.items():
                if not isinstance(counters, dict):
                    continue
                self._by_agent[agent] = TokenCounters(
                    input_tokens=max(0, int(counters.get("input_tokens", 0) or 0)),
                    output_tokens=max(0, int(counters.get("output_tokens", 0) or 0)),
                    total_tokens=max(0, int(counters.get("total_tokens", 0) or 0)),
                    calls=max(0, int(counters.get("calls", 0) or 0)),
                )


token_tracker = TokenTracker()
