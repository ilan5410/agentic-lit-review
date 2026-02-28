"""PRISMA 2020 flow diagram rendered as a Plotly figure."""
from __future__ import annotations

from dataclasses import dataclass, field

import plotly.graph_objects as go


@dataclass
class PRISMAData:
    identified_openalex: int = 0
    identified_semantic_scholar: int = 0
    identified_snowballing: int = 0
    duplicates_removed: int = 0
    screened_title_abstract: int = 0
    excluded_title_abstract: int = 0
    assessed_full_text: int = 0
    excluded_full_text: int = 0
    excluded_full_text_reasons: dict[str, int] = field(default_factory=dict)
    human_reviewed: int = 0
    human_excluded: int = 0
    included_final: int = 0

    @property
    def total_identified(self) -> int:
        return self.identified_openalex + self.identified_semantic_scholar + self.identified_snowballing

    @property
    def after_dedup(self) -> int:
        return self.total_identified - self.duplicates_removed


def build_prisma_figure(data: PRISMAData) -> go.Figure:
    """Return a Plotly figure showing the PRISMA 2020 flow diagram."""

    def box(x, y, text, color="#1E3A5F", width=0.22, height=0.08):
        return dict(x=x, y=y, text=text, color=color, width=width, height=height)

    boxes = [
        box(0.5, 0.95, f"Records identified<br>OpenAlex: {data.identified_openalex}<br>"
                        f"Semantic Scholar: {data.identified_semantic_scholar}<br>"
                        f"Snowballing: {data.identified_snowballing}<br>"
                        f"<b>Total: {data.total_identified}</b>"),
        box(0.5, 0.80, f"Records after deduplication<br><b>n = {data.after_dedup}</b><br>"
                        f"({data.duplicates_removed} duplicates removed)"),
        box(0.5, 0.65, f"Records screened<br>(title & abstract)<br><b>n = {data.screened_title_abstract}</b>"),
        box(0.85, 0.65, f"Records excluded<br><b>n = {data.excluded_title_abstract}</b>", color="#7F1D1D"),
        box(0.5, 0.50, f"Full-text articles assessed<br>for eligibility<br><b>n = {data.assessed_full_text}</b>"),
        box(0.85, 0.50, f"Full-text excluded<br><b>n = {data.excluded_full_text}</b>", color="#7F1D1D"),
        box(0.5, 0.35, f"Human-in-the-loop review<br><b>n = {data.human_reviewed}</b><br>"
                        f"({data.human_excluded} excluded)") if data.human_reviewed else None,
        box(0.5, 0.18, f"Studies included<br>in final review<br><b>n = {data.included_final}</b>",
            color="#14532D"),
    ]
    boxes = [b for b in boxes if b is not None]

    shapes = []
    annotations = []

    for b in boxes:
        x0 = b["x"] - b["width"] / 2
        x1 = b["x"] + b["width"] / 2
        y0 = b["y"] - b["height"] / 2
        y1 = b["y"] + b["height"] / 2
        shapes.append(dict(
            type="rect", x0=x0, x1=x1, y0=y0, y1=y1,
            fillcolor=b["color"], line=dict(color="white", width=1),
            xref="paper", yref="paper",
        ))
        annotations.append(dict(
            x=b["x"], y=b["y"], text=b["text"],
            showarrow=False, font=dict(color="white", size=11),
            align="center", xref="paper", yref="paper",
        ))

    # Vertical arrows between main boxes
    arrow_pairs = [(0.95, 0.80), (0.80, 0.65), (0.65, 0.50)]
    if data.human_reviewed:
        arrow_pairs += [(0.50, 0.35), (0.35, 0.18)]
    else:
        arrow_pairs += [(0.50, 0.18)]

    for y_start, y_end in arrow_pairs:
        shapes.append(dict(
            type="line", x0=0.5, x1=0.5,
            y0=y_start - 0.04, y1=y_end + 0.04,
            line=dict(color="white", width=2),
            xref="paper", yref="paper",
        ))

    # Horizontal arrows to exclusion boxes
    for y_val in [0.65, 0.50]:
        shapes.append(dict(
            type="line", x0=0.72, x1=0.63,
            y0=y_val, y1=y_val,
            line=dict(color="#EF4444", width=2, dash="dot"),
            xref="paper", yref="paper",
        ))

    fig = go.Figure()
    fig.update_layout(
        shapes=shapes,
        annotations=annotations,
        xaxis=dict(visible=False, range=[0, 1]),
        yaxis=dict(visible=False, range=[0, 1]),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=10, b=10),
        height=620,
    )
    return fig
