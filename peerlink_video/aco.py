"""
Ant Colony Optimization–style metrics for worker selection.
Pheromone evaporation + deposit based on speed, frames done, battery.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class WorkerMetrics:
    node_id: str
    capability_score: float = 1.0  # higher = more capable
    battery_level: float = 1.0  # 0..1
    frames_claimed: int = 0
    frames_done: int = 0
    frames_failed: int = 0
    last_speed_fps: float = 0.0
    pheromone: float = 0.5
    last_update: float = field(default_factory=time.time)

    def deposit(self, success: bool, fps: float) -> None:
        """Deposit pheromone on successful path; evaporate on failure."""
        self.last_speed_fps = fps
        self.last_update = time.time()
        if success:
            self.frames_done += 1
            # Stronger deposit for higher fps and capability
            delta = 0.05 + min(0.2, fps * 0.01) * self.capability_score
            self.pheromone = min(1.0, self.pheromone + delta)
        else:
            self.frames_failed += 1
            self.pheromone = max(0.05, self.pheromone * 0.85)

    def evaporate(self, rate: float = 0.02) -> None:
        self.pheromone = max(0.05, self.pheromone * (1.0 - rate))

    def selection_weight(self) -> float:
        """Higher = more likely to receive next frame."""
        bat = 0.2 + 0.8 * self.battery_level
        return self.pheromone * self.capability_score * bat * (1.0 + self.last_speed_fps * 0.05)


def pick_worker(workers: dict[str, WorkerMetrics]) -> str | None:
    if not workers:
        return None
    import random
    items = list(workers.items())
    weights = [w.selection_weight() for _, w in items]
    s = sum(weights)
    if s <= 0:
        return random.choice([k for k, _ in items])
    r = random.random() * s
    acc = 0.0
    for (k, w), wt in zip(items, weights):
        acc += wt
        if r <= acc:
            return k
    return items[-1][0]
