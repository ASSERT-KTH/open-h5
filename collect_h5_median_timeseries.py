#!/usr/bin/env python3
"""Collect a rolling-window h5-index / h5-median analogue from Semantic Scholar."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import plotly.graph_objects as go

from impact_factor import RequestCache, _get, _venue_match, get_default_api_key, load_journals

API_BASE = "https://api.semanticscholar.org/graph/v1"
PUBLICATION_YEARS = list(range(2011, 2026))
WINDOW_END_YEARS = list(range(2015, 2026))


def fetch_papers_with_citations(
    venue_key: str,
    year: int,
    venues: dict[str, dict],
    api_key: str | None,
    cache: RequestCache,
    verbose: bool = False,
) -> list[dict]:
    venue_names = venues[venue_key]["venue_names"]
    papers: list[dict] = []
    token: str | None = None

    if verbose:
        print(f"  Fetching {venue_key} papers for {year}", flush=True)

    while True:
        params = {
            "fields": "paperId,title,year,venue,publicationVenue,citationCount",
            "venue": ",".join(venue_names),
            "year": str(year),
            "limit": 1000,
        }
        if token:
            params["token"] = token

        payload = _get(f"{API_BASE}/paper/search/bulk", params, api_key=api_key, cache=cache, sleep_after=1.0)
        batch = payload.get("data") or []
        for paper in batch:
            if paper.get("year") == year and _venue_match(paper, venue_names):
                papers.append(paper)

        token = payload.get("token")
        if not batch or not token:
            break

    if verbose:
        print(f"    matched {len(papers)} papers", flush=True)
    return papers


def compute_h_metrics(citation_counts: list[int]) -> tuple[int, float | None]:
    if not citation_counts:
        return 0, None
    counts = sorted(citation_counts, reverse=True)
    h = 0
    for index, count in enumerate(counts, start=1):
        if count >= index:
            h = index
        else:
            break
    if h == 0:
        return 0, 0.0
    core = counts[:h]
    core_sorted = sorted(core)
    mid = len(core_sorted) // 2
    if len(core_sorted) % 2 == 1:
        median = float(core_sorted[mid])
    else:
        median = (core_sorted[mid - 1] + core_sorted[mid]) / 2
    return h, median


def collect_rows(
    venues: dict[str, dict],
    cache_path: Path,
    api_key: str | None,
    verbose: bool,
) -> list[dict]:
    rows: list[dict] = []
    cache = RequestCache(cache_path)
    try:
        for venue_key, metadata in venues.items():
            if verbose:
                print(f"=== {venue_key} ===", flush=True)
            papers_by_year: dict[int, list[dict]] = {}
            for year in PUBLICATION_YEARS:
                papers_by_year[year] = fetch_papers_with_citations(
                    venue_key,
                    year,
                    venues,
                    api_key=api_key,
                    cache=cache,
                    verbose=verbose,
                )

            for end_year in WINDOW_END_YEARS:
                publication_years = list(range(end_year - 4, end_year + 1))
                window_papers: list[dict] = []
                for year in publication_years:
                    window_papers.extend(papers_by_year[year])

                seen: set[str] = set()
                citation_counts: list[int] = []
                for paper in window_papers:
                    paper_id = paper["paperId"]
                    if paper_id in seen:
                        continue
                    seen.add(paper_id)
                    citation_counts.append(int(paper.get("citationCount") or 0))

                h5_index, h5_median = compute_h_metrics(citation_counts)
                rows.append(
                    {
                        "venue": venue_key,
                        "venue_name": metadata["display"],
                        "label": metadata["label"],
                        "type": metadata["type"],
                        "window_end_year": end_year,
                        "publication_years": publication_years,
                        "papers_in_window": len(citation_counts),
                        "h5_index": h5_index,
                        "h5_median": h5_median,
                    }
                )
    finally:
        cache.close()
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "venue",
        "venue_name",
        "label",
        "type",
        "window_end_year",
        "publication_years",
        "papers_in_window",
        "h5_index",
        "h5_median",
    ]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(rows: list[dict], path: Path) -> None:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["venue"], []).append(row)
    payload = {
        "title": "Software Systems Venues: Rolling h5-median Over Time",
        "subtitle": "Semantic Scholar analogue using rolling 5-year publication windows",
        "window_end_years": WINDOW_END_YEARS,
        "series": [],
    }
    ordered = sorted(grouped, key=lambda key: grouped[key][-1]["h5_median"] or -1, reverse=True)
    for venue in ordered:
        venue_rows = sorted(grouped[venue], key=lambda row: row["window_end_year"])
        payload["series"].append(
            {
                "venue": venue,
                "venue_name": venue_rows[0]["venue_name"],
                "label": venue_rows[0]["label"],
                "type": venue_rows[0]["type"],
                "points": venue_rows,
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_html(rows: list[dict], path: Path) -> None:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["venue"], []).append(row)
    ordered = sorted(grouped, key=lambda key: grouped[key][-1]["h5_median"] or -1, reverse=True)
    colors = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
        "#393b79", "#637939", "#8c6d31", "#843c39", "#7b4173",
        "#3182bd", "#31a354", "#756bb1", "#636363", "#e6550d",
    ]

    fig = go.Figure()
    for index, venue in enumerate(ordered):
        venue_rows = sorted(grouped[venue], key=lambda row: row["window_end_year"])
        fig.add_trace(
            go.Scatter(
                x=[row["window_end_year"] for row in venue_rows],
                y=[row["h5_median"] for row in venue_rows],
                mode="lines+markers",
                name=venue_rows[0]["label"],
                line={
                    "color": colors[index % len(colors)],
                    "dash": "solid" if venue_rows[0]["type"] == "journal" else "dash",
                    "width": 2.5,
                },
                marker={"size": 7},
                customdata=[
                    [
                        row["venue_name"],
                        row["label"],
                        row["type"],
                        row["h5_index"],
                        row["h5_median"],
                        row["papers_in_window"],
                        row["publication_years"][0],
                        row["publication_years"][-1],
                    ]
                    for row in venue_rows
                ],
                hovertemplate=(
                    "<b>%{customdata[1]}</b><br>"
                    "Venue: %{customdata[0]}<br>"
                    "Type: %{customdata[2]}<br>"
                    "Window end year: %{x}<br>"
                    "Publication window: %{customdata[6]}-%{customdata[7]}<br>"
                    "h5-index analogue: %{customdata[3]}<br>"
                    "h5-median analogue: %{customdata[4]}<br>"
                    "Papers in window: %{customdata[5]}<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        title={
            "text": "Software Systems Venues: Rolling h5-median Over Time<br><sup>Semantic Scholar analogue using rolling 5-year publication windows</sup>",
            "x": 0.5,
        },
        template="plotly_white",
        xaxis_title="Window end year",
        yaxis_title="h5-median analogue",
        width=1600,
        height=980,
        hovermode="closest",
        legend={
            "orientation": "v",
            "x": 1.02,
            "y": 1,
            "xanchor": "left",
            "yanchor": "top",
            "font": {"size": 11},
        },
        margin={"l": 70, "r": 320, "t": 90, "b": 70},
    )
    fig.update_xaxes(tickmode="array", tickvals=WINDOW_END_YEARS)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(path, include_plotlyjs="cdn", full_html=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venues-file", default="data/software_systems_google_scholar.json")
    parser.add_argument("--cache-path", default="/home/martin/workspace/independent-impact-factor/.semanticscholar-cache.sqlite3")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--output-csv", default="results/software_systems_h5_median.csv")
    parser.add_argument("--output-json", default="results/software_systems_h5_median.json")
    parser.add_argument("--output-html", default="results/software_systems_h5_median.html")
    parser.add_argument("--venues", nargs="*", default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.api_key is None:
        args.api_key = get_default_api_key()

    venues = load_journals(args.venues_file)
    if args.venues is not None:
        venues = {key: venues[key] for key in args.venues}

    rows = collect_rows(venues, Path(args.cache_path), args.api_key, args.verbose)
    write_csv(rows, Path(args.output_csv))
    write_json(rows, Path(args.output_json))
    write_html(rows, Path(args.output_html))

    print(f"csv written: {args.output_csv}")
    print(f"json written: {args.output_json}")
    print(f"html written: {args.output_html}")


if __name__ == "__main__":
    main()
