"""Single source of truth for the KSP crime schema.

Every table and column here is transcribed verbatim from
Police_FIR_ER_Diagram.md. tests/test_catalog.py re-reads that document and
fails if the two ever diverge. Never add a column to make a query easier.
"""

TABLES = {
    "CaseMaster": {
        "CaseMasterID": "INT",
        "CrimeNo": "VARCHAR",
        "CaseNo": "VARCHAR",
        "CrimeRegisteredDate": "DATE",
        "PolicePersonID": "INT",
        "PoliceStationID": "INT",
        "CaseCategoryID": "INT",
        "GravityOffenceID": "INT",
        "CrimeMajorHeadID": "INT",
        "CrimeMinorHeadID": "INT",
        "CaseStatusID": "INT",
        "CourtID": "INT",
        "IncidentFromDate": "DATETIME",
        "IncidentToDate": "DATETIME",
        "InfoReceivedPSDate": "DATETIME",
        "latitude": "DECIMAL",
        "longitude": "DECIMAL",
        "BriefFacts": "Nvarchar(Max)",
    },
    "ComplainantDetails": {
        "ComplainantID": "INT",
        "CaseMasterID": "INT",
        "ComplainantName": "VARCHAR",
        "AgeYear": "INT",
        "OccupationID": "INT",
        "ReligionID": "INT",
        "CasteID": "INT",
        "GenderID": "INT",
    },
    "ActSectionAssociation": {
        "CaseMasterID": "INT",
        "ActID": "INT",
        "SectionID": "INT",
        "ActOrderID": "INT",
        "SectionOrderID": "INT",
    },
    "Victim": {
        "VictimMasterID": "INT",
        "CaseMasterID": "INT",
        "VictimName": "VARCHAR",
        "AgeYear": "INT",
        "GenderID": "INT",
        "VictimPolice": "VARCHAR",
    },
    "Accused": {
        "AccusedMasterID": "INT",
        "CaseMasterID": "INT",
        "AccusedName": "VARCHAR",
        "AgeYear": "INT",
        "GenderID": "INT",
        "PersonID": "VARCHAR",
    },
    "ArrestSurrender": {
        "ArrestSurrenderID": "INT",
        "CaseMasterID": "INT",
        "ArrestSurrenderTypeID": "INT",
        "ArrestSurrenderDate": "DATE",
        "ArrestSurrenderStateId": "INT",
        "ArrestSurrenderDistrictId": "INT",
        "PoliceStationID": "INT",
        "IOID": "INT",
        "CourtID": "INT",
        "AccusedMasterID": "INT",
        "IsAccused": "BIT",
        "IsComplainantAccused": "BIT",
    },
    "Act": {
        "ActCode": "VARCHAR",
        "ActDescription": "VARCHAR",
        "ShortName": "VARCHAR",
        "Active": "BIT",
    },
    "Section": {
        "ActCode": "VARCHAR",
        "SectionCode": "VARCHAR",
        "SectionDescription": "VARCHAR",
        "Active": "BIT",
    },
    "CrimeHeadActSection": {
        "CrimeHeadID": "INT",
        "ActCode": "VARCHAR",
        "SectionCode": "VARCHAR",
    },
    "CrimeHead": {
        "CrimeHeadID": "INT",
        "CrimeGroupName": "VARCHAR",
        "Active": "BIT",
    },
    "CrimeSubHead": {
        "CrimeSubHeadID": "INT",
        "CrimeHeadID": "INT",
        "CrimeHeadName": "VARCHAR",
        "SeqID": "INT",
    },
    "CasteMaster": {
        "caste_master_id": "INT",
        "caste_master_name": "VARCHAR",
    },
    "ReligionMaster": {
        "ReligionID": "INT",
        "ReligionName": "VARCHAR",
    },
    "OccupationMaster": {
        "OccupationID": "INT",
        "OccupationName": "VARCHAR",
    },
    "CaseStatusMaster": {
        "CaseStatusID": "INT",
        "CaseStatusName": "VARCHAR",
    },
    "Court": {
        "CourtID": "INT",
        "CourtName": "VARCHAR",
        "DistrictID": "INT",
        "StateID": "INT",
        "Active": "BIT",
    },
    "District": {
        "DistrictID": "INT",
        "DistrictName": "VARCHAR",
        "StateID": "INT",
        "Active": "BIT",
    },
    "State": {
        "StateID": "INT",
        "StateName": "VARCHAR",
        "NationalityID": "INT",
        "Active": "BIT",
    },
    "Unit": {
        "UnitID": "INT",
        "UnitName": "VARCHAR",
        "TypeID": "INT",
        "ParentUnit": "INT",
        "NationalityID": "INT",
        "StateID": "INT",
        "DistrictID": "INT",
        "Active": "BIT",
    },
    "UnitType": {
        "UnitTypeID": "INT",
        "UnitTypeName": "VARCHAR",
        "CityDistState": "VARCHAR",
        "Hierarchy": "INT",
        "Active": "BIT",
    },
    "Rank": {
        "RankID": "INT",
        "RankName": "VARCHAR",
        "Hierarchy": "INT",
        "Active": "BIT",
    },
    "Designation": {
        "DesignationID": "INT",
        "DesignationName": "VARCHAR",
        "Active": "BIT",
        "SortOrder": "INT",
    },
    "Employee": {
        "EmployeeID": "INT",
        "DistrictID": "INT",
        "UnitID": "INT",
        "RankID": "INT",
        "DesignationID": "INT",
        "KGID": "VARCHAR",
        "FirstName": "VARCHAR",
        "EmployeeDOB": "DATE",
        "GenderID": "INT",
        "BloodGroupID": "INT",
        "PhysicallyChallenged": "BIT",
        "AppointmentDate": "DATE",
    },
    "CaseCategory": {
        "CaseCategoryID": "INT",
        "LookupValue": "VARCHAR",
    },
    "GravityOffence": {
        "GravityOffenceID": "INT",
        "LookupValue": "VARCHAR",
    },
    "ChargesheetDetails": {
        "CSID": "INT",
        "CaseMasterID": "INT",
        "csdate": "DATETIME",
        "cstype": "CHAR",
        "PolicePersonID": "INT",
    },
}

