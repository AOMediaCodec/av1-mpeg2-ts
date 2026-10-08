"""specbuild — A reusable pipeline for building Bikeshed specifications.

Import the public API from sub-modules::

    from specbuild.config import CONFIG, SpecConfig
    from specbuild.builder import compile_spec
    from specbuild.output.pdf import generate_pdf
    from specbuild.output.diff import diff_spec
    ...
"""

from pathlib import Path

# Resolved project root (parent of the specbuild/ package directory).
# Used by utils.run_helper_script and others to locate ``scripts/``.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
