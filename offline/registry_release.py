"""Executable entrypoint for offline registry publishing (`O2`)."""

from __future__ import annotations

import sys

from dle.tools.registry_release import main

if __name__ == "__main__":
    sys.exit(main())
