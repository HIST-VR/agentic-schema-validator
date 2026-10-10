"""CLI: python -m extraction_engine --schema invoice --sample"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from dotenv import load_dotenv

from extraction_engine.engine import dumps_payload, extract
from extraction_engine.providers import PROVIDERS
from extraction_engine.schemas.registry import SCHEMAS, get_schema


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="extraction_engine",
        description="Extract one document into a Pydantic schema and print the validated JSON.",
    )
    parser.add_argument("--schema", required=True, choices=sorted(SCHEMAS))
    parser.add_argument("--provider", default="google", choices=sorted(PROVIDERS))
    parser.add_argument("--model", default=None, help="Defaults to the provider's recommended model.")
    parser.add_argument("--sample", action="store_true", help="Use the built-in dirty sample.")
    parser.add_argument("--text", default=None, help="Raw source text.")
    parser.add_argument("--file", default=None, help="Path to a UTF-8 source file.")
    parser.add_argument("--max-retries", type=int, default=3)
    args = parser.parse_args(argv)

    sources = [args.sample, bool(args.text), bool(args.file)]
    if sum(bool(item) for item in sources) != 1:
        parser.error("Pass exactly one of --sample, --text, or --file.")

    spec = get_schema(args.schema)
    if args.sample:
        source = spec.sample_text
    elif args.text:
        source = args.text
    else:
        source = Path(args.file).read_text(encoding="utf-8")

    provider = PROVIDERS[args.provider]
    model = args.model or provider.default_model
    result = extract(
        source_text=source,
        schema_key=spec.key,
        provider_key=provider.key,
        model_name=model,
        max_retries=args.max_retries,
    )
    for event in result.events:
        attempt = f" attempt={event.attempt}" if event.attempt is not None else ""
        print(f"[{event.kind}] {event.title}{attempt}", file=sys.stderr)
        if event.detail:
            print(event.detail, file=sys.stderr)
        print(file=sys.stderr)
    if result.ok and result.data is not None:
        sys.stdout.write(dumps_payload(result.data))
        return 0
    print(result.error_message or "Extraction failed.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
