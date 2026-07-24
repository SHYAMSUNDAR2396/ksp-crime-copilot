import hashlib
import sqlite3

import pytest

from tools import gen_data


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("db")
    counts = gen_data.build(str(out / "crime.db"), csv_dir=str(out / "csv"))
    conn = sqlite3.connect(str(out / "crime.db"))
    conn.row_factory = sqlite3.Row
    yield conn, counts, out
    conn.close()


def test_case_count_is_exact(built):
    _, counts, _ = built
    assert counts["CaseMaster"] == gen_data.TOTAL_CASES


def test_every_catalog_table_is_populated(built):
    _, counts, _ = built
    from functions.crime_query import catalog
    for table in catalog.TABLES:
        assert counts[table] > 0, table


def test_crimeno_is_eighteen_digits(built):
    conn, _, _ = built
    rows = conn.execute('SELECT CrimeNo FROM "CaseMaster"').fetchall()
    for row in rows:
        assert len(row["CrimeNo"]) == 18, row["CrimeNo"]
        assert row["CrimeNo"].isdigit()


def test_caseno_is_last_nine_digits_of_crimeno(built):
    conn, _, _ = built
    rows = conn.execute('SELECT CrimeNo, CaseNo FROM "CaseMaster"').fetchall()
    for row in rows:
        assert row["CaseNo"] == row["CrimeNo"][-9:]


def test_no_orphan_child_rows(built):
    conn, _, _ = built
    from functions.crime_query import catalog
    case_ids = {r[0] for r in conn.execute('SELECT CaseMasterID FROM "CaseMaster"')}
    for table in sorted(catalog.CASE_SCOPED_TABLES - {"CaseMaster"}):
        orphans = [
            r[0]
            for r in conn.execute('SELECT CaseMasterID FROM "{0}"'.format(table))
            if r[0] not in case_ids
        ]
        assert orphans == [], table


def test_two_wheeler_theft_trend_is_seeded(built):
    conn, _, _ = built
    sql = """
        SELECT COUNT(*) FROM "CaseMaster"
        JOIN "CrimeSubHead" ON CaseMaster.CrimeMinorHeadID = CrimeSubHead.CrimeSubHeadID
        WHERE CrimeSubHead.CrimeHeadName = 'Two-Wheeler Theft'
          AND CaseMaster.PoliceStationID = 1
          AND CaseMaster.CrimeRegisteredDate >= ?
    """
    recent = conn.execute(sql, ("2026-04-01",)).fetchone()[0]
    earlier = conn.execute(
        sql.replace(">= ?", "< ?"), ("2026-04-01",)
    ).fetchone()[0]
    # 90 days of uplift must outweigh the preceding 640 days of background rate.
    assert recent > earlier


def test_burglary_cluster_is_tight(built):
    conn, _, _ = built
    rows = conn.execute(
        """
        SELECT latitude, longitude FROM "CaseMaster"
        JOIN "CrimeSubHead" ON CaseMaster.CrimeMinorHeadID = CrimeSubHead.CrimeSubHeadID
        WHERE CrimeSubHead.CrimeHeadName = 'Burglary'
          AND CaseMaster.PoliceStationID = 1
        """
    ).fetchall()
    lat0, lon0 = gen_data.CLUSTER_CENTRE
    radius = gen_data.CLUSTER_RADIUS_DEG
    within_radius = [
        r for r in rows
        if (r["latitude"] - lat0) ** 2 + (r["longitude"] - lon0) ** 2 <= radius ** 2
    ]
    assert len(within_radius) >= 60


def test_name_variants_span_three_stations(built):
    conn, _, _ = built
    rows = conn.execute(
        """
        SELECT Accused.AccusedName, CaseMaster.PoliceStationID
        FROM "Accused"
        JOIN "CaseMaster" ON Accused.CaseMasterID = CaseMaster.CaseMasterID
        WHERE Accused.PersonID = 'A9'
        """
    ).fetchall()
    assert len(rows) == 4
    assert {r["AccusedName"] for r in rows} == set(gen_data.RAVI_SPELLINGS)
    assert len({r["PoliceStationID"] for r in rows}) >= 3


def test_name_variant_test_is_not_satisfied_by_namesakes(built):
    conn, _, _ = built
    placeholders = ",".join("?" for _ in gen_data.RAVI_SPELLINGS)
    rows = conn.execute(
        """
        SELECT AccusedName FROM "Accused"
        WHERE AccusedName IN ({0})
        """.format(placeholders),
        gen_data.RAVI_SPELLINGS,
    ).fetchall()
    assert len(rows) > 4


