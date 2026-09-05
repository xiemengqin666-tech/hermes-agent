#!/usr/bin/env python3
"""Verify actual Hermes browser selection for each profile without launching it."""

import argparse
import os
from pathlib import Path
import subprocess
import sys


PROBE = """
import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.environ['HERMES_HOME'], '.env'), override=True)
from tools.browser_use_cli import is_browser_use_cli_mode
from tools.browser_tool import _build_browser_env
from tools.browser_tool_cdp import _get_cdp_override_raw
from tools.browser_tool_cloud import _use_real_profile
from tools.browser_tool_install import check_browser_requirements
assert not is_browser_use_cli_mode(), 'Browser Use would bypass Edge routing'
assert check_browser_requirements(), 'Built-in browser tools are unavailable'
assert not _use_real_profile(), 'Default real-browser profile is enabled'
assert not _get_cdp_override_raw(), 'Unexpected CDP override'
env = _build_browser_env()
assert env.get('AGENT_BROWSER_EXECUTABLE_PATH') == (
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
), 'Edge executable missing from the actual browser subprocess environment'
assert env.get('AGENT_BROWSER_AUTO_CONNECT', '').lower() not in ('1', 'true'), (
    'Auto-connect could attach to Chrome'
)
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--hermes-repo', type=Path, required=True)
    args = parser.parse_args()
    homes = [args.home, *sorted((args.home / 'profiles').glob('*'))]
    for home in homes:
        if not (home / 'config.yaml').is_file():
            continue
        subprocess.run(
            [sys.executable, '-c', PROBE],
            cwd=args.hermes_repo,
            env={**os.environ, 'HERMES_HOME': str(home)},
            check=True, timeout=30,
        )
        print(f'Edge routing verified: {home.name}', flush=True)


if __name__ == '__main__':
    main()
