"""Load and access the project YAML config (see example_config.yaml).

The config is a nested mapping organized as ``<concern>.<component>.<key>``,
e.g. ``paths.patreon.chapters_csv`` or ``plot.royalroad.out``. This module
wraps the parsed dict so those values can be reached by attribute access,
dotted-string lookup, or by grabbing a whole section as a plain dict.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = "config.yaml"

_MISSING = object()


class ConfigError(KeyError):
    """Raised when a requested config key or section does not exist."""


class Config:
    """A thin, read-only wrapper around the parsed YAML config.

    Access styles (all equivalent where the path exists):

        config["paths"]["patreon"]["chapters_csv"]   # raw dict indexing
        config.paths.patreon.chapters_csv            # attribute access
        config.get("paths.patreon.chapters_csv")     # dotted lookup
        config.section("plot.patreon")               # whole sub-mapping as dict
    """

    def __init__(self, data: dict[str, Any] | None = None):
        self._data: dict[str, Any] = data or {}

    # -- construction -------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CONFIG_PATH) -> "Config":
        """Load config from ``path``. Raises FileNotFoundError if missing."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {p}")
        with p.open() as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ConfigError(f"Top-level config must be a mapping, got {type(data).__name__}")
        return cls(data)

    # -- lookup -------------------------------------------------------------

    def get(self, dotted_key: str, default: Any = _MISSING) -> Any:
        """Look up a value by dotted path, e.g. ``"plot.patreon.day_rolling_avg"``.

        Returns ``default`` if provided and the key is absent; otherwise raises
        ConfigError. Intermediate mappings are returned as Config objects so
        access can continue (``config.get("paths").patreon``).
        """
        node: Any = self._data
        for part in dotted_key.split("."):
            if isinstance(node, Config):
                node = node._data
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                if default is _MISSING:
                    raise ConfigError(f"Missing config key: {dotted_key!r}")
                return default
        return self._wrap(node)

    def section(self, dotted_key: str) -> dict[str, Any]:
        """Return a whole sub-mapping as a plain dict (copy).

        Handy for feeding argparse defaults, e.g.::

            cfg = Config.load()
            defaults = cfg.section("plot.patreon")
            parser.add_argument("--day-rolling-avg",
                                default=defaults.get("day_rolling_avg", 26))
        """
        node = self.get(dotted_key)
        if isinstance(node, Config):
            return dict(node._data)
        if isinstance(node, dict):
            return dict(node)
        raise ConfigError(f"Config key {dotted_key!r} is not a section (got {type(node).__name__})")

    def as_dict(self) -> dict[str, Any]:
        """Return the underlying data as a plain dict."""
        return self._data

    # -- dunder access ------------------------------------------------------

    def _wrap(self, value: Any) -> Any:
        return Config(value) if isinstance(value, dict) else value

    def __getitem__(self, key: str) -> Any:
        if key not in self._data:
            raise ConfigError(f"Missing config key: {key!r}")
        return self._wrap(self._data[key])

    def __getattr__(self, name: str) -> Any:
        # Only called when normal attribute lookup fails, so _data is safe.
        try:
            return self._wrap(self._data[name])
        except KeyError:
            raise AttributeError(
                f"Config has no key {name!r} (available: {', '.join(self._data) or '<empty>'})"
            )

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __iter__(self):
        return iter(self._data)

    def keys(self):
        return self._data.keys()

    def __repr__(self) -> str:
        return f"Config({list(self._data)!r})"


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> Config:
    """Convenience function mirroring ``Config.load``."""
    return Config.load(path)
