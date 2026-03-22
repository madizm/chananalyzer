"""
Build deployable artifacts for the public site.

Outputs:
    dist/site/      - static frontend + published JSON
    dist/release/   - optional feedback service binary for Linux deployment
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_WEB_DIR = PROJECT_ROOT / "public-web"
PUBLISH_DIR = PROJECT_ROOT / "dist" / "publish"
SITE_DIR = PROJECT_ROOT / "dist" / "site"
RELEASE_DIR = PROJECT_ROOT / "dist" / "release"
FEEDBACK_DIR = PROJECT_ROOT / "feedback-service"
DEFAULT_GO_CACHE = Path("/tmp/chanalyzer-go-cache")


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def copy_tree_contents(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def build_site() -> None:
    if not PUBLIC_WEB_DIR.exists():
        raise FileNotFoundError(f"Missing static frontend directory: {PUBLIC_WEB_DIR}")
    if not PUBLISH_DIR.exists():
        raise FileNotFoundError(
            f"Missing published JSON directory: {PUBLISH_DIR}. "
            "Run scripts/export_public_results.py first."
        )

    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    SITE_DIR.mkdir(parents=True, exist_ok=True)

    copy_tree_contents(PUBLIC_WEB_DIR, SITE_DIR)
    for filename in ("buy_scan_results.json", "sell_scan_results.json", "manifest.json"):
        shutil.copy2(PUBLISH_DIR / filename, SITE_DIR / filename)


def build_feedback_binary(goos: str, goarch: str) -> Path:
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    output = RELEASE_DIR / f"feedback-service-{goos}-{goarch}"
    DEFAULT_GO_CACHE.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "GOOS": goos,
        "GOARCH": goarch,
        "CGO_ENABLED": "0",
        "GOCACHE": os.environ.get("GOCACHE", str(DEFAULT_GO_CACHE)),
    }
    run(["go", "build", "-o", str(output), "."], cwd=FEEDBACK_DIR, env=env)
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build public site deployment artifacts")
    parser.add_argument(
        "--skip-feedback-build",
        action="store_true",
        help="Only build dist/site and skip the Go feedback binary",
    )
    parser.add_argument("--goos", default="linux", help="GOOS for the feedback binary")
    parser.add_argument("--goarch", default="amd64", help="GOARCH for the feedback binary")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_site()
    print(f"Built static site at {SITE_DIR}")

    if not args.skip_feedback_build:
        binary = build_feedback_binary(args.goos, args.goarch)
        print(f"Built feedback binary at {binary}")


if __name__ == "__main__":
    main()
