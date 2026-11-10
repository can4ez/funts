#!/usr/bin/env python3
"""Authorized-source importer for the 'После полуночи' question bank.

Usage:
  python tools/question_importer.py --config examples/sources.example.json \
    --output questions.json --report report.json

Requires beautifulsoup4 for HTML; optional rapidfuzz speeds fuzzy matching.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import json
import re
import socket
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

try:
    from rapidfuzz import fuzz  # type: ignore
except ImportError:
    fuzz = None

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:
    BeautifulSoup = None

USER_AGENT = "AfterMidnightQuestionImporter/1.0 (authorized content only)"
MAX_BODY_BYTES = 2 * 1024 * 1024
PREFIX = re.compile(r"^\s*(?:truth|правда|dare|действие)\s*[:\-–—]\s*", re.I)
LABEL = re.compile(r"^\s*(truth|правда|dare|действие)\s*[:\-–—]\s*", re.I)
NON_WORD = re.compile(r"[^\w\s{}]+", re.UNICODE)
WS = re.compile(r"\s+")
TYPE_MAP = {"truth": "truth", "правда": "truth", "dare": "dare", "действие": "dare", "question": "truth", "challenge": "dare"}
LEVEL_MAP = {"easy": 1, "pg": 1, "normal": 1, "medium": 2, "pg13": 2, "hard": 3, "extreme": 3, "r": 3, "nsfw": 3}


def norm_text(value: str) -> str:
    s = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    s = WS.sub(" ", NON_WORD.sub(" ", s)).strip()
    return s


def strip_prefix(text: str) -> tuple[str | None, str]:
    match = LABEL.match(text)
    guessed = TYPE_MAP.get(match.group(1).casefold()) if match else None
    return guessed, PREFIX.sub("", text).strip()


def stable_id(kind: str, text: str) -> str:
    return "ext-" + hashlib.sha256(f"{kind}\0{norm_text(text)}".encode("utf-8")).hexdigest()[:20]


def as_bool(value: Any) -> bool:
    return value is True or str(value).strip().casefold() in {"1", "yes", "true", "да"}


def get_path(obj: Any, dotted: str | None) -> Any:
    if not dotted:
        return obj
    for part in dotted.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, (list, tuple)) and part.isdigit():
            idx = int(part)
            obj = obj[idx] if idx < len(obj) else None
        else:
            return None
    return obj


def infer_rows(data: Any, source: dict) -> list[Any]:
    rows = get_path(data, source.get("record_path"))
    if not source.get("record_path") and isinstance(rows, dict):
        for key in ("cards", "questions", "data", "results", "messages", "prompts", "items"):
            if isinstance(rows.get(key), list):
                rows = rows[key]
                break
    if not isinstance(rows, list):
        raise ValueError("Cannot find a list of records; set record_path in source config")
    return rows


def to_card(row: Any, source: dict, source_url: str) -> dict | None:
    if isinstance(row, str):
        raw = row
        row = {}
    elif isinstance(row, dict):
        if source.get("filter_field") and str(get_path(row, source["filter_field"])) != str(source.get("filter_value")):
            return None
        raw = get_path(row, source.get("text_field") or "text")
        if raw is None:
            raw = next((row[k] for k in ("question", "prompt", "sentence", "content", "title") if isinstance(row.get(k), str)), None)
        if isinstance(raw, dict):
            raw = raw.get("text")
    else:
        return None
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    prefix_type, text = strip_prefix(raw)
    text = re.sub(r"^\d{1,4}[.)]\s+", "", text).strip()
    declared_type = get_path(row, source["type_field"]) if source.get("type_field") else source.get("type")
    typ = TYPE_MAP.get(str(declared_type or "").casefold(), prefix_type)
    level_raw = get_path(row, source.get("level_field")) if source.get("level_field") else source.get("level", 2)
    try:
        level = LEVEL_MAP.get(str(level_raw).casefold(), int(level_raw) if str(level_raw).isdigit() else 2)
    except (ValueError, TypeError):
        level = 2
    touch = as_bool(get_path(row, source.get("touch_field"))) if source.get("touch_field") else as_bool(source.get("touch", False))
    if not typ or level not in (1, 2, 3) or not (6 <= len(text) <= 350):
        return {"_invalid": True, "source": source.get("id", "?"), "text": text[:100], "reason": "missing type, invalid level or text length"}
    return {"id": stable_id(typ, text), "text": text, "type": typ, "level": level, "touch": touch,
            "source": source["id"], "source_url": source_url, "license": source.get("license", "unspecified")}


def is_public_https(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    hostname = parsed.hostname
    if hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(hostname)
        return ip.is_global
    except ValueError:
        return True


def fetch_text(url: str, robots_cache: dict, last_request: dict, delay: float) -> str:
    if not is_public_https(url):
        raise ValueError("Remote sources must use public https URLs (no local or private IP addresses)")
    u = urllib.parse.urlparse(url)
    origin = f"{u.scheme}://{u.netloc}"
    if origin not in robots_cache:
        robots_url = origin + "/robots.txt"
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        try:
            with urllib.request.urlopen(urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT}), timeout=12) as res:
                text = res.read(128_000).decode("utf-8", "replace")
                parser.parse(text.splitlines())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                parser.parse([])  # No robots file: no rules for this agent
            else:
                raise PermissionError(f"robots.txt unavailable ({exc.code}); refusing to crawl {origin}") from exc
        except Exception as exc:
            raise PermissionError(f"Cannot read robots.txt for {origin}: {exc}") from exc
        robots_cache[origin] = parser
    parser = robots_cache[origin]
    if not parser.can_fetch(USER_AGENT, url):
        raise PermissionError(f"robots.txt prohibits fetching {url}")
    pause = max(float(delay), float(parser.crawl_delay(USER_AGENT) or 0), 1.0)
    elapsed = time.monotonic() - last_request.get(origin, 0)
    if elapsed < pause:
        time.sleep(pause - elapsed)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/html,text/csv;q=0.9,*/*;q=0.3"})
    with urllib.request.urlopen(req, timeout=20) as res:
        redirected = res.geturl()
        if not is_public_https(redirected):
            raise PermissionError("Unsafe redirected location")
        # Do not follow cross-origin page redirects silently; protect against robots policy changes.
        redirect_origin = urllib.parse.urlparse(redirected).netloc
        if redirect_origin != u.netloc:
            raise PermissionError(f"Cross-origin redirect to {redirect_origin}; download the authorized dataset locally instead")
        size = int(res.headers.get("Content-Length", "0") or 0)
        if size > MAX_BODY_BYTES:
            raise ValueError(f"Remote response too large ({size} bytes)")
        payload = res.read(MAX_BODY_BYTES + 1)
    if len(payload) > MAX_BODY_BYTES:
        raise ValueError("Remote response exceeds 2MB limit")
    last_request[origin] = time.monotonic()
    return payload.decode("utf-8-sig", "replace")


def parse_html(document: str, source: dict, url: str) -> list[dict]:
    if BeautifulSoup is None:
        raise RuntimeError("HTML parsing requires: pip install beautifulsoup4")
    soup = BeautifulSoup(document, "html.parser")
    blocks = source.get("selectors") or [{"selector": source.get("selector"), "type": source.get("type"), "level": source.get("level", 2)}]
    rows = []
    for block in blocks:
        if not block.get("selector"):
            raise ValueError(f"Missing CSS selector for HTML source {source['id']}")
        effective = {**source, **block}
        for element in soup.select(block["selector"]):
            text = element.get_text(" ", strip=True)
            row = to_card(text, effective, url)
            if row is not None:
                rows.append(row)
    return rows


def read_source(source: dict, base_dir: Path, robots_cache: dict, last_request: dict, delay: float) -> list[dict]:
    if not source.get("enabled", True):
        return []
    kind = source.get("kind", "json").lower()
    locations = source.get("urls") or ([source["url"]] if source.get("url") else [source.get("path")])
    records = []
    for loc in locations:
        if not loc:
            raise ValueError(f"Missing URL/path for {source.get('id')}")
        if str(loc).startswith(("https://", "http://")):
            if source.get("approved") is not True or not source.get("license") or not source.get("permission_note"):
                raise PermissionError(f"Remote source '{source.get('id')}' needs approved=true, license and permission_note")
            content = fetch_text(str(loc), robots_cache, last_request, delay)
            url = str(loc)
        else:
            path = (base_dir / str(loc)).resolve()
            content = path.read_text(encoding="utf-8-sig")
            url = source.get("source_url") or path.as_uri()
        if kind == "html":
            records.extend(parse_html(content, source, url))
        elif kind in ("json", "api"):
            rows = infer_rows(json.loads(content), source)
            for row in rows:
                card = to_card(row, source, source.get("source_url") or url)
                if card is not None:
                    records.append(card)
        elif kind == "csv":
            rows = csv.DictReader(content.splitlines(), delimiter=source.get("delimiter", ","))
            for row in rows:
                card = to_card(row, source, source.get("source_url") or url)
                if card is not None:
                    records.append(card)
        else:
            raise ValueError(f"Unsupported kind: {kind}")
    return records


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if fuzz is not None:
        return max(float(fuzz.ratio(a, b)), float(fuzz.token_sort_ratio(a, b))) / 100
    return max(SequenceMatcher(None, a, b).ratio(), SequenceMatcher(None, " ".join(sorted(a.split())), " ".join(sorted(b.split()))).ratio())


def deduplicate(cards: Iterable[dict], existing: Iterable[dict] = (), hard: float = 0.93, review: float = 0.83) -> dict:
    """Preserve first occurrence. Very close matches are removed; borderline cases go to review."""
    if not 0.5 < review < hard <= 1.0:
        raise ValueError("Need 0.5 < review < hard <= 1.0")
    kept: list[dict] = []
    seeded: list[dict] = []
    duplicates: list[dict] = []
    review_items: list[dict] = []
    invalid: list[dict] = []
    norm_to_card: dict[tuple[str, str], dict] = {}
    token_index: dict[tuple[str, str], set[int]] = defaultdict(set)
    compare_set: list[tuple[dict, str]] = []

    def register(card: dict) -> None:
        key = (card["type"], norm_text(card["text"]))
        norm_to_card[key] = card
        idx = len(compare_set)
        compare_set.append((card, key[1]))
        # Invert distinctive words. First 10 longest tokens work across word reordering.
        for token in sorted({s for s in key[1].split() if len(s) >= 4}, key=lambda s: (-len(s), s))[:10]:
            token_index[(key[0], token)].add(idx)

    for base in existing:
        if isinstance(base, dict) and base.get("type") in ("truth", "dare") and isinstance(base.get("text"), str):
            seeded.append(base)
            register(base)

    for card in cards:
        if not isinstance(card, dict) or card.get("_invalid"):
            invalid.append(card if isinstance(card, dict) else {"reason": "not an object"})
            continue
        key = (card["type"], norm_text(card["text"]))
        if not key[1]:
            invalid.append({"reason": "empty normalized text", "card": card})
            continue
        if key in norm_to_card:
            other = norm_to_card[key]
            duplicates.append({"kind": "exact", "item": card, "matches": other, "score": 1.0})
            continue
        tokens = sorted({t for t in key[1].split() if len(t) >= 4}, key=lambda s: (-len(s), s))[:10]
        candidate_ids: set[int] = set()
        for token in tokens:
            candidate_ids.update(token_index.get((key[0], token), ()))
        best = (0.0, None)
        for idx in candidate_ids:
            other, normalized = compare_set[idx]
            ratio = min(len(key[1]), len(normalized)) / max(len(key[1]), len(normalized))
            if ratio < 0.7:
                continue
            score = similarity(key[1], normalized)
            if score > best[0]:
                best = (score, other)
        if best[0] >= hard:
            duplicates.append({"kind": "near", "item": card, "matches": best[1], "score": round(best[0], 4)})
        else:
            if best[0] >= review:
                review_items.append({"item": card, "possible_match": best[1], "score": round(best[0], 4)})
            kept.append(card)
            register(card)
    return {"cards": kept, "duplicates": duplicates, "review": review_items, "invalid": invalid,
            "stats": {"already_existing": len(seeded), "accepted": len(kept), "removed": len(duplicates), "review": len(review_items), "invalid": len(invalid)}}


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description="Import, normalize and deduplicate authorized Truth or Dare questions")
    cli.add_argument("--config", type=Path, required=True, help="JSON source manifest")
    cli.add_argument("--output", type=Path, default=Path("question-bank.json"))
    cli.add_argument("--report", type=Path, default=Path("question-report.json"))
    cli.add_argument("--existing", type=Path, help="Existing exported JSON bank to deduplicate against")
    cli.add_argument("--hard", type=float, default=0.93, help="Auto-reject near match similarity (default 0.93)")
    cli.add_argument("--review", type=float, default=0.83, help="Flag similarity for manual review (default 0.83)")
    cli.add_argument("--delay", type=float, default=2.0, help="Min seconds between requests per host")
    cli.add_argument("--hold-review", action="store_true", help="Exclude possible near-duplicates requiring manual review from published output")
    args = cli.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if not isinstance(config.get("sources"), list):
        cli.error("Config must contain sources array")
    ids = [s.get("id") for s in config["sources"]]
    if len(ids) != len(set(ids)) or any(not i for i in ids):
        cli.error("Each source needs a unique id")
    if args.existing:
        old = json.loads(args.existing.read_text(encoding="utf-8-sig"))
        existing = old if isinstance(old, list) else old.get("cards", [])
    else:
        existing = []
    all_cards = []
    robots_cache: dict = {}
    last_request: dict = {}
    source_errors = []
    counts: dict[str, int] = {}
    for spec in config["sources"]:
        if not spec.get("enabled", True):
            continue
        try:
            cards = read_source(spec, args.config.parent, robots_cache, last_request, max(args.delay, 1.0))
            all_cards.extend(cards)
            counts[spec["id"]] = len(cards)
            print(f"{spec['id']}: extracted {len(cards)}", file=sys.stderr)
        except Exception as exc:
            source_errors.append({"source": spec.get("id"), "error": str(exc)})
            print(f"{spec.get('id')}: FAILED: {exc}", file=sys.stderr)
    result = deduplicate(all_cards, existing, hard=args.hard, review=args.review)
    if args.hold_review:
        hold_keys = {(item["item"]["type"], norm_text(item["item"]["text"])) for item in result["review"]}
        result["cards"] = [card for card in result["cards"] if (card["type"], norm_text(card["text"])) not in hold_keys]
        result["stats"]["accepted"] = len(result["cards"])
        result["stats"]["held_for_review"] = len(hold_keys)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"version": 1, "cards": result["cards"]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {"stats": {"source_records": len(all_cards), **result["stats"]}, "by_source": counts, "duplicates": result["duplicates"], "review": result["review"], "invalid": result["invalid"], "source_errors": source_errors}
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"stats": report["stats"], "by_source": counts, "source_errors": source_errors}, ensure_ascii=False, indent=2))
    return 1 if source_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
