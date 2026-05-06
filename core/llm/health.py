"""
Javris LLM — Provider Health Tracker
──────────────────────────────────────
Tracks per-provider metrics using:

  • EWMA (Exponential Weighted Moving Average) for latency
    — O(1) space, numerically stable, gives recent samples more weight

  • UCB1 (Upper Confidence Bound 1) for routing score
    — Algorithm from multi-armed bandit research
    — Balances exploitation (use fast/reliable providers) with
      exploration (don't abandon a provider just from a few samples)
    — Score = success_rate + C * sqrt(ln(N) / n_i)
      where N = total global trials, n_i = this provider's trials

  • Rolling window error rate (deque[bool], maxlen=20)
    — Stable snapshot of recent reliability

  • P95 latency via reservoir sampling (Vitter's Algorithm R)
    — Memory-bounded percentile estimation without storing all data
"""

from __future__ import annotations

import math
import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import List

# Global trial counter (shared across all providers for UCB1)
_GLOBAL_TRIALS: int = 1   # start at 1 to avoid log(0)


def _increment_global() -> int:
    global _GLOBAL_TRIALS
    _GLOBAL_TRIALS += 1
    return _GLOBAL_TRIALS


# ── Reservoir sampler for P-percentile estimation ─────────────────

class ReservoirSampler:
    """Vitter's Algorithm R — uniform reservoir sampling in O(1) space."""
    def __init__(self, k: int = 100):
        self._k = k
        self._reservoir: List[float] = []
        self._n = 0

    def add(self, value: float) -> None:
        self._n += 1
        if len(self._reservoir) < self._k:
            self._reservoir.append(value)
        else:
            j = random.randint(0, self._n - 1)
            if j < self._k:
                self._reservoir[j] = value

    def percentile(self, p: float) -> float:
        if not self._reservoir:
            return 0.0
        sorted_r = sorted(self._reservoir)
        idx = int(p / 100 * len(sorted_r))
        return sorted_r[min(idx, len(sorted_r) - 1)]


# ── Per-provider health ───────────────────────────────────────────

@dataclass
class ProviderHealth:
    """
    Tracks latency, success rate, and rate-limit state for one LLM provider.

    EWMA parameters:
      alpha = 0.25 → recent 4 samples dominate (fast adaptation)
    """
    name: str
    ewma_alpha: float = 0.25

    # Latency (seconds) — EWMA
    latency_ewma: float     = 1.5     # optimistic initial guess
    latency_min:  float     = math.inf
    latency_max:  float     = 0.0

    # Latency percentiles — reservoir sampler (P50, P95)
    _latency_sampler: ReservoirSampler = field(
        default_factory=lambda: ReservoirSampler(k=200), init=False
    )

    # Error rate — rolling window (True=success)
    _outcomes: deque = field(
        default_factory=lambda: deque(maxlen=20), init=False
    )

    # Rate limiting
    rate_limited_until: float = 0.0

    # UCB1 counters
    _local_trials: int   = field(default=0, init=False)
    _local_success: int  = field(default=0, init=False)

    # Lifetime totals
    total_requests:  int = 0
    total_successes: int = 0
    total_failures:  int = 0
    total_tokens:    int = 0

    # ── Query state ───────────────────────────────────────────────

    @property
    def is_rate_limited(self) -> bool:
        return time.monotonic() < self.rate_limited_until

    @property
    def success_rate(self) -> float:
        if not self._outcomes:
            return 0.8   # optimistic prior
        return sum(self._outcomes) / len(self._outcomes)

    @property
    def error_rate(self) -> float:
        return 1.0 - self.success_rate

    def p50_latency(self) -> float:
        v = self._latency_sampler.percentile(50)
        return v if v > 0 else self.latency_ewma

    def p95_latency(self) -> float:
        v = self._latency_sampler.percentile(95)
        return v if v > 0 else self.latency_ewma * 2

    # ── UCB1 routing score ────────────────────────────────────────

    def ucb1_score(self) -> float:
        """
        UCB1 routing score — higher = prefer this provider.

        Formula:
          score = success_rate / latency_ewma
                + C * sqrt(ln(N) / max(n_i, 1))

        Where:
          success_rate / latency_ewma  = exploitation term
          C * sqrt(...)                = exploration bonus (UCB1)
          N = _GLOBAL_TRIALS           = total requests across all providers
          n_i = _local_trials          = this provider's request count
          C = 0.5                      = exploration weight
        """
        if self.is_rate_limited:
            return 0.0

        exploit = self.success_rate / max(self.latency_ewma, 0.05)

        C = 0.5
        n_i = max(self._local_trials, 1)
        explore = C * math.sqrt(math.log(max(_GLOBAL_TRIALS, 1)) / n_i)

        return exploit + explore

    # ── Recording outcomes ─────────────────────────────────────────

    def record_success(self, latency: float, tokens: int = 0) -> None:
        """Update metrics after a successful call."""
        global _GLOBAL_TRIALS
        _GLOBAL_TRIALS = _increment_global()
        self._local_trials  += 1
        self._local_success += 1

        self._outcomes.append(1)
        self.total_requests  += 1
        self.total_successes += 1
        self.total_tokens    += tokens

        # EWMA latency update
        self.latency_ewma = (
            self.ewma_alpha * latency
            + (1.0 - self.ewma_alpha) * self.latency_ewma
        )
        self.latency_min = min(self.latency_min, latency)
        self.latency_max = max(self.latency_max, latency)
        self._latency_sampler.add(latency)

    def record_failure(self, is_rate_limit: bool = False, retry_after: float = 60.0) -> None:
        """Update metrics after a failure."""
        global _GLOBAL_TRIALS
        _GLOBAL_TRIALS = _increment_global()
        self._local_trials += 1

        self._outcomes.append(0)
        self.total_requests += 1
        self.total_failures += 1

        if is_rate_limit:
            self.rate_limited_until = time.monotonic() + retry_after
            # Penalise latency EWMA heavily so this provider ranks lower
            self.latency_ewma = min(self.latency_ewma * 3, 30.0)

    # ── Serialisation ─────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "name":             self.name,
            "state":            "rate_limited" if self.is_rate_limited else "available",
            "ucb1_score":       round(self.ucb1_score(), 4),
            "success_rate":     round(self.success_rate, 3),
            "latency_ewma_ms":  round(self.latency_ewma * 1000, 1),
            "latency_p50_ms":   round(self.p50_latency() * 1000, 1),
            "latency_p95_ms":   round(self.p95_latency() * 1000, 1),
            "total_requests":   self.total_requests,
            "total_successes":  self.total_successes,
            "total_tokens":     self.total_tokens,
            "rate_limited_until": (
                round(self.rate_limited_until - time.monotonic(), 1)
                if self.is_rate_limited else 0
            ),
        }
