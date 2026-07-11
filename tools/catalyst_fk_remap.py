"""Automates the export -> remap -> upsert-reimport ETL for converting one
Catalyst foreign-key relationship's data from business-key values to the
parent table's real, platform-assigned ROWID.

Prerequisite (console, no CLI path exists for this): the child table's FK
column must already be converted to Catalyst's "Foreign Key" data type,
pointing at the parent table, before running this script -- see
docs/CATALYST_RUNBOOK.md, "Open gap: ZCQL relationships", worked example.

Usage (see docs/CATALYST_RUNBOOK.md's runbook procedure for the full
per-relationship sequence, including the console steps this script does
not automate):

    python -m tools.catalyst_fk_remap \\
        --parent Rank --parent-col RankID \\
        --child Employee --child-col RankID --child-pk EmployeeID
"""
import argparse
import csv
import glob
import os
import subprocess
import sys

_EXP_SCRIPT = os.path.join(os.path.dirname(__file__), "catalyst_ds_import.exp")


def build_rowid_map(export_csv_path, parent_col):
    """Read a `catalyst ds:export`-downloaded CSV (ROWID plus every
    business column) into a {business_key_value: ROWID} dict."""
    mapping = {}
    with open(export_csv_path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            mapping[row[parent_col]] = row["ROWID"]
    return mapping


def remap_csv(child_csv_in, child_csv_out, child_col, rowid_map):
    """Rewrite one column of a child table's CSV from business-key values
    to the parent's ROWID. Values with no entry in rowid_map (NULL FKs,
    or a parent row genuinely absent) are left untouched -- the caller is
    responsible for deciding whether that's expected."""
    with open(child_csv_in, newline="", encoding="utf-8") as src:
        reader = csv.DictReader(src)
        rows = list(reader)
        fieldnames = reader.fieldnames
    for row in rows:
        if row[child_col] in rowid_map:
            row[child_col] = rowid_map[row[child_col]]
    with open(child_csv_out, "w", newline="", encoding="utf-8") as dst:
        writer = csv.DictWriter(dst, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _run(cmd):
    print("+ {0}".format(" ".join(cmd)))
    subprocess.run(cmd, check=True)


def _latest_export_csv(unzip_dir, parent_table):
    matches = sorted(glob.glob(os.path.join(unzip_dir, "Table-{0}*.csv".format(parent_table))))
    if not matches:
        raise SystemExit("no exported CSV found for {0} in {1}".format(parent_table, unzip_dir))
    return matches[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", required=True, help="Parent table name, e.g. Rank")
    parser.add_argument("--parent-col", required=True, help="Parent business-key column, e.g. RankID")
    parser.add_argument("--child", required=True, help="Child table name, e.g. Employee")
    parser.add_argument("--child-col", required=True, help="Child FK column to remap, e.g. RankID")
    parser.add_argument("--child-pk", required=True,
                         help="Child table's unique column, for the upsert find_by -- "
                              "must already be marked 'Is Unique' in the console")
    parser.add_argument("--csv-dir", default="build/csv", help="Where the original child CSV lives")
    parser.add_argument("--work-dir", default="build/fk_remap", help="Scratch directory for this script")
    args = parser.parse_args()

    os.makedirs(args.work_dir, exist_ok=True)

    print("== Step 1: export {0} ==".format(args.parent))
    export_out = subprocess.run(
        ["catalyst", "ds:export", "--table", args.parent],
        check=True, capture_output=True, text=True,
    ).stdout
    print(export_out)
    jobid = next(
        tok.strip('"') for tok in export_out.split() if tok.strip('"').isdigit() and len(tok.strip('"')) > 10
    )

    print("== Step 2: wait for export and download ==")
    unzip_dir = os.path.join(args.work_dir, "{0}_export".format(args.parent))
    os.makedirs(unzip_dir, exist_ok=True)
    _run([_EXP_SCRIPT, "status-download", "export", jobid])
    for zip_path in glob.glob("Export_{0}_*.zip".format(jobid)):
        _run(["unzip", "-o", zip_path, "-d", unzip_dir])
        os.remove(zip_path)

    export_csv = _latest_export_csv(unzip_dir, args.parent)
    rowid_map = build_rowid_map(export_csv, args.parent_col)
    print("Built {0}.{1} -> ROWID map with {2} entries".format(
        args.parent, args.parent_col, len(rowid_map)))

    print("== Step 3: remap the child CSV ==")
    child_csv_in = os.path.join(args.csv_dir, "{0}.csv".format(args.child))
    child_csv_out = os.path.join(args.work_dir, "{0}_fk_remapped.csv".format(args.child))
    remap_csv(child_csv_in, child_csv_out, args.child_col, rowid_map)

    print("== Step 4: upsert-reimport {0} ==".format(args.child))
    config_path = os.path.join(args.work_dir, "{0}_upsert_config.json".format(args.child))
    with open(config_path, "w", encoding="utf-8") as handle:
        handle.write('{{"operation": "upsert", "find_by": "{0}"}}'.format(args.child_pk))
    _run([_EXP_SCRIPT, "import", child_csv_out, args.child, config_path])

    print("Done. Verify with: catalyst ds:export --table {0}".format(args.child))


if __name__ == "__main__":
    main()
