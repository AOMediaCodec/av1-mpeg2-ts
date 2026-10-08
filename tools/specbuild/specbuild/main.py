"""Console entry point for the ``specbuild`` command.

After ``pip install -e .``, this module is invoked via::

    specbuild            # equivalent to: python compile.py
    specbuild --pdf      # equivalent to: python compile.py --pdf

The heavy lifting lives in ``compile.py`` at the project root.  This
module loads it by absolute path (avoiding ``sys.path`` pollution) and
re-exports its :func:`~compile.main` for use as a ``console_scripts``
entry point.
"""

from __future__ import annotations


def main() -> None:
    """Entry point for the ``specbuild`` console script."""
    # Import lazily so the package can be imported without pulling in
    # the full build driver and all its transitive dependencies.
    import importlib.util

    from specbuild import PROJECT_ROOT

    # Load compile.py by absolute path — avoids mutating sys.path and
    # prevents shadowing the stdlib ``compile`` module.
    _compile_py = PROJECT_ROOT / "compile.py"
    if not _compile_py.exists():
        # When installed as a regular wheel (not editable), compile.py lives
        # next to the package in the project root.  Handle --help and
        # --version gracefully rather than crashing with a confusing error.
        import sys

        if any(
            a in sys.argv
            for a in ("--help", "-h", "--version", "--list-profiles", "--help-features")
        ):
            # Bootstrap a minimal argparse just for informational flags.
            import argparse

            p = argparse.ArgumentParser(
                prog="specbuild",
                description="specbuild: Bikeshed specification build pipeline.",
            )
            p.add_argument("--version", action="version", version="specbuild (wheel install)")
            p.parse_known_args()
            return
        raise FileNotFoundError(
            f"compile.py not found at {_compile_py}. "
            "Run specbuild from the project root with an editable install "
            "(pip install -e .) or from the checked-out repository."
        )
    spec = importlib.util.spec_from_file_location("compile", _compile_py)
    if spec is None:
        raise RuntimeError(f"Could not load module spec from {_compile_py}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main()
