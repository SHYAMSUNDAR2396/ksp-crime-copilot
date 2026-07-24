"""Seeded synthetic data generator for the KSP crime schema.

Deterministic by construction: every random draw comes from one seeded
random.Random instance, and rows are inserted in a fixed order. The eval
suite's gold SQL depends on this.
"""
import argparse
import csv
import datetime as dt
import os
import random
import sqlite3

from functions.crime_query import catalog

SEED = 20260709
TOTAL_CASES = 5000
BASE_CASES = 4820
TREND_CASES = 120       # Two-Wheeler Theft uplift, Bengaluru East, last 90 days
CLUSTER_CASES = 60      # tight burglary cluster for DBSCAN

START_DATE = dt.date(2024, 7, 1)
END_DATE = dt.date(2026, 6, 30)
TREND_START = dt.date(2026, 4, 1)

CLUSTER_CENTRE = (12.9850, 77.6600)
CLUSTER_RADIUS_DEG = 0.0018  # ~200 m at Bengaluru's latitude
RAVI_SPELLINGS = ["Ravi Kumar", "Ravi K", "R. Kumar", "Ravikumar"]
DEMO_CASE_IDS = {}

STATES = [(1, "Karnataka", 1, 1)]
DISTRICTS = [(1, "Bengaluru City", 1, 1), (2, "Mysuru", 1, 1), (3, "Belagavi", 1, 1)]
DISTRICT_CENTRES = {1: (12.9716, 77.5946), 2: (12.2958, 76.6394), 3: (15.8497, 74.4977)}

UNIT_TYPES = [(1, "Police Station", "City", 3, 1), (2, "Circle Office", "District", 2, 1),
              (3, "District HQ", "District", 1, 1)]
UNIT_NAMES = [
    (1, "Bengaluru East", 1), (2, "Bengaluru West", 1),
    (3, "Bengaluru South", 1), (4, "Bengaluru North", 1),
    (5, "Mysuru North", 2), (6, "Mysuru South", 2),
    (7, "Nazarbad", 2), (8, "Krishnaraja", 2),
    (9, "Belagavi City", 3), (10, "Belagavi Rural", 3),
    (11, "Tilakwadi", 3), (12, "Camp", 3),
]

RANKS = [(1, "DGP", 1, 1), (2, "IGP", 2, 1), (3, "SP", 3, 1),
         (4, "Inspector", 4, 1), (5, "Sub-Inspector", 5, 1), (6, "Constable", 6, 1)]
DESIGNATIONS = [(1, "SHO", 1, 1), (2, "Investigating Officer", 1, 2),
                (3, "Beat Constable", 1, 3), (4, "Superintendent of Police", 1, 4)]

CRIME_HEADS = [(1, "Crimes Against Body", 1), (2, "Crimes Against Property", 1),
               (3, "Crimes Against Women", 1), (4, "Economic Offences", 1)]
CRIME_SUBHEADS = [
    (1, 1, "Murder", 1), (2, 1, "Attempt to Murder", 2), (3, 1, "Hurt", 3),
    (4, 2, "Burglary", 4), (5, 2, "Theft", 5), (6, 2, "Two-Wheeler Theft", 6),
    (7, 2, "Robbery", 7), (8, 2, "Dacoity", 8),
    (9, 3, "Assault on Woman", 9), (10, 3, "Dowry Harassment", 10),
    (11, 4, "Cheating", 11), (12, 4, "Criminal Breach of Trust", 12),
]

ACTS = [("IPC", "Indian Penal Code, 1860", "IPC", 1),
        ("NDPS", "Narcotic Drugs and Psychotropic Substances Act, 1985", "NDPS", 1),
        ("POCSO", "Protection of Children from Sexual Offences Act, 2012", "POCSO", 1),
        ("MVA", "Motor Vehicles Act, 1988", "MVA", 1)]
