"""Repositories issuestore supports.

Kept free of side effects so it can be imported without resolving the active
repository in ``issuestore.config``.
"""

from __future__ import annotations

REPOS: tuple[str, ...] = (
    "holoviz/holoviews",
    "holoviz/panel",
    "holoviz/hvplot",
    "holoviz/param",
    "holoviz/geoviews",
    "holoviz/datashader",
    "bokeh/bokeh",
)
