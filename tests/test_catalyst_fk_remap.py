import csv

from tools.catalyst_fk_remap import build_rowid_map, remap_csv


def _write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def test_build_rowid_map_reads_a_catalyst_export_csv(tmp_path):
    export_path = tmp_path / "Table-Rank.csv"
    _write_csv(
        export_path,
        ["ROWID", "CREATORID", "CREATEDTIME", "MODIFIEDTIME", "RankID", "RankName", "Hierarchy", "Active"],
        [
            ["48091000000037038", "48091000000013007", "2026-07-11 10:09:49:077",
             "2026-07-11 10:09:49:077", "1", "DGP", "1", "1"],
            ["48091000000037041", "48091000000013007", "2026-07-11 10:09:49:077",
             "2026-07-11 10:09:49:077", "4", "Inspector", "4", "1"],
        ],
    )

    mapping = build_rowid_map(str(export_path), "RankID")

    assert mapping == {"1": "48091000000037038", "4": "48091000000037041"}


def test_remap_csv_rewrites_only_the_target_column(tmp_path):
    child_in = tmp_path / "Employee.csv"
    child_out = tmp_path / "Employee_remapped.csv"
    _write_csv(
        child_in,
        ["EmployeeID", "DistrictID", "UnitID", "RankID", "FirstName"],
        [
            ["1", "1", "1", "4", "Suresh"],
            ["2", "1", "1", "5", "Manjunath"],
        ],
    )
    rowid_map = {"4": "48091000000037041", "5": "48091000000037042"}

    remap_csv(str(child_in), str(child_out), "RankID", rowid_map)

    with open(child_out, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["RankID"] == "48091000000037041"
    assert rows[1]["RankID"] == "48091000000037042"
    # Every other column is untouched.
    assert rows[0]["EmployeeID"] == "1"
    assert rows[0]["FirstName"] == "Suresh"


def test_remap_csv_leaves_unmapped_values_untouched(tmp_path):
    """A child value with no entry in rowid_map (e.g. a NULL FK, or a
    parent row that doesn't exist) is left as-is rather than silently
    dropped or blanked -- the caller decides how to handle gaps, this
    function's job is only the substitution it can do safely."""
    child_in = tmp_path / "Employee.csv"
    child_out = tmp_path / "Employee_remapped.csv"
    _write_csv(
        child_in,
        ["EmployeeID", "RankID"],
        [["1", ""], ["2", "999"]],
    )
    rowid_map = {"4": "48091000000037041"}

    remap_csv(str(child_in), str(child_out), "RankID", rowid_map)

    with open(child_out, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["RankID"] == ""
    assert rows[1]["RankID"] == "999"
