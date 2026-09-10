"""Test-suite guards that keep the suite from touching real user data.

The suite must never write to the user's app data dir. A previous version of
``test_agent_platform_provider.py`` constructed a bare ``BackendConfig()`` and
called ``update()``, which overwrote the live ``config.json`` API keys with mock
values. Isolate router singletons during collection as well as file logging.
"""

import os
import tempfile

_test_profile = tempfile.TemporaryDirectory(prefix="echo-pytest-", ignore_cleanup_errors=True)
os.environ["ECHO_DATA_DIR"] = _test_profile.name
os.environ["VOICESPIRIT_DATA_DIR"] = _test_profile.name

os.environ.setdefault("ECHO_DISABLE_FILE_LOG", "1")
