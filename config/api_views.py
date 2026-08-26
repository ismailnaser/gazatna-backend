"""Backward-compatible re-exports. Prefer importing from domain apps."""
from accounts.views import *  # noqa: F401,F403
from academics.views import *  # noqa: F401,F403
from assignments.views import *  # noqa: F401,F403
from content.views import *  # noqa: F401,F403
from finance.views import *  # noqa: F401,F403
from staff.views import *  # noqa: F401,F403
from config.api_helpers import *  # noqa: F401,F403
