"""Explicit, confirmation-gated production promotion command."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from .config import PRODUCTION_COLLECTION, Settings
from .mongo_storage import MongoStorage
from .promotion import ProductionPromoter, validate_promotion_candidate


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate or promote one Bronze run")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--promote-first-mixed", action="store_true")
    mode.add_argument("--promote-ready", action="store_true")
    parser.add_argument("--promotion-time")
    parser.add_argument("--confirm-production")
    parser.add_argument("--confirm-mixed-run-count", type=int)
    parser.add_argument("--expected-current-documents", type=int)
    args = parser.parse_args()

    promotion_time: datetime | None = None
    if not args.validate_only:
        if not args.promotion_time:
            parser.error("--promotion-time is required")
        try:
            promotion_time = datetime.fromisoformat(args.promotion_time)
        except ValueError:
            parser.error("--promotion-time must be an ISO-8601 timestamp")
        if promotion_time.tzinfo is None:
            parser.error("--promotion-time must include a timezone")
        if args.confirm_production != PRODUCTION_COLLECTION:
            parser.error("--confirm-production must be exactly legacy_records")
        if args.promote_first_mixed:
            if args.confirm_mixed_run_count != 16:
                parser.error("--confirm-mixed-run-count must be exactly 16")
            if args.expected_current_documents is None:
                parser.error("--expected-current-documents is required")
        elif (
            args.confirm_mixed_run_count is not None
            or args.expected_current_documents is not None
        ):
            parser.error(
                "mixed migration confirmation options are invalid with --promote-ready"
            )

    settings = Settings.from_env()
    storage = MongoStorage(settings)
    try:
        storage.ping()
        report = validate_promotion_candidate(
            storage,
            run_id=args.run_id,
            run_dir=args.run_dir,
            project_root=args.project_root,
        )
        if not report.passed:
            print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
            return 2
        if args.validate_only:
            print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
            return 0

        expected_rows = next(
            check.expected
            for check in report.checks
            if check.name == "production_row_count"
        )
        promoter = ProductionPromoter(storage, state_root=settings.state_root)

        if args.promote_first_mixed:
            result = promoter.promote_first_mixed_legacy(
                run_id=args.run_id,
                source_name=settings.source_name,
                expected_rows=expected_rows,
                candidate_report=report,
                expected_legacy_documents=args.expected_current_documents,
                promotion_time=promotion_time,
            )
        else:
            result = promoter.promote_ready_to_ready(
                run_id=args.run_id,
                source_name=settings.source_name,
                expected_rows=expected_rows,
                candidate_report=report,
                promotion_time=promotion_time,
            )
        print(
            json.dumps(
                {
                    "run_id": result.run_id,
                    "previous_run_ids": result.previous_run_ids,
                    "backup_collection": result.backup_collection,
                    "production_collection": result.production_collection,
                    "ready_at": result.ready_at,
                    "post_validation": result.post_validation.as_dict(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        storage.close()


if __name__ == "__main__":
    raise SystemExit(main())