SECTIONS = [
    ("IPC", "302", "Punishment for murder", 1),
    ("IPC", "307", "Attempt to murder", 1),
    ("IPC", "323", "Punishment for voluntarily causing hurt", 1),
    ("IPC", "354", "Assault on woman with intent to outrage her modesty", 1),
    ("IPC", "379", "Punishment for theft", 1),
    ("IPC", "380", "Theft in dwelling house", 1),
    ("IPC", "392", "Punishment for robbery", 1),
    ("IPC", "395", "Punishment for dacoity", 1),
    ("IPC", "406", "Punishment for criminal breach of trust", 1),
    ("IPC", "420", "Cheating and dishonestly inducing delivery of property", 1),
    ("IPC", "457", "Lurking house-trespass by night", 1),
    ("IPC", "498A", "Husband or relative subjecting woman to cruelty", 1),
    ("NDPS", "20", "Contravention in relation to cannabis plant", 1),
    ("POCSO", "4", "Punishment for penetrative sexual assault", 1),
    ("MVA", "184", "Driving dangerously", 1),
]
SUBHEAD_SECTIONS = {
    1: [("IPC", "302")], 2: [("IPC", "307")], 3: [("IPC", "323")],
    4: [("IPC", "457"), ("IPC", "380")], 5: [("IPC", "379")],
    6: [("IPC", "379")], 7: [("IPC", "392")], 8: [("IPC", "395")],
    9: [("IPC", "354")], 10: [("IPC", "498A")],
    11: [("IPC", "420")], 12: [("IPC", "406")],
}

CASE_STATUSES = [(1, "Under Investigation"), (2, "Charge Sheeted"), (3, "Closed")]
CASE_CATEGORIES = [(1, "FIR"), (3, "UDR"), (4, "PAR"), (8, "Zero FIR")]
GRAVITY = [(1, "Heinous"), (2, "Non-Heinous")]
HEINOUS_SUBHEADS = {1, 2, 7, 8, 9}  # Murder, Attempt, Robbery, Dacoity, Assault on Woman

CASTES = [(1, "General"), (2, "Scheduled Caste"), (3, "Scheduled Tribe"),
          (4, "Other Backward Class"), (5, "Not Recorded")]
RELIGIONS = [(1, "Hindu"), (2, "Muslim"), (3, "Christian"), (4, "Jain"), (5, "Other")]
OCCUPATIONS = [(1, "Farmer"), (2, "Government Employee"), (3, "Private Employee"),
               (4, "Business"), (5, "Student"), (6, "Daily Wage Labourer"),
               (7, "Homemaker"), (8, "Unemployed")]

FIRST_NAMES = ["Ravi", "Suresh", "Manjunath", "Lakshmi", "Girish", "Anitha", "Prakash",
               "Shobha", "Nagaraj", "Vinod", "Kavitha", "Basavaraj", "Deepa", "Mahesh",
               "Sunitha", "Harish", "Roopa", "Chandru", "Geetha", "Srinivas"]
LAST_NAMES = ["Kumar", "Gowda", "Reddy", "Shetty", "Patil", "Hegde", "Rao", "Naik",
              "Murthy", "Bhat", "Desai", "Kulkarni"]

BRIEF_FACTS = {
    1: "Deceased found with stab injuries near {place}. Motive suspected to be a prior dispute.",
    2: "Accused attacked complainant with a sharp weapon near {place}; victim hospitalised.",
    3: "Quarrel over parking near {place} escalated; complainant sustained blunt injuries.",
    4: "House lock broken between {t1} and {t2} at {place}; gold ornaments and cash taken.",
    5: "Mobile phone and wallet stolen from complainant at {place} in a crowded market.",
    6: "Two-wheeler parked outside {place} found missing; no CCTV coverage at the spot.",
    7: "Two persons on a motorcycle snatched a chain from complainant near {place}.",
    8: "Armed group entered premises at {place} and decamped with valuables.",
    9: "Accused outraged the modesty of the complainant near {place}; witnesses present.",
    10: "Complainant harassed by in-laws for additional dowry at her residence in {place}.",
    11: "Accused induced complainant to transfer funds on a false investment promise.",
    12: "Entrusted goods at {place} were misappropriated by the accused.",
}
PLACES = ["the main market", "a residential layout", "the bus terminus", "an industrial estate",
          "the temple street", "a commercial complex", "the ring road junction", "a park"]


def _point_in_cluster(rng, centre):
    """Uniform-ish point strictly inside CLUSTER_RADIUS_DEG of centre.

    Rejection sampling, so the radius is a guarantee and not a 3-sigma hope.
    """
    while True:
        dlat = rng.gauss(0, CLUSTER_RADIUS_DEG / 3.0)
        dlon = rng.gauss(0, CLUSTER_RADIUS_DEG / 3.0)
        if (dlat * dlat + dlon * dlon) <= CLUSTER_RADIUS_DEG ** 2:
            return centre[0] + dlat, centre[1] + dlon


