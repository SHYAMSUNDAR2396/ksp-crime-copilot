-- Versioned derived relationship projection.
-- These are application tables, not additions to the authoritative FIR ER model.
CREATE TABLE IF NOT EXISTS "PersonNode" (
  "NodeID" TEXT NOT NULL,
  "NormalizedName" TEXT NOT NULL,
  "AgeBand" INTEGER NOT NULL,
  "GenderID" TEXT,
  "Confidence" REAL NOT NULL,
  "ResolutionVersion" TEXT NOT NULL,
  "UpdatedAt" TEXT NOT NULL,
  UNIQUE ("NodeID", "ResolutionVersion")
);
CREATE TABLE IF NOT EXISTS "PersonMember" (
  "MemberID" INTEGER PRIMARY KEY AUTOINCREMENT,
  "NodeID" TEXT NOT NULL,
  "CaseMasterID" INTEGER NOT NULL,
  "Role" TEXT NOT NULL,
  "SourceName" TEXT NOT NULL,
  "AgeYear" INTEGER,
  "GenderID" TEXT,
  "SourceCrimeNo" TEXT NOT NULL,
  "ResolutionVersion" TEXT NOT NULL,
  "UpdatedAt" TEXT NOT NULL,
  UNIQUE ("NodeID", "CaseMasterID", "Role", "ResolutionVersion")
);
CREATE TABLE IF NOT EXISTS "EdgePersonCase" (
  "EdgeID" INTEGER PRIMARY KEY AUTOINCREMENT,
  "NodeID" TEXT NOT NULL,
  "CaseMasterID" INTEGER NOT NULL,
  "Role" TEXT NOT NULL,
  "Confidence" REAL NOT NULL,
  "SourceCrimeNo" TEXT NOT NULL,
  "ResolutionVersion" TEXT NOT NULL,
  "UpdatedAt" TEXT NOT NULL,
  UNIQUE ("NodeID", "CaseMasterID", "Role", "ResolutionVersion")
);
CREATE TABLE IF NOT EXISTS "EdgeCaseEmployee" (
  "EdgeID" INTEGER PRIMARY KEY AUTOINCREMENT,
  "CaseMasterID" INTEGER NOT NULL,
  "EmployeeID" INTEGER NOT NULL,
  "Role" TEXT NOT NULL,
  "Confidence" REAL NOT NULL,
  "SourceCrimeNo" TEXT NOT NULL,
  "ResolutionVersion" TEXT NOT NULL,
  "UpdatedAt" TEXT NOT NULL,
  UNIQUE ("CaseMasterID", "EmployeeID", "Role", "ResolutionVersion")
);
CREATE TABLE IF NOT EXISTS "EdgeCaseSection" (
  "EdgeID" INTEGER PRIMARY KEY AUTOINCREMENT,
  "CaseMasterID" INTEGER NOT NULL,
  "SectionID" TEXT NOT NULL,
  "Confidence" REAL NOT NULL,
  "SourceCrimeNo" TEXT NOT NULL,
  "ResolutionVersion" TEXT NOT NULL,
  "UpdatedAt" TEXT NOT NULL,
  UNIQUE ("CaseMasterID", "SectionID", "ResolutionVersion")
);
CREATE TABLE IF NOT EXISTS "EdgeCaseNear" (
  "EdgeID" INTEGER PRIMARY KEY AUTOINCREMENT,
  "CaseMasterID" INTEGER NOT NULL,
  "RelatedCaseID" INTEGER NOT NULL,
  "DistanceKm" REAL NOT NULL,
  "Confidence" REAL NOT NULL,
  "SourceCrimeNos" TEXT NOT NULL,
  "ResolutionVersion" TEXT NOT NULL,
  "UpdatedAt" TEXT NOT NULL,
  UNIQUE ("CaseMasterID", "RelatedCaseID", "ResolutionVersion")
);
CREATE TABLE IF NOT EXISTS "GraphProjectionState" (
  "ProjectionName" TEXT PRIMARY KEY,
  "ActiveVersion" TEXT NOT NULL,
  "UpdatedAt" TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS "idx_EdgePersonCase_CaseVersion"
  ON "EdgePersonCase" ("CaseMasterID", "ResolutionVersion");
CREATE INDEX IF NOT EXISTS "idx_EdgeCaseNear_CaseVersion"
  ON "EdgeCaseNear" ("CaseMasterID", "ResolutionVersion");
