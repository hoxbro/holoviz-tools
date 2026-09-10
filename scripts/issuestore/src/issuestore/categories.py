"""Per-repo zero-shot classification categories.

Two orthogonal dimensions, classified independently (see
``issuestore.analysis.classify``):

- topic: the area of the codebase an issue concerns. Repo-specific, since each
  repo has its own backends/subsystems.
- type: what kind of issue it is (docs, perf, compatibility, ...). Shared
  across repos, since these apply the same way everywhere.

Each is a ``name -> descriptive phrase`` mapping, where the phrase is embedded
and compared (cosine) against each issue's stored embedding to pick the
nearest bucket. Add a new repo by defining its topic mapping and registering
it in ``TOPIC_CATEGORIES_BY_REPO``.
"""

from __future__ import annotations

# bug/feature/enhancement have zero-shot phrases here like everything else, but
# classify_type_dimension (issuestore.analysis.classify) swaps in a few-shot
# centroid - built from issues carrying the matching GitHub `type:` label -
# wherever one is available, since that beats a phrase for this distinction.
TYPE_CATEGORIES = {
    "documentation": "documentation, examples, tutorials, and website content",
    "performance": "slow performance, memory usage, and speed regressions",
    "installation / packaging": "installation, dependencies, conda, pip, and packaging issues",
    "testing": "test failures, flaky tests, and test coverage",
    "ci": "continuous integration, github actions, and build pipeline issues",
    "bug": "a bug report describing incorrect behavior, an error, or a crash",
    "feature": "request for a new feature that doesn't exist yet",
    "enhancement": "request to improve or extend existing functionality",
}

# name -> descriptive phrase used for the embedding comparison.
HOLOVIEWS_CATEGORIES = {
    "bokeh backend": "bokeh javascript interactive plot, bokehjs, hover tools, glyphs, widgets, and toolbar",
    "matplotlib backend": "matplotlib static figure, mpl axes, savefig, and rendered png or svg output",
    "plotly backend": "plotly figure, plotly.js traces, and the plotly renderer in the notebook",
    "datashader / big data": "datashader rasterization, aggregation, or large dataset performance",
    "streams / interactivity": "streams, linked selections, interactive callbacks, and dynamic maps",
    "layout / composition": "layouts, overlays, grids, and composing elements together",
    "styling / options": "styling, options system, colormaps, and appearance customization",
    "data / gridded interface": "data interfaces, pandas, xarray, gridded and tabular data handling",
}

PANEL_CATEGORIES = {
    "widgets": "widgets, sliders, buttons, inputs, and their values and events",
    "layouts / templates": "layouts, templates, rows, columns, tabs, sidebars, and page structure",
    "panes": "panes rendering objects like markdown, html, images, dataframes, and plots",
    "reactive / param": "reactive expressions, param parameters, bind, depends, and callbacks",
    "server / deployment": "panel serve, tornado server, deployment, sessions, and websockets",
    "notebook / jupyter": "jupyter notebook, jupyterlab, ipywidgets comms, and pyodide or wasm",
    "styling / theming": "css, styling, themes, design system, and appearance customization",
    "plotting integration": "integration with bokeh, matplotlib, plotly, holoviews, and other plotting libraries",
}

HVPLOT_CATEGORIES = {
    "pandas / dask backend": "pandas dataframes, dask dataframes, and tabular data plotting",
    "xarray / gridded backend": "xarray datasets, gridded and multidimensional data plotting",
    "geo / geoviews": "geographic plotting, projections, geopandas, and geoviews integration",
    "plot types": "kinds of plots such as line, scatter, bar, hist, heatmap, and image",
    "styling / options": "styling, colormaps, options, and appearance customization",
    "widgets / interactivity": "widgets, sliders, groupby, and interactive exploration",
    "streaming / dynamic data": "streaming data, live updating plots, and dynamic maps",
}

# Registry of repo slug ("owner/name") -> topic mapping.
TOPIC_CATEGORIES_BY_REPO = {
    "holoviz/holoviews": HOLOVIEWS_CATEGORIES,
    "holoviz/panel": PANEL_CATEGORIES,
    "holoviz/hvplot": HVPLOT_CATEGORIES,
}


def topic_categories_for(repo: str) -> dict[str, str]:
    """Return the topic-area mapping for ``repo``, or empty if unregistered."""
    return TOPIC_CATEGORIES_BY_REPO.get(repo, {})


def type_categories_for(repo: str) -> dict[str, str]:
    """Return the issue-type mapping. Same for every repo; ``repo`` is unused
    but kept so callers can treat both dimensions symmetrically."""
    return TYPE_CATEGORIES