def test_sensitive_columns_are_populated_not_null(built):
    conn, _, _ = built
    null_castes = conn.execute(
        'SELECT COUNT(*) FROM "ComplainantDetails" WHERE CasteID IS NULL'
    ).fetchone()[0]
    assert null_castes == 0


def test_foreign_keys_are_remapped_to_parent_rowid(built):
    """Every FK column must hold the parent row's SQLite rowid, not its
    business primary key, mirroring Catalyst's Foreign Key columns (which
    can only reference a parent's platform ROWID). Checks every
    relationship in catalog.FOREIGN_KEYS structurally: every non-null
    child value must equal some row's rowid in the parent table."""
    from functions.crime_query import catalog

    conn, _, _ = built
    for child, child_col, parent, _parent_col in catalog.FOREIGN_KEYS:
        # Compare as strings: a TEXT-affinity column (e.g. Section.ActCode,
        # declared VARCHAR) stores an inserted integer rowid as its text
        # form ('1', not 1) per SQLite's affinity rules -- harmless for
        # real queries (SQLite applies numeric affinity when comparing
        # TEXT to INTEGER in a JOIN/WHERE), but str() here avoids a false
        # mismatch from comparing raw Python int vs str representations.
        parent_rowids = {str(row[0]) for row in conn.execute('SELECT rowid FROM "{0}"'.format(parent))}
        child_values = {
            str(row[0]) for row in conn.execute(
                'SELECT DISTINCT "{0}" FROM "{1}" WHERE "{0}" IS NOT NULL'.format(child_col, child)
            )
        }
        assert child_values <= parent_rowids, (
            "{0}.{1} has values with no matching {2}.rowid: {3}".format(
                child, child_col, parent, child_values - parent_rowids
            )
        )


def test_foreign_key_remap_is_not_a_coincidental_no_op():
    """Act's business key (ActCode) is text ('IPC'), so its rowid can never
    coincidentally equal the pre-remap business-key value the way small
    sequential-integer-keyed lookup tables (Unit, District, ...) do. This
    proves the remap actually runs, not just that assertions happen to
    still hold by accident."""
    import sqlite3

    conn = sqlite3.connect(":memory:")
    from functions.crime_query import catalog

    conn.executescript(catalog.sqlite_ddl())
    conn.execute('INSERT INTO "Act" (ActCode, ActDescription, ShortName, Active) '
                 "VALUES ('IPC', 'Indian Penal Code', 'IPC', 1)")
    conn.execute('INSERT INTO "Act" (ActCode, ActDescription, ShortName, Active) '
                 "VALUES ('NDPS', 'Narcotic Drugs Act', 'NDPS', 1)")
    conn.execute(
        'INSERT INTO "ActSectionAssociation" '
        '(CaseMasterID, ActID, SectionID, ActOrderID, SectionOrderID) '
        "VALUES (1, 'NDPS', 'S1', 1, 1)"
    )
    conn.commit()

    from tools.gen_data import _remap_foreign_keys_to_rowid
    _remap_foreign_keys_to_rowid(conn)

    # CaseMasterID itself gets remapped too (no matching CaseMaster row in
    # this minimal fixture, so it becomes NULL) -- query the single row
    # directly rather than filtering on a column that's also being remapped.
    remapped = conn.execute('SELECT ActID FROM "ActSectionAssociation"').fetchone()[0]
    ndps_rowid = conn.execute("SELECT rowid FROM \"Act\" WHERE ActCode = 'NDPS'").fetchone()[0]
    assert remapped == ndps_rowid
    assert remapped != "NDPS"


def test_generation_is_byte_for_byte_reproducible(tmp_path):
    def digest(path):
        counts = gen_data.build(str(path / "crime.db"), csv_dir=str(path / "csv"))
        assert counts
        parts = []
        for csv_file in sorted((path / "csv").iterdir()):
            parts.append(hashlib.sha256(csv_file.read_bytes()).hexdigest())
        return parts

    first = digest(tmp_path / "a")
    second = digest(tmp_path / "b")
    assert first == second


def test_demo_case_ids_include_bilingual_pair_and_replay_seeds(built):
    assert len(gen_data.DEMO_CASE_IDS["bilingual_mo_pair"]) == 2
    assert len(gen_data.DEMO_CASE_IDS["ravi_variants"]) == 4
    assert gen_data.DEMO_CASE_IDS["hotspot_candidates"]
    conn, _, _ = built
    rows = conn.execute(
        'SELECT BriefFacts FROM "CaseMaster" WHERE CaseMasterID IN (?, ?)',
        gen_data.DEMO_CASE_IDS["bilingual_mo_pair"],
    ).fetchall()
    assert any("ಬಾಗಿಲು" in row[0] for row in rows)
    assert any("House lock" in row[0] for row in rows)
