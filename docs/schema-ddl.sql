CREATE TABLE IF NOT EXISTS "CaseMaster" (
  "CaseMasterID" INTEGER,
  "CrimeNo" TEXT,
  "CaseNo" TEXT,
  "CrimeRegisteredDate" TEXT,
  "PolicePersonID" INTEGER,
  "PoliceStationID" INTEGER,
  "CaseCategoryID" INTEGER,
  "GravityOffenceID" INTEGER,
  "CrimeMajorHeadID" INTEGER,
  "CrimeMinorHeadID" INTEGER,
  "CaseStatusID" INTEGER,
  "CourtID" INTEGER,
  "IncidentFromDate" TEXT,
  "IncidentToDate" TEXT,
  "InfoReceivedPSDate" TEXT,
  "latitude" REAL,
  "longitude" REAL,
  "BriefFacts" TEXT
);

CREATE TABLE IF NOT EXISTS "ComplainantDetails" (
  "ComplainantID" INTEGER,
  "CaseMasterID" INTEGER,
  "ComplainantName" TEXT,
  "AgeYear" INTEGER,
  "OccupationID" INTEGER,
  "ReligionID" INTEGER,
  "CasteID" INTEGER,
  "GenderID" INTEGER
);

CREATE TABLE IF NOT EXISTS "ActSectionAssociation" (
  "CaseMasterID" INTEGER,
  "ActID" INTEGER,
  "SectionID" INTEGER,
  "ActOrderID" INTEGER,
  "SectionOrderID" INTEGER
);

CREATE TABLE IF NOT EXISTS "Victim" (
  "VictimMasterID" INTEGER,
  "CaseMasterID" INTEGER,
  "VictimName" TEXT,
  "AgeYear" INTEGER,
  "GenderID" INTEGER,
  "VictimPolice" TEXT
);

CREATE TABLE IF NOT EXISTS "Accused" (
  "AccusedMasterID" INTEGER,
  "CaseMasterID" INTEGER,
  "AccusedName" TEXT,
  "AgeYear" INTEGER,
  "GenderID" INTEGER,
  "PersonID" TEXT
);

CREATE TABLE IF NOT EXISTS "ArrestSurrender" (
  "ArrestSurrenderID" INTEGER,
  "CaseMasterID" INTEGER,
  "ArrestSurrenderTypeID" INTEGER,
  "ArrestSurrenderDate" TEXT,
  "ArrestSurrenderStateId" INTEGER,
  "ArrestSurrenderDistrictId" INTEGER,
  "PoliceStationID" INTEGER,
  "IOID" INTEGER,
  "CourtID" INTEGER,
  "AccusedMasterID" INTEGER,
  "IsAccused" INTEGER,
  "IsComplainantAccused" INTEGER
);

CREATE TABLE IF NOT EXISTS "Act" (
  "ActCode" TEXT,
  "ActDescription" TEXT,
  "ShortName" TEXT,
  "Active" INTEGER
);

CREATE TABLE IF NOT EXISTS "Section" (
  "ActCode" TEXT,
  "SectionCode" TEXT,
  "SectionDescription" TEXT,
  "Active" INTEGER
);

CREATE TABLE IF NOT EXISTS "CrimeHeadActSection" (
  "CrimeHeadID" INTEGER,
  "ActCode" TEXT,
  "SectionCode" TEXT
);

CREATE TABLE IF NOT EXISTS "CrimeHead" (
  "CrimeHeadID" INTEGER,
  "CrimeGroupName" TEXT,
  "Active" INTEGER
);

CREATE TABLE IF NOT EXISTS "CrimeSubHead" (
  "CrimeSubHeadID" INTEGER,
  "CrimeHeadID" INTEGER,
  "CrimeHeadName" TEXT,
  "SeqID" INTEGER
);

CREATE TABLE IF NOT EXISTS "CasteMaster" (
  "caste_master_id" INTEGER,
  "caste_master_name" TEXT
);

CREATE TABLE IF NOT EXISTS "ReligionMaster" (
  "ReligionID" INTEGER,
  "ReligionName" TEXT
);

CREATE TABLE IF NOT EXISTS "OccupationMaster" (
  "OccupationID" INTEGER,
  "OccupationName" TEXT
);

CREATE TABLE IF NOT EXISTS "CaseStatusMaster" (
  "CaseStatusID" INTEGER,
  "CaseStatusName" TEXT
);

CREATE TABLE IF NOT EXISTS "Court" (
  "CourtID" INTEGER,
  "CourtName" TEXT,
  "DistrictID" INTEGER,
  "StateID" INTEGER,
  "Active" INTEGER
);

CREATE TABLE IF NOT EXISTS "District" (
  "DistrictID" INTEGER,
  "DistrictName" TEXT,
  "StateID" INTEGER,
  "Active" INTEGER
);

CREATE TABLE IF NOT EXISTS "State" (
  "StateID" INTEGER,
  "StateName" TEXT,
  "NationalityID" INTEGER,
  "Active" INTEGER
);

CREATE TABLE IF NOT EXISTS "Unit" (
  "UnitID" INTEGER,
  "UnitName" TEXT,
  "TypeID" INTEGER,
  "ParentUnit" INTEGER,
  "NationalityID" INTEGER,
  "StateID" INTEGER,
  "DistrictID" INTEGER,
  "Active" INTEGER
);

CREATE TABLE IF NOT EXISTS "UnitType" (
  "UnitTypeID" INTEGER,
  "UnitTypeName" TEXT,
  "CityDistState" TEXT,
  "Hierarchy" INTEGER,
  "Active" INTEGER
);

CREATE TABLE IF NOT EXISTS "Rank" (
  "RankID" INTEGER,
  "RankName" TEXT,
  "Hierarchy" INTEGER,
  "Active" INTEGER
);

CREATE TABLE IF NOT EXISTS "Designation" (
  "DesignationID" INTEGER,
  "DesignationName" TEXT,
  "Active" INTEGER,
  "SortOrder" INTEGER
);

CREATE TABLE IF NOT EXISTS "Employee" (
  "EmployeeID" INTEGER,
  "DistrictID" INTEGER,
  "UnitID" INTEGER,
  "RankID" INTEGER,
  "DesignationID" INTEGER,
  "KGID" TEXT,
  "FirstName" TEXT,
  "EmployeeDOB" TEXT,
  "GenderID" INTEGER,
  "BloodGroupID" INTEGER,
  "PhysicallyChallenged" INTEGER,
  "AppointmentDate" TEXT
);

CREATE TABLE IF NOT EXISTS "CaseCategory" (
  "CaseCategoryID" INTEGER,
  "LookupValue" TEXT
);

CREATE TABLE IF NOT EXISTS "GravityOffence" (
  "GravityOffenceID" INTEGER,
  "LookupValue" TEXT
);

CREATE TABLE IF NOT EXISTS "ChargesheetDetails" (
  "CSID" INTEGER,
  "CaseMasterID" INTEGER,
  "csdate" TEXT,
  "cstype" TEXT,
  "PolicePersonID" INTEGER
);

CREATE TABLE IF NOT EXISTS "AuditLog" (
  "AuditID" INTEGER PRIMARY KEY AUTOINCREMENT,
  "EmployeeID" INTEGER,
  "RankHierarchy" INTEGER,
  "Question" TEXT,
  "GeneratedSQL" TEXT,
  "ExecutedSQL" TEXT,
  "CrimeNos" TEXT,
  "RowCount" INTEGER,
  "Timestamp" TEXT
);
