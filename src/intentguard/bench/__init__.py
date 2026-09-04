"""The synthetic benchmark: a generator that cannot see the engine, and a harness that can."""

from .harness import injection_experiment, render, report_for, run, run_case

__all__ = ["injection_experiment", "render", "report_for", "run", "run_case"]
