# Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Pytest plugin to configure sys.path before Django is loaded.
This file is loaded by pytest before conftest.py through pyproject.toml configuration.
"""
import sys
from pathlib import Path


# Add siteapps to sys.path to enable relative imports in Django apps
site_apps_dir = Path(__file__).parent / "siteapps"
if str(site_apps_dir) not in sys.path:
    sys.path.insert(0, str(site_apps_dir))
