"""Maps source (raw clip) time to edit time for a list of kept ranges."""
from dataclasses import dataclass

FPS = 30000 / 1001


@dataclass
class Timeline:
    keeps: list  # [(src_start, src_end), ...] in source seconds, ascending

    def __post_init__(self):
        self.keeps = [tuple(k) for k in self.keeps]
        self.starts = []
        t = 0.0
        for s, e in self.keeps:
            self.starts.append(t)
            t += e - s
        self.total = t

    def to_edit(self, src: float) -> float:
        """Edit time for a source time. Times inside a cut snap to the nearest kept edge."""
        best = None
        for (s, e), t0 in zip(self.keeps, self.starts):
            if s <= src <= e:
                return t0 + src - s
            edge = (t0 if src < s else t0 + e - s, min(abs(src - s), abs(src - e)))
            if best is None or edge[1] < best[1]:
                best = edge
        return best[0]

    def to_src(self, edit_t: float) -> float:
        """Source time for an edit time (a cut point maps to the start of the following keep)."""
        for (s, e), t0 in zip(self.keeps, self.starts):
            if t0 - 1e-6 <= edit_t < t0 + (e - s) - 1e-6:
                return s + edit_t - t0
        s, e = self.keeps[-1]
        return e

    def segment_start(self, edit_t: float) -> float:
        """Start (edit time) of the kept segment containing edit_t."""
        return max(s for s in self.starts if s <= edit_t + 1e-6)

    def cut_points(self) -> list:
        return self.starts[1:]