def _pick_variant_cases(cases, units=(1, 2, 5), count=4):
    """Case IDs for the seeded name variants: one per station, then topped up.

    Deterministic: `cases` is already in CaseMasterID order, and we never
    consume the RNG here.
    """
    by_unit = {}
    for case in cases:
        by_unit.setdefault(case[5], []).append(case[0])

    picked = [by_unit[unit][0] for unit in units]
    for unit in units:
        for case_id in by_unit[unit][1:]:
            if len(picked) == count:
                break
            picked.append(case_id)
        if len(picked) == count:
            break

    if len(picked) != count:
        raise AssertionError("not enough candidate cases for name variants")
    return picked


def _iso(date):
    return date.isoformat()


def _dt(date, hour, minute):
    return "{0} {1:02d}:{2:02d}:00".format(date.isoformat(), hour, minute)


def _crime_no(category_id, district_id, unit_id, year, serial):
    return "{0}{1:04d}{2:04d}{3:04d}{4:05d}".format(
        category_id, district_id, unit_id, year, serial
    )


def _employees():
    rows = []
    emp_id = 1
    for unit_id, _name, district_id in UNIT_NAMES:
        plan = [(4, 1)] + [(5, 2)] * 2 + [(6, 3)] * 5
        for rank_id, desig_id in plan:
            rows.append((emp_id, district_id, unit_id, rank_id, desig_id,
                         "KGID{0:05d}".format(emp_id), FIRST_NAMES[emp_id % len(FIRST_NAMES)],
                         "1985-01-01", 1, 1, 0, "2010-06-01"))
            emp_id += 1
    for district_id, _name, _s, _a in DISTRICTS:
        first_unit = district_id * 4 - 3
        rows.append((emp_id, district_id, first_unit, 3, 4, "KGID{0:05d}".format(emp_id),
                     "SP", "1975-01-01", 1, 1, 0, "2000-06-01"))
        emp_id += 1
    rows.append((emp_id, 1, 1, 1, 4, "KGID{0:05d}".format(emp_id), "DGP",
                 "1968-01-01", 1, 1, 0, "1992-06-01"))
    return rows


def _make_case(rng, case_id, unit_id, district_id, subhead_id, reg_date, lat, lon, serials):
    category_id = 1 if rng.random() < 0.92 else rng.choice([3, 4, 8])
    year = reg_date.year
    key = (unit_id, category_id, year)
    serials[key] = serials.get(key, 0) + 1
    crime_no = _crime_no(category_id, district_id, unit_id, year, serials[key])

    officers = [e for e in EMPLOYEES if e[2] == unit_id and e[3] in (4, 5)]
    officer = officers[case_id % len(officers)][0]

    head_id = next(s[1] for s in CRIME_SUBHEADS if s[0] == subhead_id)
    gravity = 1 if subhead_id in HEINOUS_SUBHEADS else 2
    status = rng.choices([1, 2, 3], weights=[5, 3, 2])[0]
    court_id = district_id

    incident = reg_date - dt.timedelta(days=rng.randint(0, 2))
    hour = rng.choices(range(24), weights=[3] * 6 + [1] * 12 + [3] * 6)[0]
    minute = rng.choice([0, 15, 30, 45])
    from_dt = _dt(incident, hour, minute)
    to_dt = _dt(incident, min(hour + 1, 23), minute)
    info_dt = _dt(reg_date, min(hour + 2, 23), minute)

    facts = BRIEF_FACTS[subhead_id].format(
        place=rng.choice(PLACES), t1="{0:02d}:00".format(hour), t2="{0:02d}:00".format(min(hour + 4, 23))
    )
    return (case_id, crime_no, crime_no[-9:], _iso(reg_date), officer, unit_id,
            category_id, gravity, head_id, subhead_id, status, court_id,
            from_dt, to_dt, info_dt, round(lat, 6), round(lon, 6), facts)


EMPLOYEES = _employees()