# (child_table, child_column, parent_table, parent_column)
FOREIGN_KEYS = [
    ("CaseMaster", "PolicePersonID", "Employee", "EmployeeID"),
    ("CaseMaster", "PoliceStationID", "Unit", "UnitID"),
    ("CaseMaster", "CaseCategoryID", "CaseCategory", "CaseCategoryID"),
    ("CaseMaster", "GravityOffenceID", "GravityOffence", "GravityOffenceID"),
    ("CaseMaster", "CrimeMajorHeadID", "CrimeHead", "CrimeHeadID"),
    ("CaseMaster", "CrimeMinorHeadID", "CrimeSubHead", "CrimeSubHeadID"),
    ("CaseMaster", "CaseStatusID", "CaseStatusMaster", "CaseStatusID"),
    ("CaseMaster", "CourtID", "Court", "CourtID"),
    ("ComplainantDetails", "CaseMasterID", "CaseMaster", "CaseMasterID"),
    ("ComplainantDetails", "OccupationID", "OccupationMaster", "OccupationID"),
    ("ComplainantDetails", "ReligionID", "ReligionMaster", "ReligionID"),
    ("ComplainantDetails", "CasteID", "CasteMaster", "caste_master_id"),
    ("ActSectionAssociation", "CaseMasterID", "CaseMaster", "CaseMasterID"),
    ("ActSectionAssociation", "ActID", "Act", "ActCode"),
    ("ActSectionAssociation", "SectionID", "Section", "SectionCode"),
    ("Victim", "CaseMasterID", "CaseMaster", "CaseMasterID"),
    ("Accused", "CaseMasterID", "CaseMaster", "CaseMasterID"),
    ("ArrestSurrender", "CaseMasterID", "CaseMaster", "CaseMasterID"),
    ("ArrestSurrender", "ArrestSurrenderStateId", "State", "StateID"),
    ("ArrestSurrender", "ArrestSurrenderDistrictId", "District", "DistrictID"),
    ("ArrestSurrender", "PoliceStationID", "Unit", "UnitID"),
    ("ArrestSurrender", "IOID", "Employee", "EmployeeID"),
    ("ArrestSurrender", "CourtID", "Court", "CourtID"),
    ("ArrestSurrender", "AccusedMasterID", "Accused", "AccusedMasterID"),
    ("Section", "ActCode", "Act", "ActCode"),
    ("CrimeHeadActSection", "CrimeHeadID", "CrimeHead", "CrimeHeadID"),
    ("CrimeHeadActSection", "ActCode", "Act", "ActCode"),
    ("CrimeSubHead", "CrimeHeadID", "CrimeHead", "CrimeHeadID"),
    ("Court", "DistrictID", "District", "DistrictID"),
    ("Court", "StateID", "State", "StateID"),
    ("District", "StateID", "State", "StateID"),
    ("Unit", "TypeID", "UnitType", "UnitTypeID"),
    ("Unit", "StateID", "State", "StateID"),
    ("Unit", "DistrictID", "District", "DistrictID"),
    ("Employee", "DistrictID", "District", "DistrictID"),
    ("Employee", "UnitID", "Unit", "UnitID"),
    ("Employee", "RankID", "Rank", "RankID"),
    ("Employee", "DesignationID", "Designation", "DesignationID"),
    ("ChargesheetDetails", "CaseMasterID", "CaseMaster", "CaseMasterID"),
    ("ChargesheetDetails", "PolicePersonID", "Employee", "EmployeeID"),
]

# DPDP-sensitive. Master-table primary keys are deliberately absent so joins work.
SENSITIVE_COLUMNS = frozenset({
    "ComplainantDetails.CasteID",
    "ComplainantDetails.ReligionID",
    "CasteMaster.caste_master_name",
    "ReligionMaster.ReligionName",
})

# Columns that identify a person or reproduce a case narrative. A query
# projecting any of these must also project CaseMaster.CrimeNo, so the answer
# can be traced to specific cases -- aggregate or not.
IDENTIFYING_COLUMNS = frozenset({
    "CaseMaster.BriefFacts",
    "ComplainantDetails.ComplainantName",
    "Victim.VictimName",
    "Accused.AccusedName",
    "Employee.FirstName",
})

# Tables whose rows belong to a specific case, and therefore must be RBAC-scoped.
CASE_SCOPED_TABLES = frozenset({
    "CaseMaster",
    "ComplainantDetails",
    "ActSectionAssociation",
    "Victim",
    "Accused",
    "ArrestSurrender",
    "ChargesheetDetails",
})

ALLOWED_FUNCTIONS = frozenset({"COUNT", "SUM", "AVG", "MIN", "MAX"})

OPERATIONAL_TABLES = frozenset({
    "SilentMatchAlert", "SilentMatchRecipient", "SilentMatchAction",
    "SilentMatchRun", "MoEmbeddingRecord",
})

# Mandated by PLAN.md 1.5. Absent from TABLES on purpose: the LLM must never see it.
AUDIT_TABLE = "AuditLog"
AUDIT_COLUMNS = {
    "AuditID": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "EmployeeID": "INTEGER",
    "RankHierarchy": "INTEGER",
    "Question": "TEXT",
    "GeneratedSQL": "TEXT",
    "ExecutedSQL": "TEXT",
    "CrimeNos": "TEXT",
    "RowCount": "INTEGER",
    "LoggedAt": "TEXT",
}

_SQLITE_TYPES = {
    "INT": "INTEGER",
    "BIT": "INTEGER",
    "DECIMAL": "REAL",
    "VARCHAR": "TEXT",
    "CHAR": "TEXT",
    "DATE": "TEXT",
    "DATETIME": "TEXT",
    "Nvarchar(Max)": "TEXT",
}


