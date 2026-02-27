"""CLI script to generate summary stats for an intervention.

Usage:
    python scripts/generate_summary.py rapamycin
    python scripts/generate_summary.py --all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from src.config import settings
from src.stats.summary import generate_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate summary stats for intervention data")
    parser.add_argument("intervention", nargs="?", help="Intervention name (e.g., rapamycin)")
    parser.add_argument("--all", action="store_true", help="Generate summaries for all interventions with data")
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level=settings.log_level)

    if args.all:
        doc_dir = settings.documents_dir
        if not doc_dir.exists():
            logger.error(f"No documents directory at {doc_dir}")
            sys.exit(1)
        names = [p.stem for p in doc_dir.glob("*.json")]
        if not names:
            logger.error("No intervention data files found")
            sys.exit(1)
        for name in sorted(names):
            logger.info(f"Generating summary for '{name}'...")
            summary = generate_summary(name)
            if summary:
                logger.info(f"  {summary['total_documents']} documents across {len(summary['by_source_type'])} sources")
    elif args.intervention:
        name = args.intervention.lower()
        summary = generate_summary(name)
        if summary:
            print(json.dumps(summary, indent=2, default=str))
        else:
            logger.error(f"No data found for '{name}'")
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
