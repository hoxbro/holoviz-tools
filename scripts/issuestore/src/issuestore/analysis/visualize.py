"""Interactive Panel app: explore issue embeddings as a filterable 2D scatter.

Every stored issue is classified along the topic and type dimensions (same logic
as ``classify.py``) and the high-dimensional embeddings are projected to 2D with
t-SNE (computed once at startup, independent of category). A Panel app then lets
you filter by topic AND type simultaneously (plus state and title search), while
choosing which one of the two dimensions the scatter is colored by. Each point
has a hover tooltip (issue number, title, state, category, score).

Examples::

    panel serve issuestore/analysis/visualize.py --show   # serve the module directly
    python -m issuestore.analysis.visualize --show         # launch a server via main()
    python -m issuestore.analysis.visualize --port 5007 --perplexity 50
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from issuestore.analysis.classify import (
    DEFAULT_TOPIC_CATEGORIES,
    DEFAULT_TYPE_CATEGORIES,
    classify_issues,
    classify_type_dimension,
    load_categories,
)
from issuestore.config import get_collection

STATE_ALL = "all"


def project_2d(embs: np.ndarray, perplexity: float = 30.0, random_state: int = 0) -> np.ndarray:
    """Reduce (n, d) embeddings to (n, 2) with t-SNE.

    perplexity must stay below the sample count, so it is clamped for tiny inputs.
    """
    from sklearn.manifold import TSNE  # noqa: PLC0415

    n = len(embs)
    perplexity = min(perplexity, max(1.0, (n - 1) / 3))
    tsne = TSNE(n_components=2, perplexity=perplexity, init="pca", random_state=random_state)
    return tsne.fit_transform(embs)


def category_colors(categories: list[str]) -> dict[str, str]:
    """Map each category name to a fixed hex color.

    Using an explicit name->color dict (rather than a palette name) keeps a
    category's color stable no matter which subset is currently displayed, so
    colors don't reshuffle when filtering or deselecting.
    """
    from bokeh.palettes import Category20_20  # noqa: PLC0415

    palette = Category20_20
    return {c: palette[i % len(palette)] for i, c in enumerate(sorted(categories))}


def build_scatter(df: pd.DataFrame, category_col: str, score_col: str, cmap="Category20"):
    """Build an interactive HoloViews scatter from a frame with x, y, and metadata.

    Expects columns: x, y, number, title, state, plus ``category_col``/``score_col``.
    Points are colored by ``category_col`` with a hover tooltip; returns a HoloViews
    element. Pass a name->color dict as ``cmap`` to keep colors stable across
    filtered subsets.
    """
    import holoviews as hv  # noqa: PLC0415

    hv.extension("bokeh")

    points = hv.Points(
        df,
        kdims=["x", "y"],
        vdims=[category_col, score_col, "number", "title", "state"],
    )
    return points.opts(
        color=category_col,
        cmap=cmap,
        legend_position="right",
        size=7,
        responsive=True,
        min_height=600,
        tools=["hover", "tap", "box_select"],
        # x/y are just the t-SNE layout, not meaningful to a reader - keep them
        # out of the tooltip.
        hover_tooltips=[category_col, score_col, "number", "title", "state"],
        xaxis=None,
        yaxis=None,
        title=f"Issue embeddings (t-SNE) — {len(df)} issues",
    )


def load_plot_frame(labels: str | None, perplexity: float) -> tuple[pd.DataFrame, list[str]]:
    """Classify every issue and attach 2D t-SNE coordinates.

    Categories are assigned with no score floor (min_score=0) so the app's score
    slider can filter interactively without changing the assignment.

    With ``labels`` given, classifies that single custom dimension into
    "category"/"score" columns. Otherwise classifies both built-in dimensions
    (topic, type) into "topic"/"topic_score" and "type"/"type_score" columns, so
    the app can switch between them live.

    Returns (df, dims) where ``dims`` names the classified dimension column(s).
    """
    categories = load_categories(labels)
    collection = get_collection()

    if categories is not None:
        df = classify_issues(collection, categories, min_score=0.0)
        dims = ["category"]
    else:
        topic_df = classify_issues(collection, DEFAULT_TOPIC_CATEGORIES, min_score=0.0)
        type_df = classify_type_dimension(collection, DEFAULT_TYPE_CATEGORIES, min_score=0.0)
        df = topic_df.rename(columns={"category": "topic", "score": "topic_score"}).merge(
            type_df[["number", "category", "score"]].rename(
                columns={"category": "type", "score": "type_score"}
            ),
            on="number",
        )
        dims = ["topic", "type"]

    # Re-fetch embeddings and align them to df's row order.
    got = collection.get(include=["embeddings", "metadatas"])
    by_number = {
        m["number"]: e
        for m, e in zip(got["metadatas"], np.asarray(got["embeddings"], np.float32), strict=False)
    }
    embs = np.asarray([by_number[n] for n in df["number"]], dtype=np.float32)

    coords = project_2d(embs, perplexity=perplexity)
    return df.assign(x=coords[:, 0], y=coords[:, 1]).reset_index(drop=True), dims


def _score_col(dim: str) -> str:
    return "score" if dim == "category" else f"{dim}_score"


def _issue_card(row: pd.Series, category_col: str, score_col: str):
    """A Material card for one selected issue, with a button that opens it on GitHub."""
    import panel_material_ui as pmui  # noqa: PLC0415

    open_btn = pmui.Button(
        label="Open issue",
        href=row["url"],
        target="_blank",
        icon="open_in_new",
        variant="contained",
        color="primary",
    )
    meta = pmui.Typography(
        f"**#{row['number']}** · {row['state']} · {row[category_col]} · score {row[score_col]:.3f}",
        variant="body2",
    )
    return pmui.Card(
        pmui.Typography(row["title"], variant="subtitle1"),
        meta,
        open_btn,
        sizing_mode="stretch_width",
        margin=(4, 0),
    )


def build_app(df: pd.DataFrame, dims: list[str]):
    """Assemble the Material app: filters in the sidebar, a live scatter, and a
    tap-to-inspect panel that lets you jump from a point straight to its issue.

    ``dims`` lists the classified dimension(s) present in ``df`` (see
    ``load_plot_frame``). When there's more than one, every dimension gets its
    own category/score filter and all apply simultaneously (AND'd together);
    a separate "color by" control picks which dimension the scatter is colored
    by, all without recomputing the shared t-SNE layout.
    """
    import holoviews as hv  # noqa: PLC0415
    import panel as pn  # noqa: PLC0415
    import panel_material_ui as pmui  # noqa: PLC0415

    pn.extension()

    def categories_for_dim(dim: str) -> list[str]:
        return sorted(df[dim].unique())

    # Fixed color per category so colors stay put when filtering/deselecting.
    # Kept per-dimension since topic and type have separate name spaces.
    color_maps = {dim: category_colors(categories_for_dim(dim)) for dim in dims}

    states = sorted(df["state"].unique())
    default_dim = dims[0]

    # One category MultiChoice + score slider per dimension, all filtering the
    # same underlying frame simultaneously.
    dim_filters = {
        dim: {
            "categories": pmui.MultiChoice(
                label=f"{dim.capitalize()}s" if dim != "category" else "Categories",
                options=categories_for_dim(dim),
                value=categories_for_dim(dim),
            ),
            "score": pmui.FloatSlider(
                label=f"Min {dim} score" if dim != "category" else "Min score",
                start=0.0,
                end=1.0,
                step=0.01,
                value=0.0,
            ),
        }
        for dim in dims
    }
    color_select = (
        pmui.RadioButtonGroup(label="Color by", options=dims, value=default_dim)
        if len(dims) > 1
        else None
    )
    state_select = pmui.RadioButtonGroup(
        label="State", options=[STATE_ALL, *states], value=STATE_ALL
    )
    search_input = pmui.TextInput(label="Title search", placeholder="substring match…")
    count_md = pmui.Typography("", variant="body2")

    # Selected-issue detail lives here; tapping points refreshes it.
    selection_col = pmui.Column(
        pmui.Typography("Tap a point to inspect its issue.", variant="body2"),
        sizing_mode="stretch_width",
    )
    # Holds the currently displayed subset (and active color dimension) so the
    # tap subscriber can look rows up with the right columns. Kept as two
    # single-purpose dicts (rather than one, mixed-value) so each stays typed.
    sub_state: dict[str, pd.DataFrame] = {"sub": df}
    color_dim_state: dict[str, str] = {"color_dim": default_dim}

    def clear_scores():
        for f in dim_filters.values():
            f["score"].value = 0.0

    def show_selection(index):
        sub = sub_state["sub"]
        category_col = color_dim_state["color_dim"]
        if not index:
            selection_col[:] = [
                pmui.Typography("Tap a point to inspect its issue.", variant="body2")
            ]
            return
        rows = sub.iloc[[i for i in index if i < len(sub)]]
        header = pmui.Typography(f"### {len(rows)} selected", variant="subtitle2")
        selection_col[:] = [
            header,
            *[
                _issue_card(r, category_col, _score_col(category_col))
                for _, r in rows.head(25).iterrows()
            ],
        ]

    def filtered(state_val, search, color_dim=default_dim, **dim_values):
        color_dim_state["color_dim"] = color_dim
        mask = pd.Series(True, index=df.index)
        for dim in dims:
            categories = dim_values[f"{dim}__categories"]
            min_score = dim_values[f"{dim}__score"]
            mask &= df[dim].isin(categories) & (df[_score_col(dim)] >= min_score)
        if state_val != STATE_ALL:
            mask &= df["state"] == state_val
        if search:
            mask &= df["title"].str.contains(search, case=False, regex=False)
        sub = df[mask].reset_index(drop=True)
        sub_state["sub"] = sub
        count_md.object = f"**{len(sub)}** / {len(df)} issues shown"
        if sub.empty:
            return hv.Points([], kdims=["x", "y"]).opts(responsive=True, min_height=600)
        return build_scatter(sub, color_dim, _score_col(color_dim), cmap=color_maps[color_dim])

    # A DynamicMap redrawn by the filter widgets (via Params streams). Selection
    # and double-tap streams are attached to the DynamicMap ONCE, so their
    # subscribers persist across redraws instead of being re-registered.
    Params = hv.streams.Params
    filter_streams = [
        Params(state_select, ["value"], rename={"value": "state_val"}),
        Params(search_input, ["value"], rename={"value": "search"}),
    ]
    for dim, widgets in dim_filters.items():
        filter_streams.append(
            Params(widgets["categories"], ["value"], rename={"value": f"{dim}__categories"})
        )
        filter_streams.append(
            Params(widgets["score"], ["value"], rename={"value": f"{dim}__score"})
        )
    if color_select is not None:
        filter_streams.append(Params(color_select, ["value"], rename={"value": "color_dim"}))
    plot = hv.DynamicMap(filtered, streams=filter_streams)

    sel = hv.streams.Selection1D(source=plot)
    sel.add_subscriber(show_selection)
    # Double-tapping the plot clears every score filter.
    dtap = hv.streams.DoubleTap(source=plot)
    dtap.add_subscriber(lambda x, y: clear_scores())

    dim_widgets = [w for widgets in dim_filters.values() for w in widgets.values()]
    filters_card = pmui.Card(
        *([color_select] if color_select is not None else []),
        *dim_widgets,
        state_select,
        search_input,
        count_md,
        title="Filters",
        sizing_mode="stretch_width",
    )
    selection_card = pmui.Card(
        selection_col,
        title="Selection",
        sizing_mode="stretch_width",
    )
    sidebar = pmui.Column(filters_card, selection_card)
    main = pmui.HoloViews(plot, sizing_mode="stretch_both")
    return pmui.Page(
        title="issuestore explorer", sidebar=[sidebar], main=[main], sidebar_width=360
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--labels",
        help="file of 'name: description' lines (default: built-in topic + type dimensions)",
    )
    parser.add_argument("--perplexity", type=float, default=30.0, help="t-SNE perplexity")
    parser.add_argument("--port", type=int, default=5006, help="server port")
    parser.add_argument("--show", action="store_true", help="open a browser tab")
    args = parser.parse_args()

    import panel as pn  # noqa: PLC0415

    df, dims = load_plot_frame(args.labels, args.perplexity)
    app = build_app(df, dims).servable()
    pn.serve(app, port=args.port, show=args.show)


if __name__ == "__main__":
    main()
