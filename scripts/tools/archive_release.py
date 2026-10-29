"""Archive the current deploy/ build into a reproducible, hash-verified bundle."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
META = DEPLOY / "build-meta.json"
STANDALONE = ROOT / "software" / "考研核心词.html"
OUT_ROOT = ROOT / "dist" / "releases"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect() -> list[Path]:
    if not META.is_file():
        sys.exit("deploy/build-meta.json missing; run python scripts/make_html.py first")
    files = sorted(p for p in DEPLOY.rglob("*") if p.is_file())
    if STANDALONE.is_file():
        files.append(STANDALONE)
    return files


def main() -> int:
    meta = json.loads(META.read_text(encoding="utf-8"))
    build = meta["build"]
    app_asset = meta["app_asset"].lstrip("./")
    app_file = DEPLOY / app_asset
    if not app_file.is_file():
        sys.exit(f"app asset {app_asset} missing from deploy/")
    if app_file.name != app_asset or not build:
        sys.exit("build-meta.json is inconsistent")

    files = collect()
    out_dir = OUT_ROOT / build
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    lines: list[str] = []
    for src in files:
        rel = src.relative_to(ROOT)
        dst = out_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        lines.append(f"{sha256(dst)}  {rel.as_posix()}")

    manifest = out_dir / "SHA256SUMS"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")

    zip_path = OUT_ROOT / f"kaoyan2-words-{build}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(out_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(out_dir).as_posix())

    total = sum(p.stat().st_size for p in files)
    print(f"build={build}")
    print(f"source_digest={meta.get('source_digest', '')}")
    print(f"app={app_asset} sha256={sha256(app_file)}")
    print(f"files={len(files)} bytes={total}")
    print(f"manifest={manifest.relative_to(ROOT).as_posix()}")
    print(f"zip={zip_path.relative_to(ROOT).as_posix()} sha256={sha256(zip_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
