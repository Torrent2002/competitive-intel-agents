"""Command-line entrypoint."""

from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="competitive-intel")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--input", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        input_path = Path(args.input)
        if not input_path.exists():
            parser.error(f"input file does not exist: {input_path}")
        print(f"Loaded request: {input_path}")
        return 0

    parser.print_help()
    return 0

