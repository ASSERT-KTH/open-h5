#!/usr/bin/env python3
"""Render interactive h5-median figures from the Google Scholar Software Systems table."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import plotly.graph_objects as go


def load_rows(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(rows: list[dict], path: Path) -> None:
    payload = {
        "title": "Software Systems Venues: Google Scholar h5-median",
        "source_note": "Values transcribed from the provided Google Scholar Software Systems table.",
        "venues": rows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_html(rows: list[dict], path: Path) -> None:
    colors = {"journal": "#1f77b4", "conference": "#ff7f0e"}
    fig = go.Figure()
    for venue_type in ("journal", "conference"):
        subset = [row for row in rows if row["type"] == venue_type]
        fig.add_trace(
            go.Bar(
                x=[row["h5_median"] for row in subset],
                y=[row["venue"] for row in subset],
                orientation="h",
                name=venue_type.title(),
                marker={"color": colors[venue_type]},
                customdata=[
                    [row["venue_name"], row["rank"], row["h5_index"], row["h5_median"], row["type"]]
                    for row in subset
                ],
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "Venue: %{customdata[0]}<br>"
                    "Type: %{customdata[4]}<br>"
                    "Google Scholar rank: %{customdata[1]}<br>"
                    "h5-index: %{customdata[2]}<br>"
                    "h5-median: %{customdata[3]}<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        title={
            "text": "Software Systems Venues: Google Scholar h5-median<br><sup>Values from the provided Google Scholar Software Systems table</sup>",
            "x": 0.5,
        },
        template="plotly_white",
        barmode="overlay",
        xaxis_title="h5-median",
        yaxis_title="Venue",
        width=1400,
        height=900,
        legend={"orientation": "h", "x": 0.5, "xanchor": "center", "y": 1.02, "yanchor": "bottom"},
        margin={"l": 200, "r": 60, "t": 100, "b": 70},
    )
    fig.update_yaxes(categoryorder="array", categoryarray=[row["venue"] for row in reversed(rows)])
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(path, include_plotlyjs="cdn", full_html=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/software_systems_google_scholar_h5.json")
    parser.add_argument("--output-json", default="results/software_systems_h5_median_latest.json")
    parser.add_argument("--output-html", default="results/software_systems_h5_median_latest.html")
    args = parser.parse_args()

    rows = load_rows(Path(args.input))
    rows = sorted(rows, key=lambda row: (row["h5_median"], row["h5_index"], -row["rank"]), reverse=True)
    write_json(rows, Path(args.output_json))
    write_html(rows, Path(args.output_html))

    print(f"json written: {args.output_json}")
    print(f"html written: {args.output_html}")


if __name__ == "__main__":
    main()
