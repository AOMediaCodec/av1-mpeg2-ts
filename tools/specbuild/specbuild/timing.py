"""Build timing: measure and report duration of each pipeline step."""

from __future__ import annotations

import logging
import time


class BuildTimer:
    """Accumulates timing data for named build steps.

    Usage::

        timer = BuildTimer()
        with timer.step("Compile"):
            compile_spec(...)
        with timer.step("PDF"):
            generate_pdf(...)
        timer.report()
    """

    def __init__(self) -> None:
        self._steps: list[tuple[str, float]] = []
        self._start_time: float = time.monotonic()

    class _StepContext:
        """Context manager for timing a single step."""

        def __init__(self, timer: BuildTimer, name: str):
            self._timer = timer
            self._name = name
            self._start = 0.0

        def __enter__(self) -> BuildTimer._StepContext:
            self._start = time.monotonic()
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: object,
        ) -> bool:
            elapsed = time.monotonic() - self._start
            self._timer._steps.append((self._name, elapsed))
            return False

    def step(self, name: str) -> _StepContext:
        """Return a context manager that times a named step.

        Args:
            name: Human-readable step name for the report.
        """
        return self._StepContext(self, name)

    @property
    def steps(self) -> list[tuple[str, float]]:
        """Return a copy of the recorded (name, elapsed) pairs."""
        return list(self._steps)

    def report(self) -> None:
        """Log a summary table of all timed steps."""
        total = time.monotonic() - self._start_time

        if not self._steps:
            return

        logging.info("")
        logging.info("=" * 60)
        logging.info("Build Timing Report")
        logging.info("=" * 60)

        # Find longest step name for alignment
        max_name = max(len(name) for name, _ in self._steps)
        min_col_width = 30
        col_width = max(max_name + 2, min_col_width)

        bar_scale = 2.5  # divisor: 100% / 2.5 = 40-char max bar width
        for name, elapsed in self._steps:
            pct = (elapsed / total * 100) if total > 0 else 0
            bar_len = int(pct / bar_scale)
            bar = "█" * bar_len
            logging.info(f"  {name:<{col_width}} {elapsed:6.2f}s  {pct:5.1f}%  {bar}")

        logging.info("-" * 60)
        logging.info(f"  {'Total':<{col_width}} {total:6.2f}s")
        logging.info("=" * 60)