def _remap_foreign_keys_to_rowid(conn):
    """Rewrite every foreign-key column to hold the parent row's SQLite
    rowid instead of its business primary key.

    Catalyst's Data Store "Foreign Key" columns can only reference a
    parent's platform-assigned ROWID, never a business key -- confirmed
    against a live deployment. Shaping SQLite's data the same way means
    the exact SQL the LLM generates (which always joins on ROWID, per
    prompt.py's rules) runs correctly against SqliteDB in tests and
    ZcqlDB in production, instead of diverging by backend.

    Runs after every table is populated (all parent rows already have
    their final rowid), and before CSV export in build() -- the CSVs
    keep business-key values, since the live Catalyst import path remaps
    them separately, once each relationship's real ROWIDs exist there.
    """
    for child, child_col, parent, parent_col in catalog.FOREIGN_KEYS:
        conn.execute(
            'UPDATE "{0}" SET "{1}" = ('
            '  SELECT rowid FROM "{2}" WHERE "{2}"."{3}" = "{0}"."{1}"'
            ')'.format(child, child_col, parent, parent_col)
        )
    conn.commit()


def build(sqlite_path, csv_dir=None, seed=SEED):
    rng = random.Random(seed)
    if os.path.exists(sqlite_path):
        os.remove(sqlite_path)
    os.makedirs(os.path.dirname(os.path.abspath(sqlite_path)), exist_ok=True)
    conn = sqlite3.connect(sqlite_path)
    conn.executescript(catalog.sqlite_ddl())

    data = {
        "State": STATES,
        "District": DISTRICTS,
        "UnitType": UNIT_TYPES,
        "Unit": [(uid, name, 1, None, 1, 1, did, 1) for uid, name, did in UNIT_NAMES],
        "Rank": RANKS,
        "Designation": DESIGNATIONS,
        "Employee": EMPLOYEES,
        "CrimeHead": CRIME_HEADS,
        "CrimeSubHead": CRIME_SUBHEADS,
        "CaseStatusMaster": CASE_STATUSES,
        "CaseCategory": CASE_CATEGORIES,
        "GravityOffence": GRAVITY,
        "Court": [(d[0], "{0} District Court".format(d[1]), d[0], 1, 1) for d in DISTRICTS],
        "CasteMaster": CASTES,
        "ReligionMaster": RELIGIONS,
        "OccupationMaster": OCCUPATIONS,
        "Act": ACTS,
        "Section": SECTIONS,
        "CrimeHeadActSection": sorted({
            (head, act, sec)
            for sub_id, head, _n, _q in CRIME_SUBHEADS
            for act, sec in SUBHEAD_SECTIONS[sub_id]
        }),
    }

    span = (END_DATE - START_DATE).days
    serials = {}
    cases, complainants, victims, accused_rows, arrests, act_secs, chargesheets = \
        [], [], [], [], [], [], []

    plan = []
    for _ in range(BASE_CASES):
        unit_id = rng.randint(1, 12)
        subhead_id = rng.choices(
            [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            weights=[1, 2, 12, 14, 18, 10, 6, 1, 6, 5, 8, 4],
        )[0]
        reg = START_DATE + dt.timedelta(days=rng.randint(0, span))
        plan.append((unit_id, subhead_id, reg, None))
    for _ in range(TREND_CASES):
        offset = rng.randint(0, (END_DATE - TREND_START).days)
        plan.append((1, 6, TREND_START + dt.timedelta(days=offset), None))
    for _ in range(CLUSTER_CASES):
        reg = START_DATE + dt.timedelta(days=rng.randint(0, span))
        plan.append((1, 4, reg, CLUSTER_CENTRE))

    plan.sort(key=lambda p: (p[2], p[0], p[1]))

    comp_id = victim_id = accused_id = arrest_id = cs_id = 1
    for index, (unit_id, subhead_id, reg, forced_centre) in enumerate(plan, start=1):
        district_id = next(d for u, _n, d in UNIT_NAMES if u == unit_id)
        if forced_centre:
            lat, lon = _point_in_cluster(rng, forced_centre)
        else:
            clat, clon = DISTRICT_CENTRES[district_id]
            lat, lon = clat + rng.gauss(0, 0.05), clon + rng.gauss(0, 0.05)
        case = _make_case(rng, index, unit_id, district_id, subhead_id, reg, lat, lon, serials)
        cases.append(case)

        name = "{0} {1}".format(rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES))
        complainants.append((comp_id, index, name, rng.randint(18, 70),
                             rng.randint(1, 8), rng.randint(1, 5), rng.randint(1, 5),
                             rng.choice([1, 2])))
        comp_id += 1

        for _ in range(rng.randint(0, 2)):
            victims.append((victim_id, index,
                            "{0} {1}".format(rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)),
                            rng.randint(5, 80), rng.choice([1, 2]), "0"))
            victim_id += 1

        n_accused = rng.randint(1, 3)
        case_accused = []
        for slot in range(n_accused):
            accused_rows.append((accused_id, index,
                                 "{0} {1}".format(rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)),
                                 rng.randint(18, 60), rng.choice([1, 2]),
                                 "A{0}".format(slot + 1)))
            case_accused.append(accused_id)
            accused_id += 1

        if rng.random() < 0.4:
            io = [e for e in EMPLOYEES if e[2] == unit_id and e[3] == 5][0][0]
            arrests.append((arrest_id, index, 1,
                            _iso(reg + dt.timedelta(days=rng.randint(1, 30))),
                            1, district_id, unit_id, io, district_id,
                            case_accused[0], 1, 0))
            arrest_id += 1

        for order, (act, sec) in enumerate(SUBHEAD_SECTIONS[subhead_id], start=1):
            act_secs.append((index, act, sec, 1, order))

        status = case[10]
        if status == 2:
            chargesheets.append((cs_id, index,
                                 _dt(reg + dt.timedelta(days=rng.randint(30, 90)), 10, 0),
                                 "A", case[4]))
            cs_id += 1

    # Seeded name variants: one person, four spellings, at least three stations.
    variant_targets = _pick_variant_cases(cases)
    for spelling, case_id in zip(RAVI_SPELLINGS, variant_targets):
        accused_rows.append((accused_id, case_id, spelling, 31, 1, "A9"))
        accused_id += 1

    # Deterministic Kannada/English MO pair for the cross-lingual retrieval
    # demo. Only BriefFacts changes; schema shape, counts, and foreign keys do
    # not change.
    burglary_ids = [row[0] for row in cases if row[9] == 4]
    bilingual_ids = tuple(burglary_ids[:2])
    if len(bilingual_ids) == 2:
        for position, case_id in enumerate(bilingual_ids):
            row_index = case_id - 1
            row = cases[row_index]
            narrative = (
                "ಬಾಗಿಲು ಮುರಿದು ಮನೆಗೆ ಪ್ರವೇಶಿಸಿ ಚಿನ್ನಾಭರಣ ಮತ್ತು ನಗದು ಕಳವು ಮಾಡಲಾಗಿದೆ."
                if position == 0
                else "House lock broken; gold ornaments and cash were taken from the residence."
            )
            cases[row_index] = row[:-1] + (narrative,)

    DEMO_CASE_IDS.clear()
    DEMO_CASE_IDS.update({
        "ravi_variants": tuple(variant_targets),
        "bilingual_mo_pair": bilingual_ids,
        "hotspot_candidates": tuple(row[0] for row in cases if row[9] == 4)[:CLUSTER_CASES],
    })

    data["CaseMaster"] = cases
    data["ComplainantDetails"] = complainants
    data["Victim"] = victims
    data["Accused"] = accused_rows
    data["ArrestSurrender"] = arrests
    data["ActSectionAssociation"] = act_secs
    data["ChargesheetDetails"] = chargesheets

    counts = {}
    for table in catalog.TABLES:
        rows = data[table]
        columns = list(catalog.TABLES[table])
        placeholders = ",".join("?" for _ in columns)
        quoted = ",".join('"{0}"'.format(c) for c in columns)
        conn.executemany(
            'INSERT INTO "{0}" ({1}) VALUES ({2})'.format(table, quoted, placeholders),
            rows,
        )
        counts[table] = len(rows)
    conn.commit()

    _remap_foreign_keys_to_rowid(conn)

    if csv_dir:
        os.makedirs(csv_dir, exist_ok=True)
        for table in sorted(catalog.TABLES):
            path = os.path.join(csv_dir, "{0}.csv".format(table))
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow(list(catalog.TABLES[table]))
                writer.writerows(data[table])

    conn.close()
    return counts


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic KSP crime data.")
    parser.add_argument("--sqlite", default="build/crime.db")
    parser.add_argument("--csv", default="build/csv")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    counts = build(args.sqlite, args.csv, args.seed)
    for table, count in sorted(counts.items()):
        print("{0:24s} {1:>6d}".format(table, count))


if __name__ == "__main__":
    main()
