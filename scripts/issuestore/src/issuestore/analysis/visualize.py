"""Interactive Panel app: explore issue embeddings as a filterable 2D scatter.

Every stored issue is assigned a category (same logic as ``classify.py``) and the
high-dimensional embeddings are projected to 2D with t-SNE (computed once at
startup). A Panel app then lets you filter the points live by category, state,
title search, and minimum classification score. Each point is colored by category
with a hover tooltip (issue number, title, state, category, score).

Examples::

    panel serve issuestore/analysis/visualize.py --show   # serve the module directly
    python -m issuestore.analysis.visualize --show         # launch a server via main()
    python -m issuestore.analysis.visualize --port 5007 --perplexity 50
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from issuestore.analysis.classify import classify_issues, load_categories
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


def build_scatter(df: pd.DataFrame, cmap="Category20"):
    """Build an interactive HoloViews scatter from a frame with x, y, and metadata.

    Expects columns: x, y, number, title, state, category, score. Points are
    colored by category with a hover tooltip; returns a HoloViews element. Pass a
    name->color dict as ``cmap`` to keep colors stable across filtered subsets.
    """
    import holoviews as hv  # noqa: PLC0415

    hv.extension("bokeh")

    points = hv.Points(
        df,
        kdims=["x", "y"],
        vdims=["category", "number", "title", "state", "score"],
    )
    return points.opts(
        color="category",
        cmap=cmap,
        legend_position="right",
        size=7,
        responsive=True,
        min_height=600,
        tools=["hover", "tap", "box_select"],
        xaxis=None,
        yaxis=None,
        title=f"Issue embeddings (t-SNE) — {len(df)} issues",
    )


def load_plot_frame(labels: str | None, perplexity: float) -> pd.DataFrame:
    """Classify every issue and attach 2D t-SNE coordinates.

    Categories are assigned with no score floor (min_score=0) so the app's score
    slider can filter interactively without changing the assignment.
    """
    categories = load_categories(labels)
    collection = get_collection()

    df = classify_issues(collection, categories, min_score=0.0)

    # Re-fetch embeddings and align them to df's (category-sorted) row order.
    got = collection.get(include=["embeddings", "metadatas"])
    by_number = {
        m["number"]: e
        for m, e in zip(got["metadatas"], np.asarray(got["embeddings"], np.float32), strict=False)
    }
    embs = np.asarray([by_number[n] for n in df["number"]], dtype=np.float32)

    coords = project_2d(embs, perplexity=perplexity)
    return df.assign(x=coords[:, 0], y=coords[:, 1]).reset_index(drop=True)


def _issue_card(row: pd.Series):
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
        f"**#{row['number']}** · {row['state']} · {row['category']} · score {row['score']:.3f}",
        variant="body2",
    )
    return pmui.Card(
        pmui.Typography(row["title"], variant="subtitle1"),
        meta,
        open_btn,
        sizing_mode="stretch_width",
        margin=(4, 0),
    )


def build_app(df: pd.DataFrame):
    """Assemble the Material app: filters in the sidebar, a live scatter, and a
    tap-to-inspect panel that lets you jump from a point straight to its issue.
    """
    import holoviews as hv  # noqa: PLC0415
    import panel as pn  # noqa: PLC0415
    import panel_material_ui as pmui  # noqa: PLC0415

    pn.extension()

    categories = sorted(df["category"].unique())
    states = sorted(df["state"].unique())
    # Fixed color per category so colors stay put when filtering/deselecting.
    color_map = category_colors(categories)

    category_select = pmui.MultiChoice(label="Categories", options=categories, value=categories)
    state_select = pmui.RadioButtonGroup(
        label="State", options=[STATE_ALL, *states], value=STATE_ALL
    )
    search_input = pmui.TextInput(label="Title search", placeholder="substring match…")
    score_slider = pmui.FloatSlider(label="Min score", start=0.0, end=1.0, step=0.01, value=0.0)
    count_md = pmui.Typography("", variant="body2")

    # Selected-issue detail lives here; tapping points refreshes it.
    selection_col = pmui.Column(
        pmui.Typography("Tap a point to inspect its issue.", variant="body2"),
        sizing_mode="stretch_width",
    )
    # Holds the currently displayed subset so the tap subscriber can look rows up.
    state = {"sub": df}

    def clear_score():
        score_slider.value = 0.0

    def show_selection(index):
        sub = state["sub"]
        if not index:
            selection_col[:] = [
                pmui.Typography("Tap a point to inspect its issue.", variant="body2")
            ]
            return
        rows = sub.iloc[[i for i in index if i < len(sub)]]
        header = pmui.Typography(f"### {len(rows)} selected", variant="subtitle2")
        selection_col[:] = [header, *[_issue_card(r) for _, r in rows.head(25).iterrows()]]

    def filtered(categories, state_val, search, min_score):
        mask = df["category"].isin(categories) & (df["score"] >= min_score)
        if state_val != STATE_ALL:
            mask &= df["state"] == state_val
        if search:
            mask &= df["title"].str.contains(search, case=False, regex=False)
        sub = df[mask].reset_index(drop=True)
        state["sub"] = sub
        count_md.object = f"**{len(sub)}** / {len(df)} issues shown"
        if sub.empty:
            return hv.Points([], kdims=["x", "y"]).opts(responsive=True, min_height=600)
        return build_scatter(sub, cmap=color_map)

    # A DynamicMap redrawn by the filter widgets (via Params streams). Selection
    # and double-tap streams are attached to the DynamicMap ONCE, so their
    # subscribers persist across redraws instead of being re-registered.
    Params = hv.streams.Params
    filter_streams = [
        Params(category_select, ["value"], rename={"value": "categories"}),
        Params(state_select, ["value"], rename={"value": "state_val"}),
        Params(search_input, ["value"], rename={"value": "search"}),
        Params(score_slider, ["value"], rename={"value": "min_score"}),
    ]
    plot = hv.DynamicMap(filtered, streams=filter_streams)

    sel = hv.streams.Selection1D(source=plot)
    sel.add_subscriber(show_selection)
    # Double-tapping the plot clears the score filter.
    dtap = hv.streams.DoubleTap(source=plot)
    dtap.add_subscriber(lambda x, y: clear_score())

    filters_card = pmui.Card(
        category_select,
        state_select,
        search_input,
        score_slider,
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
        "--labels", help="file of 'name: description' lines (default: built-in categories)"
    )
    parser.add_argument("--perplexity", type=float, default=30.0, help="t-SNE perplexity")
    parser.add_argument("--port", type=int, default=5006, help="server port")
    parser.add_argument("--show", action="store_true", help="open a browser tab")
    args = parser.parse_args()

    import panel as pn  # noqa: PLC0415

    df = load_plot_frame(args.labels, args.perplexity)
    app = build_app(df).servable()
    pn.serve(app, port=args.port, show=args.show)


if __name__ == "__main__":
    main()
