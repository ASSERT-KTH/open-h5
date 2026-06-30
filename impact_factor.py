#!/usr/bin/env python3
"""Compute journal impact-factor inputs from the Semantic Scholar API."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

import requests

API_BASE = "https://api.semanticscholar.org/graph/v1"
RETRY_DELAYS = [10, 30, 60]

try:
    import keyring
except Exception:
    keyring = None


def load_journals(journals_file: str | Path) -> dict[str, dict]:
    with open(journals_file, encoding="utf-8") as fh:
        return json.load(fh)


def get_default_api_key() -> Optional[str]:
    if keyring is None:
        return None
    try:
        return keyring.get_password("login2", "semanticscholar_key")
    except Exception:
        return None


class RequestCache:
    """Persistent cache for Semantic Scholar API GET responses."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if self.path.parent != Path("."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS request_cache (
                cache_key TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                params_json TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.conn.commit()

    @staticmethod
    def _cache_key(url: str, params: dict) -> str:
        payload = json.dumps(
            {"url": url, "params": params},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, url: str, params: dict) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT response_json FROM request_cache WHERE cache_key = ?",
            (self._cache_key(url, params),),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def set(self, url: str, params: dict, response: dict) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO request_cache
                (cache_key, url, params_json, response_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                self._cache_key(url, params),
                url,
                json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
                json.dumps(response, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def _get(
    url: str,
    params: dict,
    api_key: Optional[str] = None,
    cache: Optional[RequestCache] = None,
    sleep_after: float = 0.0,
) -> dict:
    if cache is not None:
        cached = cache.get(url, params)
        if cached is not None:
            return cached

    headers: dict[str, str] = {}
    if api_key:
        headers["x-api-key"] = api_key

    for attempt, delay in enumerate([0] + RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            response = requests.get(url, params=params, headers=headers, timeout=60)
            if response.status_code == 429:
                wait = int(response.headers.get("Retry-After", 60))
                print(f"    [rate-limited] sleeping {wait}s", flush=True)
                time.sleep(wait)
                continue
            response.raise_for_status()
            payload = response.json()
            if cache is not None:
                cache.set(url, params, payload)
            if sleep_after > 0:
                time.sleep(sleep_after)
            return payload
        except requests.RequestException as exc:
            if attempt == len(RETRY_DELAYS):
                raise
            print(f"    [warning] request failed ({exc}); retrying", flush=True)
    return {}


def _venue_match(paper: dict, venue_names: list[str]) -> bool:
    candidates: list[str] = []

    raw_venue = (paper.get("venue") or "").strip()
    if raw_venue:
        candidates.append(raw_venue)

    publication_venue = paper.get("publicationVenue") or {}
    publication_name = (publication_venue.get("name") or "").strip()
    if publication_name:
        candidates.append(publication_name)

    for candidate in candidates:
        candidate_lower = candidate.lower()
        for target in venue_names:
            target_lower = target.lower()
            if target_lower in candidate_lower or candidate_lower in target_lower:
                return True
    return False


def publication_years(citation_year: int, window_years: int = 2) -> list[int]:
    if window_years < 1:
        raise ValueError("window_years must be at least 1")
    start_year = citation_year - window_years
    return list(range(start_year, citation_year))


def fetch_papers(
    journal_key: str,
    year: int,
    journals: dict[str, dict],
    api_key: Optional[str] = None,
    cache: Optional[RequestCache] = None,
    verbose: bool = False,
) -> list[dict]:
    venue_names = journals[journal_key]["venue_names"]
    papers: list[dict] = []
    token: Optional[str] = None

    if verbose:
        print(f"  Fetching {journal_key} papers for {year}", flush=True)

    while True:
        params = {
            "fields": "paperId,title,year,venue,publicationVenue",
            "venue": ",".join(venue_names),
            "year": str(year),
            "limit": 1000,
        }
        if token:
            params["token"] = token

        payload = _get(
            f"{API_BASE}/paper/search/bulk",
            params,
            api_key=api_key,
            cache=cache,
            sleep_after=1.0,
        )

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


def count_citations_in_year(
    paper_id: str,
    target_year: int,
    journal_only: bool = False,
    api_key: Optional[str] = None,
    cache: Optional[RequestCache] = None,
) -> int:
    count = 0
    offset = 0
    fields = "year,publicationTypes" if journal_only else "year"

    while True:
        params = {
            "fields": fields,
            "offset": offset,
            "limit": 1000,
        }
        payload = _get(
            f"{API_BASE}/paper/{paper_id}/citations",
            params,
            api_key=api_key,
            cache=cache,
            sleep_after=0.5,
        )

        batch = payload.get("data") or []
        for item in batch:
            citing = item.get("citingPaper") or {}
            if citing.get("year") != target_year:
                continue
            if journal_only:
                publication_types = citing.get("publicationTypes") or []
                if "JournalArticle" not in publication_types:
                    continue
            count += 1

        if len(batch) < 1000:
            break
        offset += 1000

    return count


def count_citations_by_year(
    paper_id: str,
    target_years: list[int],
    api_key: Optional[str] = None,
    cache: Optional[RequestCache] = None,
) -> tuple[dict[int, int], dict[int, int]]:
    """Return citing-paper counts for multiple years in one pass.

    The first dictionary counts all citing paper types. The second counts only
    citing papers whose ``publicationTypes`` include ``JournalArticle``.
    """
    all_counts = {year: 0 for year in target_years}
    journal_counts = {year: 0 for year in target_years}
    target_year_set = set(target_years)

    offset = 0
    while True:
        params = {
            "fields": "year,publicationTypes",
            "offset": offset,
            "limit": 1000,
        }
        payload = _get(
            f"{API_BASE}/paper/{paper_id}/citations",
            params,
            api_key=api_key,
            cache=cache,
            sleep_after=0.5,
        )

        batch = payload.get("data") or []
        for item in batch:
            citing = item.get("citingPaper") or {}
            year = citing.get("year")
            if year not in target_year_set:
                continue
            all_counts[year] += 1
            publication_types = citing.get("publicationTypes") or []
            if "JournalArticle" in publication_types:
                journal_counts[year] += 1

        if len(batch) < 1000:
            break
        offset += 1000

    return all_counts, journal_counts


def compute_impact_factor(
    journal_key: str,
    citation_year: int,
    journals: dict[str, dict],
    journal_only: bool = False,
    window_years: int = 2,
    api_key: Optional[str] = None,
    cache: Optional[RequestCache] = None,
    verbose: bool = False,
) -> dict:
    metadata = journals[journal_key]
    years = publication_years(citation_year, window_years=window_years)

    all_papers: list[dict] = []
    for year in years:
        all_papers.extend(fetch_papers(journal_key, year, journals, api_key, cache, verbose))

    unique_papers: list[dict] = []
    seen: set[str] = set()
    for paper in all_papers:
        paper_id = paper["paperId"]
        if paper_id not in seen:
            seen.add(paper_id)
            unique_papers.append(paper)

    if verbose:
        print(
            f"  Counting citations for {journal_key} {citation_year} "
            f"({len(unique_papers)} papers, mode={'wos_replica' if journal_only else 'extended'})",
            flush=True,
        )

    total_citations = 0
    for index, paper in enumerate(unique_papers, start=1):
        if verbose:
            if index == 1 or index % 25 == 0 or index == len(unique_papers):
                print(f"    progress {index}/{len(unique_papers)}", flush=True)
        total_citations += count_citations_in_year(
            paper["paperId"],
            citation_year,
            journal_only=journal_only,
            api_key=api_key,
            cache=cache,
        )

    paper_count = len(unique_papers)
    impact_factor = None
    if paper_count:
        impact_factor = round(total_citations / paper_count, 4)

    return {
        "journal": journal_key,
        "journal_name": metadata["display"],
        "field": metadata.get("field"),
        "publisher": metadata.get("publisher"),
        "citation_year": citation_year,
        "publication_years": years,
        "window_years": window_years,
        "mode": "wos_replica" if journal_only else "extended",
        "papers_in_window": paper_count,
        "citations_in_year": total_citations,
        "impact_factor": impact_factor,
    }
