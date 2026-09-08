"""Test-suite guards that keep the suite from touching real user data.

The suite must never write to the user's app data dir. A previous version of
``test_agent_platform_provider.py`` constructed a bare ``BackendConfig()`` and
called ``update()``, which overwrote the live ``config.json`` API keys with mock
values. Tests build their own config via a temp file; this file covers the
one remaining side channel — the rotating log file.
"""

import os

os.environ.setdefault("ECHO_DISABLE_FILE_LOG", "1")
