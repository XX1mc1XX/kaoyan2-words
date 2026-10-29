#!/usr/bin/env python3
"""Fetch the public dictionary inputs ignored by git, with pinned integrity."""

from __future__ import annotations

import hashlib
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CHUNK_SIZE = 1024 * 1024

# skywind3000/ECDICT master at the time these immutable Git blobs were pinned.
UPSTREAM_COMMIT = "ab22ad36302cafc6349a050e2b60894855208055"
FILES = (
    {
        "path": DATA / "ecdict.csv",
        "blob": "0e527e22e0e0d22f012b0ed251a8dddd5891773b",
        "name": "ecdict.csv",
        "size": 66009548,
        "sha256": "D1ECBDF9EE2B920AFB6F430CA6B6BB9F559588CF0DFF86E04BD255F9390843CC",
    },
    {
        "path": DATA / "lemma.en.txt",
        "blob": "34eabb9f48c5867a91c01c33b206120e275f0418",
        "name": "lemma.en.txt",
        "size": 2318694,
        "sha256": "E255B097404E3E0052060E2DDF6E15A1414F577071D63D51D2CA0CE9DACEE0FC",
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def download_from_url(
    url: str,
    target: Path,
    partial: Path,
    expected_size: int,
    expected_sha: str,
) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github.raw+json",
            "User-Agent": "kaoyan-vocabulary-ci/1.0",
        },
    )
    digest = hashlib.sha256()
    received = 0
    try:
        with urllib.request.urlopen(request, timeout=180) as response, partial.open("wb") as output:
            status = getattr(response, "status", 200)
            if status != 200:
                raise RuntimeError(f"HTTP {status}")
            for chunk in iter(lambda: response.read(CHUNK_SIZE), b""):
                output.write(chunk)
                digest.update(chunk)
                received += len(chunk)
        actual_sha = digest.hexdigest().upper()
        if received != expected_size:
            raise RuntimeError(f"size {received} != {expected_size}")
        if actual_sha != expected_sha:
            raise RuntimeError(f"sha256 {actual_sha} != {expected_sha}")
        os.replace(partial, target)
        return actual_sha
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def download(item: dict[str, object]) -> None:
    target = item["path"]
    expected_size = item["size"]
    expected_sha = item["sha256"]
    filename = item["name"]
    assert isinstance(target, Path)
    assert isinstance(expected_size, int)
    assert isinstance(expected_sha, str)
    assert isinstance(filename, str)

    partial = target.with_suffix(target.suffix + ".part")
    target.parent.mkdir(parents=True, exist_ok=True)
    if partial.exists():
        partial.unlink()

    api_url = "https://api.github.com/repos/skywind3000/ECDICT/git/blobs/" + str(item["blob"])
    raw_url = f"https://raw.githubusercontent.com/skywind3000/ECDICT/{UPSTREAM_COMMIT}/{filename}"
    errors = []
    for url in (api_url, raw_url):
        print(f"download {target.relative_to(ROOT)} from {url}", flush=True)
        try:
            actual_sha = download_from_url(url, target, partial, expected_size, expected_sha)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            print(f"warning: download failed: {exc}", file=sys.stderr, flush=True)
            continue
        print(f"verified {target.relative_to(ROOT)} sha256={actual_sha}", flush=True)
        return
    raise RuntimeError("all download sources failed: " + " | ".join(errors))


def main() -> int:
    for item in FILES:
        target = item["path"]
        expected_sha = item["sha256"]
        assert isinstance(target, Path)
        assert isinstance(expected_sha, str)
        if target.exists():
            actual_sha = sha256(target)
            if actual_sha != expected_sha:
                raise RuntimeError(
                    f"{target.relative_to(ROOT)} exists with sha256={actual_sha}, "
                    f"expected {expected_sha}; refusing to overwrite it"
                )
            print(f"verified existing {target.relative_to(ROOT)} sha256={actual_sha}", flush=True)
            continue
        download(item)
    print(f"public build inputs ready (ECDICT {UPSTREAM_COMMIT[:12]})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
