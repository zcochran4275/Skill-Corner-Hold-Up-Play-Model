"""Download SkillCorner open data into data/raw/<match_id>/.

Events, phases of play and match JSON are plain files (~5 MB per match).
Tracking is stored in Git LFS (~90 MB per match), so it comes from
media.githubusercontent.com. Existing files of plausible size are skipped.

Usage:
    python scripts/download_data.py --no-tracking
    python scripts/download_data.py --matches 1874553 1886347
    python scripts/download_data.py
"""
import argparse
import json
from pathlib import Path

import requests

RAW = "https://raw.githubusercontent.com/SkillCorner/opendata/master/data"
MEDIA = "https://media.githubusercontent.com/media/SkillCorner/opendata/master/data"
LISTING = "https://api.github.com/repos/SkillCorner/opendata/contents/data/matches"
OUT = Path(__file__).resolve().parent.parent / "data" / "raw"

SMALL_FILES = ["match.json", "dynamic_events.csv", "phases_of_play.csv"]
TRACKING = "tracking_extrapolated.jsonl"
MIN_TRACKING_BYTES = 1_000_000  # an LFS pointer stub is ~130 bytes


def fetch(url: str, dest: Path, min_bytes: int = 0) -> bool:
    if dest.exists() and dest.stat().st_size > max(min_bytes, 0):
        print(f"  skip  {dest.name}")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    if tmp.stat().st_size < min_bytes:
        tmp.unlink()
        raise RuntimeError(f"{dest.name} is {min_bytes}+ bytes expected; got an LFS pointer?")
    tmp.replace(dest)
    print(f"  saved {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", nargs="*", help="match ids (default: all)")
    ap.add_argument("--no-tracking", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    fetch(f"{RAW}/matches.json", OUT / "matches.json")

    ids = args.matches
    if not ids:
        listing = requests.get(LISTING, timeout=30)
        listing.raise_for_status()
        ids = sorted(e["name"] for e in listing.json() if e["type"] == "dir")
    print(f"{len(ids)} matches")

    for mid in ids:
        print(mid)
        for name in SMALL_FILES:
            fetch(f"{RAW}/matches/{mid}/{mid}_{name}", OUT / mid / f"{mid}_{name}")
        if not args.no_tracking:
            fetch(f"{MEDIA}/matches/{mid}/{mid}_{TRACKING}", OUT / mid / f"{mid}_{TRACKING}", MIN_TRACKING_BYTES)


if __name__ == "__main__":
    main()
