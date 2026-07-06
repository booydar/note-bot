"""Configuration for all frontends.

Everything comes from one folder (the `config` env var, same as before):
  var.json      - all settings (see config.example.json in the repo root)
  gsheets.json  - Google service-account credentials

Frontends declare what they actually need via `cfg.require(...)`, so a missing
key fails at startup with a clear message instead of a random KeyError later.
"""

from __future__ import annotations

import json
import logging
import os
import sys


class Config:
    def __init__(self, values: dict, folder: str):
        self._values = values
        self.folder = folder

    def get(self, key, default=None):
        return self._values.get(key, default)

    def __getitem__(self, key):
        return self._values[key]

    def require(self, *keys):
        missing = [k for k in keys if not self._values.get(k)]
        if missing:
            raise SystemExit(
                f"config error: missing key(s) {missing} in {os.path.join(self.folder, 'var.json')}"
            )

    # --- common derived values -----------------------------------------------
    @property
    def gsheets_cred(self):
        return os.path.join(self.folder, "gsheets.json")

    @property
    def note_db_path(self):
        return self._values["note_db_path"]

    @property
    def cache_path(self):
        return self._values["cache_path"]

    @property
    def events_db(self):
        return self._values.get("events_db") or os.path.join(self.cache_path, "events.sqlite")

    @property
    def os_user_id(self):
        v = os.getenv("os_user_id")
        return int(v) if v else None

    @property
    def proxy(self):
        return self._values.get("proxy")


def load_config(folder: str | None = None) -> Config:
    folder = folder or os.getenv("config")
    if not folder:
        raise SystemExit("config error: set the `config` env var to the config folder")
    path = os.path.join(folder, "var.json")
    try:
        with open(path) as f:
            values = json.load(f)
    except FileNotFoundError:
        raise SystemExit(f"config error: {path} not found")
    except json.JSONDecodeError as e:
        raise SystemExit(f"config error: {path} is not valid JSON: {e}")

    cfg = Config(values, folder)
    cfg.require("note_db_path", "cache_path")
    if values.get("ffprobe"):
        sys.path.append(values["ffprobe"])
    return cfg


def setup_logging(level=logging.INFO):
    """Log to stdout, and also to $LOG_FILE if set (readable without docker/sudo)."""
    handlers = [logging.StreamHandler(sys.stdout)]
    log_file = os.getenv("LOG_FILE")
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )
