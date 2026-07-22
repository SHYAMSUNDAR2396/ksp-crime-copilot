-- Operational tables only. These are fixed application queries, never exposed
-- through the NL-to-ZCQL schema catalog.
CREATE TABLE IF NOT EXISTS SilentMatchAlert (
  AlertID INTEGER PRIMARY KEY AUTOINCREMENT,
  AlertType TEXT NOT NULL,
  AnchorCaseID INTEGER NOT NULL,
  MatchedCaseID INTEGER NOT NULL,
  AnchorCrimeNo TEXT NOT NULL,
  MatchedCrimeNo TEXT NOT NULL,
  Score INTEGER NOT NULL,
  ConfidenceBand TEXT NOT NULL,
  Status TEXT NOT NULL DEFAULT 'New',
  EvidenceJSON TEXT NOT NULL,
  EvidenceSnapshotJSON TEXT NOT NULL,
  SourceRunID TEXT NOT NULL,
  IndexVersion TEXT NOT NULL DEFAULT '',
  CreatedAt TEXT NOT NULL,
  UpdatedAt TEXT NOT NULL,
  UNIQUE (AlertType, AnchorCaseID, MatchedCaseID)
);
CREATE TABLE IF NOT EXISTS SilentMatchRecipient (
  RecipientID INTEGER PRIMARY KEY AUTOINCREMENT,
  AlertID INTEGER NOT NULL,
  EmployeeID INTEGER NOT NULL,
  SeenAt TEXT,
  UNIQUE (AlertID, EmployeeID)
);
CREATE TABLE IF NOT EXISTS SilentMatchAction (
  ActionID INTEGER PRIMARY KEY AUTOINCREMENT,
  AlertID INTEGER NOT NULL,
  ActionType TEXT NOT NULL,
  Note TEXT NOT NULL,
  EmployeeID INTEGER NOT NULL,
  CreatedAt TEXT NOT NULL,
  PreviousScore INTEGER,
  PreviousConfidenceBand TEXT,
  EvidenceSnapshotJSON TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS SilentMatchRun (
  RunID TEXT PRIMARY KEY,
  TriggerSource TEXT NOT NULL,
  Status TEXT NOT NULL,
  AnchorsSeen INTEGER NOT NULL DEFAULT 0,
  CandidatesSeen INTEGER NOT NULL DEFAULT 0,
  AlertsCreated INTEGER NOT NULL DEFAULT 0,
  StartedAt TEXT NOT NULL,
  FinishedAt TEXT
);
CREATE TABLE IF NOT EXISTS MoEmbeddingRecord (
  CaseMasterID INTEGER PRIMARY KEY,
  CrimeNo TEXT NOT NULL,
  IndexVersion TEXT NOT NULL,
  Provider TEXT NOT NULL,
  VectorJSON TEXT NOT NULL,
  UpdatedAt TEXT NOT NULL
);
