#!/usr/bin/env python3
"""Upload the APN PoC DOCX template to the artifacts S3 bucket."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_KEY = "templates/apn-poc-template.docx"


def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, check=True, text=True, capture_output=True)
    return result.stdout.strip()


def resolve_bucket(tf_dir: Path, explicit_bucket: str | None) -> str:
    if explicit_bucket:
        return explicit_bucket

    for output_name in ("artifacts_bucket", "s3_bucket"):
        try:
            bucket = run(["terraform", f"-chdir={tf_dir}", "output", "-raw", output_name])
        except subprocess.CalledProcessError:
            continue
        if bucket:
            return bucket

    raise SystemExit(
        "ERROR: artifacts bucket output not found. Run Terraform apply first, "
        "or pass --bucket explicitly."
    )


def upload_template(template_path: Path, bucket: str, key: str, profile: str | None, region: str | None) -> None:
    if not template_path.exists():
        raise SystemExit(
            f"ERROR: template file not found: {template_path}\n"
            "Place apn-poc-template.docx there manually before running this script."
        )
    if not template_path.is_file():
        raise SystemExit(f"ERROR: template path is not a file: {template_path}")
    if template_path.suffix.lower() != ".docx":
        raise SystemExit(f"ERROR: template must be a .docx file: {template_path}")

    uri = f"s3://{bucket}/{key}"
    cmd = [
        "aws",
        "s3",
        "cp",
        str(template_path),
        uri,
        "--content-type",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]
    if profile:
        cmd.extend(["--profile", profile])
    if region:
        cmd.extend(["--region", region])

    subprocess.run(cmd, check=True)
    print(f"Uploaded {template_path} to {uri}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--template",
        default="agent/templates/apn-poc-template.docx",
        help="Path to the local DOCX template.",
    )
    parser.add_argument("--bucket", help="Artifacts bucket name. Defaults to Terraform output.")
    parser.add_argument("--key", default=DEFAULT_KEY, help="S3 object key.")
    parser.add_argument(
        "--tf-dir",
        default="infra/terraform",
        help="Terraform directory used to read the artifacts bucket output.",
    )
    parser.add_argument("--profile", default=os.environ.get("AWS_PROFILE"), help="AWS profile for aws CLI.")
    parser.add_argument("--region", default=os.environ.get("REGION") or os.environ.get("AWS_REGION"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path.cwd()
    template_path = Path(args.template)
    if not template_path.is_absolute():
        template_path = root / template_path

    tf_dir = Path(args.tf_dir)
    if not tf_dir.is_absolute():
        tf_dir = root / tf_dir

    bucket = resolve_bucket(tf_dir, args.bucket)
    upload_template(template_path, bucket, args.key, args.profile, args.region)
    return 0


if __name__ == "__main__":
    sys.exit(main())
