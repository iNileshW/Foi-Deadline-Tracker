"""Shared test setup.

The app module refuses to import without a session secret. Tests
run with an ephemeral dev secret; production runs must set
FOI_SECRET_KEY explicitly.
"""

import os

os.environ.setdefault("FOI_ALLOW_INSECURE_DEV_SECRET", "1")
