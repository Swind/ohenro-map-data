"""Command-line interface: fetch (default) and normalize subcommands."""

from __future__ import annotations

import sys

from arukihenro_routes.fetch import main as fetch_main
from arukihenro_routes.normalize import normalize_archive

_SUBCOMMANDS = ("fetch", "normalize")


def _normalize_main(argv) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="arukihenro_routes normalize", description=normalize_archive.__doc__)
    parser.add_argument("--data-dir", default="source/arukihenro-routes")
    parser.add_argument("--output", default="output/arukihenro-routes.json")
    args = parser.parse_args(argv)
    summary = normalize_archive(args.data_dir, args.output)
    print(
        "normalize: routes=%d maps=%d lines=%d points=%d photos=%d warnings=%d"
        % (
            summary["route_count"],
            summary["map_count"],
            summary["line_count"],
            summary["point_count"],
            summary["photo_point_count"],
            summary["warning_count"],
        )
    )
    return 0


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in _SUBCOMMANDS:
        subcommand = args.pop(0)
    else:
        subcommand = "fetch"
    if subcommand == "normalize":
        return _normalize_main(args)
    return fetch_main(args)