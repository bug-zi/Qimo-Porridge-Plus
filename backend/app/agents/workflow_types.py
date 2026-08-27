from collections.abc import Callable
from typing import Any

JsonModelCall = Callable[[str, str, str], dict[str, Any]]

