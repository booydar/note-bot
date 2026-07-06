"""One Google-Sheets client for finance + movies (was duplicated in both).

Google traffic must go through the SOCKS proxy while Nextcloud/Telegram traffic
must not, so the proxy is applied only inside the `ctx()` block: it temporarily
sets the proxy env vars, yields an authorized gspread client, and restores the
env afterwards. Do all sheet operations inside the block.
"""

from __future__ import annotations

import contextlib
import os


class GSheetsClient:
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets',
              'https://www.googleapis.com/auth/drive']

    def __init__(self, cred_path, proxy=None):
        from oauth2client.service_account import ServiceAccountCredentials
        self.proxy = proxy
        self.credentials = ServiceAccountCredentials.from_json_keyfile_name(cred_path, self.SCOPES)

    @contextlib.contextmanager
    def _proxy_env(self):
        if not self.proxy:
            yield
            return
        keys = ('HTTPS_PROXY', 'HTTP_PROXY', 'https_proxy', 'http_proxy')
        saved = {k: os.environ.get(k) for k in keys}
        for k in keys:
            os.environ[k] = self.proxy
        try:
            yield
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    @contextlib.contextmanager
    def ctx(self):
        """Yield an authorized gspread client, with the proxy env in place."""
        import gspread
        with self._proxy_env():
            yield gspread.authorize(self.credentials)
