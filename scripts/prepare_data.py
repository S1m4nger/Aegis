#!/usr/bin/env python3
"""Safely extract only the confirmed PaySim CSV. No silent schema mixing."""
from __future__ import annotations
import argparse, csv, io, shutil, zipfile
from pathlib import Path

EXPECTED = "PS_20174392719_1491204439457_log.csv"
HEADER = ["step","type","amount","nameOrig","oldbalanceOrg","newbalanceOrig",
          "nameDest","oldbalanceDest","newbalanceDest","isFraud","isFlaggedFraud"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True, dest="source_zip")
    ap.add_argument("--out", default="data/raw/paysim.csv")
    args = ap.parse_args()
    source, out = Path(args.source_zip), Path(args.out)
    if not source.is_file():
        raise SystemExit(f"Dataset ZIP not found: {source}")
    with zipfile.ZipFile(source) as z:
        files = [x for x in z.infolist() if not x.is_dir()]
        if len(files) != 1 or files[0].filename != EXPECTED:
            raise SystemExit(f"Wrong ZIP contents. Expected only {EXPECTED}; got {[x.filename for x in files]}")
        with z.open(files[0]) as src:
            first = src.readline().decode("utf-8-sig").strip().split(",")
            if first != HEADER:
                raise SystemExit(f"Wrong header: {first}. Do NOT use IEEE sample_submission data.")
        out.parent.mkdir(parents=True, exist_ok=True)
        with z.open(files[0]) as src, out.open("wb") as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
    print(f"OK PaySim CSV extracted to {out} ({out.stat().st_size:,} bytes)")

if __name__ == "__main__":
    main()
