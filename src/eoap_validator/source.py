"""Source reading and conservative original-YAML locations."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import unquote, urldefrag, urlparse

import requests
from ruamel.yaml import YAML

from .report import Location


class Source:
    def __init__(self, uri: str, data: Any):
        self.uri = uri
        self.data = data

    @classmethod
    def read(cls, uri: str) -> Source:
        parsed = urlparse(uri)
        if parsed.scheme == "file":
            if parsed.netloc not in ("", "localhost"):
                raise OSError("Remote file authorities are not supported")
            content = Path(unquote(parsed.path)).read_text(encoding="utf-8")
        elif parsed.scheme in ("http", "https"):
            response = requests.get(uri, timeout=30)
            response.raise_for_status()
            content = response.text
        else:
            raise OSError(f"Unsupported source scheme: {parsed.scheme}")
        return cls(uri, YAML(typ="rt").load(content))

    def location(self, path: str, node: Any = None, key: Any = None) -> Location:
        line = column = None
        try:
            mark = node.lc.key(key) if key is not None else (node.lc.line, node.lc.col)
            line, column = mark[0] + 1, mark[1] + 1
        except (AttributeError, KeyError, TypeError):
            pass
        return Location(uri=self.uri, path=path, line=line, column=column)

    def process_node(self, process_id: str) -> Any:
        if not isinstance(self.data, dict):
            return None
        nodes = self.data.get("$graph", [self.data])
        matches = [
            n
            for n in nodes
            if isinstance(n, dict)
            and str(n.get("id", "")).removeprefix("#") == process_id
        ]
        if len(matches) == 1:
            return matches[0]
        # A standalone anonymous process has no ambiguous sibling.
        if "$graph" not in self.data and not self.data.get("id"):
            return self.data
        return None


def source_uri(location: str) -> tuple[str, str | None]:
    base, fragment = urldefrag(location)
    uri = base if urlparse(base).scheme else Path(base).absolute().as_uri()
    return uri, unquote(fragment) if "#" in location else None


def missing_local_references(source: Source) -> list[str]:
    """Report directly declared unavailable local dependencies before DOM loading.

    Remote fetch errors remain the resolver's responsibility. This is not a
    recursive dependency manifest or a replacement for schema-salad resolution.
    """
    from urllib.parse import urljoin

    missing: list[str] = []

    def walk(value, base):
        if isinstance(value, list):
            for item in value:
                walk(item, base)
        elif isinstance(value, dict):
            base = urljoin(base, str(value.get("$base", base)))
            for key, item in value.items():
                is_reference = key in ("$import", "$include") or (
                    key == "run" and "in" in value
                )
                if is_reference and isinstance(item, str) and not item.startswith("#"):
                    target = urldefrag(urljoin(base, item))[0]
                    parsed = urlparse(target)
                    if (
                        parsed.scheme == "file"
                        and not Path(unquote(parsed.path)).is_file()
                    ):
                        missing.append(target)
                walk(item, base)

    walk(source.data, source.uri)
    return sorted(set(missing))
