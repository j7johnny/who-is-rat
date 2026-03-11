import os

env = os.environ.get("DJANGO_SETTINGS_MODULE", "")
if not env or env == "config.settings":
    # Auto-detect: if POSTGRES_DB is set, use prod; otherwise dev
    if os.environ.get("POSTGRES_DB"):
        from .prod import *  # noqa: F401, F403
    else:
        from .dev import *  # noqa: F401, F403
