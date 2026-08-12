# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--message", default="hello")
parser.add_argument("--output", "-o", required=True)
args = parser.parse_args()
Path(args.output).write_text(args.message + "\n", encoding="utf-8")
print(f"wrote {args.output}: {args.message}")
