import re
from pathlib import Path

import pytest

from functions.crime_query import catalog

ER_DOC = Path(__file__).resolve().parents[1] / "Police_FIR_ER_Diagram.md"

# Named in the Relationship Matrix but never given column definitions.
UNDEFINED_IN_DOC = {"Inv_OccuranceTime", "inv_arrestsurrenderaccused"}


def parse_er_document(text):
    """Return {table_name: {column_name: type}} as literally written in the doc."""
    start = text.index("## Table Definitions")
    end = text.index("## Relationship Matrix")
    body = text[start:end]

    tables = {}
    current = None
    for line in body.splitlines():
        heading = re.match(r"^## (\w+)\s*$", line)
        if heading:
            name = heading.group(1)
            if name == "Table" or name == "Definitions":
                continue
            current = name
            tables.setdefault(current, {})
            continue
        if current is None or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        col, col_type = cells[0], cells[1]
        if not col or not col_type:
            continue
        if col == "Column Name" or set(col_type) <= {"-"}:
            continue
        tables[current][col] = col_type
    tables.pop("Table Definitions", None)
    return tables


@pytest.fixture(scope="module")
def doc_tables():
    return parse_er_document(ER_DOC.read_text(encoding="utf-8"))


def test_catalog_table_names_match_document(doc_tables):
    assert set(catalog.TABLES) == set(doc_tables)


def test_catalog_columns_match_document(doc_tables):
    for table, columns in doc_tables.items():
        assert catalog.TABLES[table] == columns, table


def test_undefined_tables_are_absent(doc_tables):
    assert UNDEFINED_IN_DOC.isdisjoint(catalog.TABLES)
    assert UNDEFINED_IN_DOC.isdisjoint(doc_tables)


def test_audit_table_is_not_queryable():
    assert catalog.AUDIT_TABLE not in catalog.TABLES


def test_sensitive_columns_exist_and_exclude_master_keys():
    for dotted in catalog.SENSITIVE_COLUMNS:
        table, column = dotted.split(".")
        assert column in catalog.TABLES[table], dotted
    assert "CasteMaster.caste_master_id" not in catalog.SENSITIVE_COLUMNS
    assert "ReligionMaster.ReligionID" not in catalog.SENSITIVE_COLUMNS


def test_identifying_columns_exist():
    for dotted in catalog.IDENTIFYING_COLUMNS:
        table, column = dotted.split(".")
        assert column in catalog.TABLES[table], dotted


def test_foreign_keys_reference_real_columns():
    for child_t, child_c, parent_t, parent_c in catalog.FOREIGN_KEYS:
        assert child_c in catalog.TABLES[child_t], (child_t, child_c)
        assert parent_c in catalog.TABLES[parent_t], (parent_t, parent_c)


def test_case_scoped_tables_all_have_casemasterid():
    for table in catalog.CASE_SCOPED_TABLES:
        if table == "CaseMaster":
            assert "CaseMasterID" in catalog.TABLES[table]
        else:
            assert "CaseMasterID" in catalog.TABLES[table], table


def test_sqlite_ddl_creates_every_table_plus_audit():
    ddl = catalog.sqlite_ddl()
    for table in catalog.TABLES:
        assert f'CREATE TABLE IF NOT EXISTS "{table}"' in ddl
    assert f'CREATE TABLE IF NOT EXISTS "{catalog.AUDIT_TABLE}"' in ddl


def test_describe_mentions_every_table(doc_tables):
    described = catalog.describe()
    for table in doc_tables:
        assert table in described


def test_describe_foreign_keys_uses_catalyst_parent_rowids():
    described = catalog.describe_foreign_keys()
    assert "Catalyst Foreign Key joins (child column -> parent ROWID)" in described
    assert "CaseMaster.PoliceStationID -> Unit.ROWID" in described
    assert "CaseMaster.PoliceStationID -> Unit.UnitID" not in described


def test_operational_tables_are_not_part_of_nl_catalog():
    assert "SilentMatchAlert" not in catalog.TABLES
    assert "SilentMatchAlert" in catalog.OPERATIONAL_TABLES
    assert "CREATE TABLE IF NOT EXISTS \"SilentMatchAlert\"" in catalog.operational_ddl()