def sqlite_ddl():
    """CREATE TABLE statements for every schema table plus the audit log."""
    statements = []
    for table, columns in TABLES.items():
        cols = ",\n  ".join(
            '"{0}" {1}'.format(name, _SQLITE_TYPES[typ])
            for name, typ in columns.items()
        )
        statements.append(
            'CREATE TABLE IF NOT EXISTS "{0}" (\n  {1}\n);'.format(table, cols)
        )
    audit_cols = ",\n  ".join(
        '"{0}" {1}'.format(name, typ) for name, typ in AUDIT_COLUMNS.items()
    )
    statements.append(
        'CREATE TABLE IF NOT EXISTS "{0}" (\n  {1}\n);'.format(AUDIT_TABLE, audit_cols)
    )
    return "\n\n".join(statements) + "\n\n" + operational_ddl()


def operational_ddl():
    """DDL for fixed operational tables, intentionally outside TABLES."""
    return """
CREATE TABLE IF NOT EXISTS "SilentMatchAlert" (
  "AlertID" INTEGER PRIMARY KEY AUTOINCREMENT,
  "AlertType" TEXT NOT NULL,
  "AnchorCaseID" INTEGER NOT NULL,
  "MatchedCaseID" INTEGER NOT NULL,
  "AnchorCrimeNo" TEXT NOT NULL,
  "MatchedCrimeNo" TEXT NOT NULL,
  "Score" INTEGER NOT NULL,
  "ConfidenceBand" TEXT NOT NULL,
  "Status" TEXT NOT NULL DEFAULT 'New',
  "EvidenceJSON" TEXT NOT NULL,
  "EvidenceSnapshotJSON" TEXT NOT NULL,
  "SourceRunID" TEXT NOT NULL,
  "IndexVersion" TEXT NOT NULL DEFAULT '',
  "CreatedAt" TEXT NOT NULL,
  "UpdatedAt" TEXT NOT NULL,
  UNIQUE ("AlertType", "AnchorCaseID", "MatchedCaseID")
);
CREATE INDEX IF NOT EXISTS "idx_SilentMatchAlert_Status" ON "SilentMatchAlert" ("Status");
CREATE TABLE IF NOT EXISTS "SilentMatchRecipient" (
  "RecipientID" INTEGER PRIMARY KEY AUTOINCREMENT,
  "AlertID" INTEGER NOT NULL,
  "EmployeeID" INTEGER NOT NULL,
  "SeenAt" TEXT,
  UNIQUE ("AlertID", "EmployeeID")
);
CREATE TABLE IF NOT EXISTS "SilentMatchAction" (
  "ActionID" INTEGER PRIMARY KEY AUTOINCREMENT,
  "AlertID" INTEGER NOT NULL,
  "Action" TEXT NOT NULL,
  "Note" TEXT NOT NULL,
  "EmployeeID" INTEGER NOT NULL,
  "CreatedAt" TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS "SilentMatchRun" (
  "RunID" TEXT PRIMARY KEY,
  "TriggerSource" TEXT NOT NULL,
  "Status" TEXT NOT NULL,
  "AnchorsSeen" INTEGER NOT NULL DEFAULT 0,
  "CandidatesSeen" INTEGER NOT NULL DEFAULT 0,
  "AlertsCreated" INTEGER NOT NULL DEFAULT 0,
  "StartedAt" TEXT NOT NULL,
  "FinishedAt" TEXT
);
CREATE TABLE IF NOT EXISTS "MoEmbeddingRecord" (
  "CaseMasterID" INTEGER PRIMARY KEY,
  "CrimeNo" TEXT NOT NULL,
  "IndexVersion" TEXT NOT NULL,
  "Provider" TEXT NOT NULL,
  "VectorJSON" TEXT NOT NULL,
  "UpdatedAt" TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS "idx_SilentMatchAction_Alert" ON "SilentMatchAction" ("AlertID");
""".strip()


def describe():
    """Compact case-schema text for the NL-to-ZCQL prompt."""
    lines = []
    for table, columns in TABLES.items():
        lines.append("{0}({1})".format(table, ", ".join(columns)))
    return "\n".join(lines)


def describe_foreign_keys():
    """Render the live Catalyst relationship contract for the prompt."""
    lines = ["Catalyst Foreign Key joins (child column -> parent ROWID):"]
    for child_t, child_c, parent_t, _parent_c in FOREIGN_KEYS:
        lines.append(
            "  {0}.{1} -> {2}.ROWID".format(child_t, child_c, parent_t)
        )
    return "\n".join(lines)
