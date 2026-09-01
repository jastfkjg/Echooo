from __future__ import annotations


class SentenceSegmenter:
    """Turns LLM text deltas into chunks that are long enough for natural TTS."""

    hard_breaks = set("。！？!?；;\n")
    soft_breaks = set("，,")

    def __init__(self, *, min_chars: int = 8, soft_chars: int = 24, max_chars: int = 60):
        self.min_chars = min_chars
        self.soft_chars = soft_chars
        self.max_chars = max_chars
        self._buffer = ""

    def feed(self, delta: str) -> list[str]:
        self._buffer += delta
        ready: list[str] = []
        while True:
            split_at = self._find_split()
            if split_at is None:
                break
            chunk = self._buffer[:split_at].strip()
            self._buffer = self._buffer[split_at:]
            if chunk:
                ready.append(chunk)
        return ready

    def _find_split(self) -> int | None:
        for index, char in enumerate(self._buffer, start=1):
            if index >= self.min_chars and char in self.hard_breaks:
                return index
            if index >= self.soft_chars and char in self.soft_breaks:
                return index
            if index >= self.max_chars:
                return index
        return None

    def flush(self) -> str:
        remaining = self._buffer.strip()
        self._buffer = ""
        return remaining

