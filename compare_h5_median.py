#!/usr/bin/env python3
"""Compare Google Scholar h5-median to the recomputed Semantic Scholar analogue."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go


def load_google_table(html_path: Path) -> pd.DataFrame:
    tables = pd.read_html(html_path)
    if not tables:
        raise SystemExit(f"No tables found in {html_path}")
    df = tables[0].copy()
    df = df.rename(
        columns={
            df.columns[0]: "rank",
            "Publication": "venue_name",
            "h5-index": "google_h5_index",
            "h5-median": "google_h5_median",
        }
    )
    df["rank"] = df["rank"].astype(float).astype(int)
    df["google_h5_index"] = df["google_h5_index"].astype(int)
    df["google_h5_median"] = df["google_h5_median"].astype(int)
    return df[["rank", "venue_name", "google_h5_index", "google_h5_median"]]


def load_label_map(path: Path) -> dict[str, dict]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {row["venue_name"]: row for row in rows}


def load_recomputed_latest(csv_path: Path, window_end_year: int) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df = df[df["window_end_year"] == window_end_year].copy()
    df = df.drop(columns=["venue"])
    df = df.rename(
        columns={
            "venue_name": "recomputed_venue_name",
            "label": "venue",
            "type": "venue_type",
            "h5_index": "recomputed_h5_index",
            "h5_median": "recomputed_h5_median",
        }
    )
    return df[
        [
            "venue",
            "recomputed_venue_name",
            "venue_type",
            "recomputed_h5_index",
            "recomputed_h5_median",
            "papers_in_window",
            "publication_years",
        ]
    ]


def build_comparison(
    google_html: Path,
    label_json: Path,
    recomputed_csv: Path,
    window_end_year: int,
) -> pd.DataFrame:
    google = load_google_table(google_html)
    label_map = load_label_map(label_json)
    google["venue"] = google["venue_name"].map(lambda name: label_map[name]["venue"])
    google["venue_type"] = google["venue_name"].map(lambda name: label_map[name]["type"])

    recomputed = load_recomputed_latest(recomputed_csv, window_end_year)
    merged = google.merge(recomputed, on=["venue", "venue_type"], how="left")
    merged["median_difference"] = merged["recomputed_h5_median"] - merged["google_h5_median"]
    merged["median_ratio"] = merged["recomputed_h5_median"] / merged["google_h5_median"]
    merged["index_difference"] = merged["recomputed_h5_index"] - merged["google_h5_index"]
    return merged.sort_values("rank").reset_index(drop=True)


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def write_json(df: pd.DataFrame, path: Path, window_end_year: int) -> None:
    payload = {
        "comparison_window": f"{window_end_year - 4}-{window_end_year}",
        "rows": df.replace({np.nan: None}).to_dict(orient="records"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_markdown(df: pd.DataFrame, path: Path, window_end_year: int) -> None:
    pearson = df["google_h5_median"].corr(df["recomputed_h5_median"], method="pearson")
    spearman = df["google_h5_median"].corr(df["recomputed_h5_median"], method="spearman")
    mean_diff = df["median_difference"].mean()
    median_diff = df["median_difference"].median()

    lines = [
        "# Google Scholar vs Recomputed h5-median",
        "",
        f"- Google Scholar file: `Software Systems - Google Scholar Metrics - 20260630.html`",
        f"- Recomputed comparison window: `{window_end_year - 4}-{window_end_year}`",
        "- Recomputed values use the Semantic Scholar rolling-window h5-median analogue.",
        f"- Pearson correlation: `{pearson:.4f}`",
        f"- Spearman correlation: `{spearman:.4f}`",
        f"- Mean difference (recomputed - Google): `{mean_diff:.2f}`",
        f"- Median difference (recomputed - Google): `{median_diff:.2f}`",
        "",
        "| Rank | Venue | Type | Google h5-index | Google h5-median | Recomputed h5-index | Recomputed h5-median | Difference | Ratio |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in df.itertuples(index=False):
        rec_idx = "NA" if pd.isna(row.recomputed_h5_index) else str(int(row.recomputed_h5_index))
        rec_med = "NA" if pd.isna(row.recomputed_h5_median) else f"{row.recomputed_h5_median:.1f}"
        diff = "NA" if pd.isna(row.median_difference) else f"{row.median_difference:.1f}"
        ratio = "NA" if pd.isna(row.median_ratio) else f"{row.median_ratio:.3f}"
        lines.append(
            f"| {row.rank} | {row.venue} | {row.venue_type} | {row.google_h5_index} | {row.google_h5_median} | "
            f"{rec_idx} | {rec_med} | {diff} | {ratio} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_scatter_html(df: pd.DataFrame, path: Path) -> None:
    colors = {"journal": "#1f77b4", "conference": "#ff7f0e"}
    fig = go.Figure()
    for venue_type in ("journal", "conference"):
        sub = df[df["venue_type"] == venue_type]
        fig.add_trace(
            go.Scatter(
                x=sub["google_h5_median"],
                y=sub["recomputed_h5_median"],
                mode="markers+text",
                name=venue_type.title(),
                text=sub["venue"],
                textposition="top center",
                marker={"size": 10, "color": colors[venue_type]},
                customdata=np.column_stack(
                    [
                        sub["recomputed_venue_name"],
                        sub["google_h5_index"],
                        sub["recomputed_h5_index"],
                        sub["median_difference"],
                        sub["median_ratio"],
                    ]
                ),
                hovertemplate=(
                    "<b>%{text}</b><br>"
                    "Venue: %{customdata[0]}<br>"
                    "Google h5-median: %{x}<br>"
                    "Recomputed h5-median: %{y}<br>"
                    "Google h5-index: %{customdata[1]}<br>"
                    "Recomputed h5-index: %{customdata[2]}<br>"
                    "Difference: %{customdata[3]:.1f}<br>"
                    "Ratio: %{customdata[4]:.3f}<extra></extra>"
                ),
            )
        )

    min_val = float(min(df["google_h5_median"].min(), df["recomputed_h5_median"].min()))
    max_val = float(max(df["google_h5_median"].max(), df["recomputed_h5_median"].max()))
    fig.add_trace(
        go.Scatter(
            x=[min_val, max_val],
            y=[min_val, max_val],
            mode="lines",
            name="y = x",
            line={"color": "#666666", "dash": "dash"},
            hoverinfo="skip",
        )
    )

    fig.update_layout(
        title={
            "text": "Google Scholar vs Recomputed h5-median<br><sup>x = Google Scholar h5-median, y = recomputed Semantic Scholar analogue for 2020-2024</sup>",
            "x": 0.5,
        },
        template="plotly_white",
        xaxis_title="Google Scholar h5-median",
        yaxis_title="Recomputed h5-median",
        width=1200,
        height=900,
        hovermode="closest",
        legend={"orientation": "h", "x": 0.5, "xanchor": "center", "y": 1.02, "yanchor": "bottom"},
        margin={"l": 80, "r": 40, "t": 90, "b": 80},
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(0,0,0,0.08)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(0,0,0,0.08)")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(path, include_plotlyjs="cdn", full_html=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--google-html", default="Software Systems - Google Scholar Metrics - 20260630.html")
    parser.add_argument("--google-labels", default="data/software_systems_google_scholar_h5.json")
    parser.add_argument("--recomputed-csv", default="results/software_systems_h5_median.csv")
    parser.add_argument("--window-end-year", type=int, default=2024)
    parser.add_argument("--output-prefix", default="results/software_systems_h5_median_comparison")
    args = parser.parse_args()

    df = build_comparison(
        Path(args.google_html),
        Path(args.google_labels),
        Path(args.recomputed_csv),
        args.window_end_year,
    )

    prefix = Path(args.output_prefix)
    write_csv(df, prefix.with_suffix(".csv"))
    write_json(df, prefix.with_suffix(".json"), args.window_end_year)
    write_markdown(df, prefix.with_suffix(".md"), args.window_end_year)
    write_scatter_html(df, prefix.with_suffix(".html"))

    print(f"csv written: {prefix.with_suffix('.csv')}")
    print(f"json written: {prefix.with_suffix('.json')}")
    print(f"markdown written: {prefix.with_suffix('.md')}")
    print(f"html written: {prefix.with_suffix('.html')}")


if __name__ == "__main__":
    main()
