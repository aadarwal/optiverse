"""CLI subcommand for AI layout generation."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path


def build_parser(subparsers: argparse._SubParsersAction | None = None) -> argparse.ArgumentParser:
    """
    Build the argument parser for the `generate` subcommand.

    Can be used standalone or added to an existing subparser group.
    """
    if subparsers is not None:
        parser = subparsers.add_parser(
            "generate",
            help="Generate an optical table layout from a text prompt or spec file",
        )
    else:
        parser = argparse.ArgumentParser(
            prog="optiverse-generate",
            description="Generate an optical table layout using AI or from a beam path spec file",
        )

    parser.add_argument(
        "prompt",
        nargs="?",
        help="Natural-language description of the desired layout",
    )
    parser.add_argument(
        "--spec",
        type=Path,
        help="Path to a beam path spec JSON file (bypasses LLM)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output file path for the assembly JSON (default: stdout)",
    )
    parser.add_argument(
        "--model",
        default="gpt-4o",
        help="OpenAI model to use (default: gpt-4o)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="LLM temperature (default: 0.2)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    return parser


def main(args: argparse.Namespace | None = None) -> int:
    """Run the generate command."""
    if args is None:
        parser = build_parser()
        args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    if args.spec:
        from .generator import generate_from_spec

        try:
            assembly = generate_from_spec(args.spec, output_path=args.output)
        except (ValueError, FileNotFoundError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    elif args.prompt:
        from .generator import generate_layout

        try:
            assembly = generate_layout(
                args.prompt,
                model=args.model,
                temperature=args.temperature,
                output_path=args.output,
            )
        except (ValueError, RuntimeError, ImportError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    else:
        print("Error: provide either a prompt or --spec file", file=sys.stderr)
        return 1

    if args.output is None:
        print(json.dumps(assembly, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
