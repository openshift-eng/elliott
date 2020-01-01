from __future__ import absolute_import, print_function, unicode_literals
import sys
from elliottlib import constants as elliott_constants

ELLIOTT_CMD = [sys.executable, "-m", "elliottlib.cli", "--quiet"]
ERRATA_TOOL_URL = elliott_constants.errata_url
