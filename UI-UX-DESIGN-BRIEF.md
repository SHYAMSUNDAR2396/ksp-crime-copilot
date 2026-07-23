# UI/UX Design Brief — KSP Crime Copilot

**Project**: Conversational AI for the Karnataka State Police Crime Database
**Competition**: Datathon 2026, KSP SCRB Challenge 01
**Platform**: Zoho Catalyst (Web Client Hosting)
**Audience**: Karnataka State Police personnel — Constables, Inspectors, Superintendents of Police (SP), Crime Branch officers
**Date**: July 2026

---

## 1. What this product is

KSP Crime Copilot is a **conversational AI assistant** that lets police officers query a 26-table crime database using natural language — in **Kannada or English** — and receive cited, explainable answers with interactive visualizations.

The officer speaks or types a question like *"ಬೆಂಗಳೂರು ಪೂರ್ವದಲ್ಲಿ ಕಳೆದ 6 ತಿಂಗಳಲ್ಲಿ ಕಳ್ಳತನ ಪ್ರಕರಣಗಳು?"* (Show me theft cases in Bengaluru East in the last 6 months), and gets back a structured answer with clickable CrimeNo citations, a hotspot map, trend charts, and optionally a network graph — all in the same language.

This is **not** a chatbot for the public. It is an **internal investigative tool** used by trained police officers. The design language should convey **authority, precision, and trust** — like a well-built cockpit dashboard, not a consumer app.

---

## 2. Users and personas

### 2.1 Constable / Field Officer (Primary)

- **Tech comfort**: Low-medium. Uses a smartphone daily but may struggle with complex UIs.
- **Primary use**: Quick lookups — "How many murder cases in my station this quarter?" "Show me FIR 2025-0412."
- **Interaction style**: Voice-first (Kannada). Prefers short answers with numbers.
- **Needs**: Fast answers, zero ambiguity, citations to verify, Kannada support non-negotiable.
- **Login**: Their rank automatically scopes all data to their station/district.

### 2.2 Inspector / SHO (Secondary)

- **Tech comfort**: Medium-high. Comfortable with dashboards and databases.
- **Primary use**: Pattern analysis — "Are there linked cases?" "What's the trend for robbery in my jurisdiction?"
- **Interaction style**: Text + voice. Follow-up questions. Drill-downs.
- **Needs**: Multi-turn context (the system remembers previous filters), ability to drill into specific cases, RBAC that shows more data (unmasked demographics).

### 2.3 SP / Crime Branch (Tertiary — power user)

- **Tech comfort**: High. Expects analytics-grade tools.
- **Primary use**: Network analysis, predictive briefings, hotspot maps — "Show me repeat offenders near this cluster" "Generate a prevention briefing."
- **Interaction style**: Text-heavy. Expects exportable reports (PDF).
- **Needs**: Full access to all features, graph visualizations, PDF export, proactive intelligence cards.

---

## 3. Core screens — Information Architecture

```
┌─────────────────────────────────────────────────┐
│                  APP SHELL                        │
│  ┌─────────────────────────────────────────────┐ │
│  │  HEADER BAR                                  │ │
│  │  Logo · App Name · Role Badge · Lang Toggle  │ │
│  └─────────────────────────────────────────────┘ │
│                                                   │
│  ┌──────────────┐  ┌───────────────────────────┐ │
│  │              │  │                           │ │
│  │  SIDEBAR     │  │  MAIN CONTENT AREA        │ │
│  │              │  │                           │ │
│  │  • Chat      │  │  (switches based on       │ │
│  │  • History   │  │   active view)            │ │
│  │  • Analytics │  │                           │ │
│  │    • Trends  │  │                           │ │
│  │    • Map     │  │                           │ │
│  │    • Network │  │                           │ │
│  │  • Briefings │  │                           │ │
│  │  • Audit Log │  │                           │ │
│  │              │  │                           │ │
│  └──────────────┘  └───────────────────────────┘ │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │  INPUT BAR (persistent at bottom)            │ │
│  │  Text field · Mic button · Send · Language    │ │
│  └─────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

### 3.1 Views

| # | View | Default for | What it shows |
|---|------|-------------|---------------|
| V1 | **Chat / Conversation** | All roles | Conversational Q&A thread + inline answer cards |
| V2 | **Citation / Case Detail** | All roles | Full CaseMaster row + BriefFacts excerpt when a citation is clicked |
| V3 | **Hotspot Map** | Inspector+ | Karnataka state map with DBSCAN clusters, station boundaries |
| V4 | **Trend Dashboard** | Inspector+ | Time-series charts: crime counts by station × type |
| V5 | **Network Graph** | SP / Crime Branch | Interactive node-edge graph of linked cases/persons |
| V6 | **Prevention Briefing** | SP / Crime Branch | Composed intelligence cards (trend + network synthesis) |
| V7 | **Audit Log** | All roles (read-only) | Every query logged with timestamp, user, result summary |
| V8 | **PDF Export** | All roles | Print-optimized conversation transcript |

---

## 4. Screen-by-screen design specifications

### 4.1 Header Bar (persistent)

```
┌──────────────────────────────────────────────────────────────┐
│  [KSP Shield]  Crime Copilot   [🇰🇳/EN toggle]  [Inspector R. Meena  ▾]  [🔴 Logout] │
└──────────────────────────────────────────────────────────────┘
```

**Elements:**
- **KSP Shield / Logo**: Karnataka State Police emblem. Left-aligned. 40px height.
- **App Name**: "Crime Copilot" in bold. Optionally subtitle: "SCRB Intelligence Platform".
- **Language Toggle**: Pill toggle — `ಕನ್ನಡ | English`. Active side filled. Clicking switches the entire UI language (labels, prompts, help text). *Note: user names and CrimeNos are never translated.*
- **Role Badge**: Shows logged-in officer's name + rank. Dropdown with: Profile, Audit Log, Export settings, Logout.
- **Role Badge Color Coding**:
  - Constable: `#42566C` (slate)
  - Inspector: `#147878` (teal)
  - SP / Crime Branch: `#B8902A` (brass)

---

### 4.2 Sidebar Navigation

```
┌──────────────┐
│  💬 Chat      │  ← primary, always visible
│  ─────────── │
│  📋 History   │  ← past conversations
│  ─────────── │
│  📊 Analytics │  ← collapsible group
│    📈 Trends  │
│    🗺️ Map     │
│    🔗 Network │  ← SP only
│  ─────────── │
│  📰 Briefings │  ← SP only
│  ─────────── │
│  📝 Audit Log │
│  ─────────── │
│  📄 Export PDF │
└──────────────┘
```

**Behavior:**
- Sidebar collapses to icon-only mode on screens < 1024px (hamburger to expand).
- Active view highlighted with left accent bar (brass `#B8902A`).
- Views restricted by RBAC: Constables see only Chat + History + Audit Log + Export. Inspector+ see Analytics group. SP+ see Network + Briefings.
- Unavailable items are hidden, not grayed out — the UI should not tease features the user cannot access.

---

### 4.3 Chat / Conversation View (V1) — THE PRIMARY SCREEN

This is the screen 90% of users will live in.

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  [ASSISTANT BUBBLE]                                      │  │
│  │  🟢 ನಮಸ್ಕಾರ, Inspector. How can I help today?            │  │
│  │  Suggested queries:                                       │  │
│  │  [ ಕಳೆದ ತಿಂಗಳು ಬೆಂಗಳೂರು ಕೊಲೆ ಪ್ರಕರಣಗಳು ]              │  │
│  │  [ Show FIR trends for my station ]                       │  │
│  │  [ Are there linked theft cases? ]                        │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  [USER BUBBLE]                                           │  │
│  │  ಕಳೆದ 6 ತಿಂಗಳಲ್ಲಿ ಬೆಂಗಳೂರು ಪೂರ್ವದಲ್ಲಿ ಕಳ್ಳತನ?        │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  [ASSISTANT ANSWER CARD]                                 │  │
│  │                                                          │  │
│  │  ┌────────────────────────────────────────────────────┐  │  │
│  │  │  📊 Summary                                        │  │  │
│  │  │  Bengaluru East — Theft — Last 6 months            │  │  │
│  │  │  Total: 47 cases                                   │  │  │
│  │  └────────────────────────────────────────────────────┘  │  │
│  │                                                          │  │
│  │  ┌────────────────────────────────────────────────────┐  │  │
│  │  │  📋 Results Table                                   │  │  │
│  │  │  CrimeNo    │ Type      │ Date       │ Station     │  │  │
│  │  │  2025-0891  │ Theft     │ 2025-03-12 │ Whitefield  │  │  │
│  │  │  2025-0847  │ Theft     │ 2025-02-28 │ Mahadevapura│  │  │
│  │  │  ...       │           │            │             │  │  │
│  │  │  [View All 47 →]                                     │  │  │
│  │  └────────────────────────────────────────────────────┘  │  │
│  │                                                          │  │
│  │  ┌────────────────────────────────────────────────────┐  │  │
│  │  │  🗺️ Mini Hotspot Map                                │  │  │
│  │  │  [embedded map preview with cluster markers]       │  │  │
│  │  │                          [Expand to full map →]    │  │  │
│  │  └────────────────────────────────────────────────────┘  │  │
│  │                                                          │  │
│  │  📎 Citations: [2025-0891] [2025-0847] [2025-0803] ...  │  │
│  │                                                          │  │
│  │  ───────────────────────────────────────────────────     │  │
│  │  🔍 Data source: Structured query (NL→SQL)              │  │
│  │  ⏱️ Response time: 2.3s                                  │  │
│  │  🛡️ RBAC scope: Bengaluru East Division                  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  [USER BUBBLE]                                           │  │
│  │  ಅದರಲ್ಲಿ ದ್ವಿಚಕ್ರ ವಾಹನ ಕಳ್ಳತನ ಮಾತ್ರ                    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  [ASSISTANT ANSWER CARD]                                 │  │
│  │  "Filtered from previous: 12 of 47 cases are            │  │
│  │   two-wheeler theft..."                                  │  │
│  │  📎 Citations: [2025-0891] [2025-0847] ...               │  │
│  │  🔍 Follow-up filter applied (session memory)            │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Key interaction patterns for the chat:**

1. **Answer Cards** — every response is a structured card, not raw text. Cards contain:
   - **Summary strip**: one-line plain-English/Kannada summary of what the answer covers
   - **Data body**: table, chart, map, or narrative depending on query type
   - **Citation row**: clickable CrimeNo badges
   - **Meta footer**: data source type, response time, RBAC scope

2. **Citation Badges** — pill-shaped, clickable. On click → opens Case Detail view (V2) as a slide-over panel.

3. **Mini Visualizations** — when a query involves spatial or trend data, embed a small preview inline (map thumbnail, sparkline). Clicking "Expand" takes the user to the full view (V3/V4).

4. **Session Memory Indicator** — when a follow-up narrows a previous result, show a subtle tag: *"Filtered from previous query"* with a link back to the original question.

5. **Voice Input Button** — large, centered mic button in the input bar. When recording:
   - Pulse animation (red ring)
   - Real-time waveform visualization
   - "Listening..." text in current language
   - Auto-submit after 3s of silence

6. **Loading State** — while the AI processes:
   - Typing indicator with role-specific message: *"Querying the database..."* / *"Analyzing patterns..."* / *"Building network graph..."*
   - Skeleton card (pulsing gray placeholder)
   - If >5s, show progress: *"Found 47 cases. Analyzing clusters..."*

7. **Error States**:
   - *"I couldn't understand that. Could you rephrase?"* — for ambiguous queries
   - *"This query requires Inspector-level access."* — for RBAC blocks
   - *"No cases match your criteria. Try broadening the time range or location."* — for empty results
   - *"I'm having trouble connecting to the database. Please try again."* — for system errors

8. **Suggested Queries** — on new conversations and after long pauses, show 3 contextually relevant suggestions based on the user's role and jurisdiction.

---

### 4.4 Case Detail View (V2) — Slide-over Panel

Opens when a citation badge is clicked. Slides in from the right (40% width, min 480px).

```
┌─────────────────────────────────────────────────────┐
│  ← Back to Chat              FIR 2025-0891     ✕    │
├─────────────────────────────────────────────────────┤
│                                                     │
│  CASE DETAILS                                       │
│  ┌───────────────────────────────────────────────┐  │
│  │ Crime No:        2025-0891                    │  │
│  │ Crime Type:      Theft (IPC 379)              │  │
│  │ Date Registered: 2025-03-12                   │  │
│  │ Station:         Whitefield PS                │  │
│  │ District:        Bengaluru Urban              │  │
│  │ Status:          Under Investigation          │  │
│  │ Gravity:         Cognizable                   │  │
│  │ IO:              SI Rajesh Kumar (PU00412)    │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  NARRATIVE (BriefFacts)                             │
│  ┌───────────────────────────────────────────────┐  │
│  │ "On 12/03/2025 at approximately 14:30 hrs,   │  │
│  │  the complainant reported that their Honda     │  │
│  │  Activa (KA-03-M-4421) was stolen from near   │  │
│  │  ITPL main gate..."                           │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  ACTS & SECTIONS                                    │
│  ┌───────────────────────────────────────────────┐  │
│  │  IPC 379 — Theft                              │  │
│  │  IPC 411 — Stolen property                    │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  LOCATION                                           │
│  ┌───────────────────────────────────────────────┐  │
│  │  [Embedded map pin: lat/long marker]          │  │
│  │  📍 Near ITPL Main Gate, Whitefield           │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  RELATED CASES                                      │
│  ┌───────────────────────────────────────────────┐  │
│  │  🔗 2025-0782 (same IO, same section)         │  │
│  │  🔗 2025-0903 (nearby location, 30 days)      │  │
│  │  🔗 2025-0651 (suspect match: "Ravi Kumar")   │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  [📥 Download Full FIR PDF]                         │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Design notes:**
- Demographics (age, gender, caste, religion) are shown based on RBAC: masked as `**` for Constables, shown for Inspector+.
- "Related Cases" section comes from the derived graph layer — shows linked cases with the link reason.
- Smooth slide animation, 300ms ease-out. Can be dismissed with ✕, Escape key, or swiping right (on tablet).

---

### 4.5 Hotspot Map View (V3)

```
┌────────────────────────────────────────────────────────────────┐
│  HOTSPOT MAP                                         [Fullscreen]│
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                                                          │  │
│  │                                                          │  │
│  │           [KARNATAKA STATE MAP]                          │  │
│  │                                                          │  │
│  │     🔴🔴🔴  ← DBSCAN clusters (red = high density)     │  │
│  │        🟡🟡  ← moderate clusters                         │  │
│  │          🟢  ← low density                               │  │
│  │                                                          │  │
│  │     [Station boundaries as faint gray polygons]          │  │
│  │                                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  FILTERS                                                 │  │
│  │  [Crime Type ▾]  [Time Range ▾]  [District ▾]           │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  CLUSTER LEGEND                                          │  │
│  │  🔴 High (10+ cases/cluster)  🟡 Medium (5-9)  🟢 Low   │  │
│  │  ○ Individual case markers                              │  │
│  │                                                          │  │
│  │  Selected cluster: Whitefield ITPL area                  │  │
│  │  14 theft cases in 90 days, trending ↑ 23% vs baseline   │  │
│  │  [View Cases →]  [View Network →]                        │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Design notes:**
- Map library: use whatever Catalyst hosting supports (Leaflet.js / OpenStreetMap tiles — free, no API key).
- Cluster markers scale with case count (larger dot = more cases).
- Clicking a cluster: zoom in, expand to individual case markers, show summary panel at bottom.
- Heat overlay option: toggle between cluster dots and gradient heat map.
- Auto-zooms to the user's assigned jurisdiction by default (RBAC-scoped).
- Animation: clusters pulse gently (1.5s cycle) to draw attention.

---

### 4.6 Trend Dashboard (V4)

```
┌────────────────────────────────────────────────────────────────┐
│  CRIME TRENDS                                      [Download]  │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  TIME-SERIES CHART                                       │  │
│  │                                                          │  │
│  │  Cases ▲                                                 │  │
│  │  50│        ╱╲      ╱╲                                  │  │
│  │  40│   ╱╲  ╱  ╲    ╱  ╲    ← actual                     │  │
│  │  30│  ╱  ╲╱    ╲──╱    ╲──                              │  │
│  │  20│ ╱              ─ ─ ─ ─ ← baseline (avg)            │  │
│  │  10│╱                                                     │  │
│  │   └──────────────────────────────▶ Time                  │  │
│  │    Jan  Feb  Mar  Apr  May  Jun                          │  │
│  │                                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  BREAKDOWN TABLE                                         │  │
│  │  Crime Type   │ Jan │ Feb │ Mar │ Apr │ Trend │          │  │
│  │  Theft        │  12 │  15 │  18 │  22 │  ↑    │          │  │
│  │  Robbery      │   3 │   2 │   4 │   3 │  ─    │          │  │
│  │  Murder       │   1 │   0 │   1 │   1 │  ─    │          │  │
│  │  Burglary     │   5 │   8 │   6 │   9 │  ↑    │          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  EARLY WARNING CARDS (if applicable)                     │  │
│  │                                                          │  │
│  │  ⚠️  Whitefield PS: Theft trending 23% above baseline    │  │
│  │      [View Details]  [View Hotspot]                      │  │
│  │                                                          │  │
│  │  ⚠️  Mahadevapura PS: Burglary uptick detected          │  │
│  │      [View Details]  [View Hotspot]                      │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Design notes:**
- Charts use a clean, minimal style — no grid lines, soft axis labels.
- Color palette: `#147878` (teal) for data lines, `#D9D3C4` (warm gray) for baselines, `#A63B25` (alert red) for threshold breaches.
- Charts must be responsive — stack vertically on mobile.
- Time range selector: default to last 12 months, with quick toggles: 3M / 6M / 1Y / Custom.

---

### 4.7 Network Graph View (V5) — SP / Crime Branch only

```
┌────────────────────────────────────────────────────────────────┐
│  CRIMINAL NETWORK ANALYSIS                                     │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                                                          │  │
│  │            ◉ Ravi Kumar (3 cases)                        │  │
│  │           /│\                                            │  │
│  │     FIR──┘ │ └──FIR                                      │  │
│  │    2025-0891  2025-0782                                  │  │
│  │      │         │                                         │  │
│  │     FIR       FIR                                        │  │
│  │   2025-0651  2025-0543                                  │  │
│  │     │         │                                         │  │
│  │    ◉ Mohan   ◉ Suresh                                   │  │
│  │   (1 case)   (2 cases)                                  │  │
│  │                                                          │  │
│  │  [Graph canvas: interactive, zoom, pan, drag]            │  │
│  │                                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  CONTROLS                                                │  │
│  │  [Person ○] [Case □] [Officer △] ← node type toggles    │  │
│  │  Depth: [1-hop] [2-hop] [3-hop]                          │  │
│  │  Layout: [Force] [Hierarchical] [Circular]               │  │
│  │  Highlight: [Repeat offenders] [Same IO] [Same Section]  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  SELECTED NODE INFO                                      │  │
│  │                                                          │  │
│  │  ◉ Ravi Kumar (possible name variant: "Ravi K")         │  │
│  │  Match confidence: 87%                                   │  │
│  │  Linked cases: 3                                         │  │
│  │  Common section: IPC 379 (Theft)                         │  │
│  │  Active since: 2025-01                                   │  │
│  │                                                          │  │
│  │  [View Full Profile]  [View Cases]                       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Design notes:**
- Use **D3.js** or **vis.js** for the force-directed graph (both work in browser, no server dependency).
- Node shapes encode type: `◉` circle = person, `□` square = case (FIR), `△` triangle = officer.
- Node size scales with centrality (more connections = larger).
- Edge labels show relationship: "same_person_in", "investigated_by", "charged_under".
- Entity-resolution matches show a dashed edge with confidence % label.
- **Critical**: graph must be zoomable/pannable — networks can get large.
- Color coding: persons = `#147878` (teal), cases = `#42566C` (slate), officers = `#B8902A` (brass).
- Clicking any node opens its detail panel (case detail or person profile).

---

### 4.8 Prevention Briefing View (V6) — SP only

```
┌────────────────────────────────────────────────────────────────┐
│  PREVENTION BRIEFING              [Generated: 2025-07-01]     │
│  📥 Export as PDF                                              │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  ⚠️  EARLY WARNING: Whitefield Division                  │  │
│  │                                                          │  │
│  │  Theft cases in Whitefield PS are trending 23% above     │  │
│  │  the 12-month baseline. DBSCAN has identified a dense    │  │
│  │  cluster around the ITPL corridor.                       │  │
│  │                                                          │  │
│  │  [View Hotspot Map →]                                    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  🔗 NETWORK FINDINGS                                     │  │
│  │                                                          │  │
│  │  3 repeat offenders are active near the cluster:         │  │
│  │                                                          │  │
│  │  ◉ Ravi Kumar — 3 theft cases (IPC 379) since Jan 2025  │  │
│  │    MO: targets two-wheelers near IT gates, afternoon     │  │
│  │    [View Profile →]                                      │  │
│  │                                                          │  │
│  │  ◉ Suresh — 2 theft cases + 1 burglary                  │  │
│  │    MO: residential break-ins, evening hours              │  │
│  │    [View Profile →]                                      │  │
│  │                                                          │  │
│  │  ◉ Unknown ("Ravi K" variant, 87% match) — 1 case       │  │
│  │    [View Network Graph →]                                │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  📊 PATTERN SUMMARY                                      │  │
│  │                                                          │  │
│  │  • Peak time: 14:00–17:00 (62% of cases)                │  │
│  │  • Peak day: Friday (28% of cases)                       │  │
│  │  • Primary target: Two-wheelers (71%)                    │  │
│  │  • Common entry point: Forced ignition lock              │  │
│  │                                                          │  │
│  │  Recommendation: Increase patrol presence near ITPL      │  │
│  │  corridor between 14:00–17:00 on weekdays.               │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  📎 Citation Case Numbers                                │  │
│  │  [2025-0891] [2025-0782] [2025-0651] [2025-0543]        │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Design notes:**
- Briefing cards are **narrative-first** — composed by the AI, not raw data dumps.
- Each finding is backed by CrimeNo citations (clickable).
- The entire briefing is exportable as PDF (via SmartBrowz).
- **Guardrail**: this view must never show individual risk scores or demographic-based profiling. The AI composes a descriptive summary, not a threat assessment.

---

### 4.9 Audit Log View (V7)

```
┌────────────────────────────────────────────────────────────────┐
│  AUDIT LOG                                                     │
│                                                                │
│  [Search: ________________]  [Date Range ▾]  [User ▾]         │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Timestamp        │ User              │ Query Summary    │  │
│  │  2025-07-01 14:32 │ Insp. R. Meena   │ Theft cases in   │  │
│  │                   │                   │ Bengaluru East   │  │
│  │                   │                   │ → 47 results 📎  │  │
│  │  ─────────────────┼───────────────────┼────────────────  │  │
│  │  2025-07-01 14:35 │ Insp. R. Meena   │ Filtered: 2-wheeler│  │
│  │                   │                   │ theft → 12 📎    │  │
│  │  ─────────────────┼───────────────────┼────────────────  │  │
│  │  2025-07-01 15:01 │ SP Anand K.      │ Network: FIR     │  │
│  │                   │                   │ 2025-0891 links  │  │
│  │                   │                   │ → graph view 🔗   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  [Export Log as CSV]                                           │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Design notes:**
- Read-only for all roles. Constables can only see their own entries.
- Every AI interaction is automatically logged (this happens server-side, but the UI shows it).
- Simple table layout, no fancy components — this is a compliance/oversight screen.

---

## 5. Design system

### 5.1 Color Palette

| Token | Hex | Usage |
|-------|-----|-------|
| `--ink` | `#0F1B2D` | Primary text, headers |
| `--ink-soft` | `#1B2C42` | Secondary text |
| `--slate` | `#42566C` | Muted text, constable badge |
| `--paper` | `#FBFAF6` | Background (warm off-white) |
| `--paper-2` | `#F2EFE6` | Card backgrounds |
| `--line` | `#D9D3C4` | Borders, dividers |
| `--brass` | `#B8902A` | Accent, active states, SP badge |
| `--brass-deep` | `#8A6A18` | Hover state for brass |
| `--teal` | `#147878` | Links, interactive elements, Inspector badge |
| `--alert` | `#A63B25` | Errors, warnings, threshold breaches |
| `--success` | `#2D6A4F` | Positive indicators, confirmed status |
| `--white` | `#FFFFFF` | Card surfaces on dark backgrounds |

**Palette rationale**: The palette is derived from the project's technical report — a "dossier" aesthetic (warm paper, navy ink, brass accents) that feels like a professional intelligence document, not a toy app.

### 5.2 Typography

| Use | Font | Weight | Size |
|-----|------|--------|------|
| Display / hero | Archivo | 700-800 | 28–48px |
| Section headings | Archivo | 600 | 20–24px |
| Body text | Source Serif 4 | 400-500 | 15–18px |
| Code / CrimeNo / IDs | IBM Plex Mono | 500 | 13–14px |
| UI labels | System sans-serif | 500 | 12–14px |

**Fallback chain**: If web fonts fail to load, fall back to system UI fonts. The app must remain usable with fallback fonts (critical for low-bandwidth rural stations).

### 5.3 Spacing & Layout

- **Base unit**: 8px
- **Card padding**: 24px
- **Section gap**: 16px
- **Max content width**: 980px (chat), 1200px (dashboard views)
- **Minimum touch target**: 44×44px (for tablet/phone use)

### 5.4 Component Library

Build these as reusable components:

| Component | States | Notes |
|-----------|--------|-------|
| `ChatBubble` | User / Assistant / System | Rounded corners, subtle shadow |
| `AnswerCard` | Loading / Content / Error | Structured card with summary + body + citations |
| `CitationBadge` | Default / Hover / Active | Pill shape, monospace CrimeNo, click to open detail |
| `RoleBadge` | Constable / Inspector / SP | Color-coded by rank |
| `FilterPill` | Active / Inactive | For map/dashboard filters |
| `DataTable` | Default / Sorted / Empty | Sortable columns, striped rows |
| `MiniChart` | Sparkline / Bar / Donut | Inline in chat cards |
| `MapCluster` | Low / Medium / High density | Scaled circle markers |
| `GraphNode` | Person / Case / Officer | Shape-coded, selectable |
| `BriefingCard` | Warning / Info / Pattern | Narrative card with citation footer |
| `InputBar` | Idle / Recording / Sending | Persistent bottom bar |
| `VoicePulse` | Idle / Listening / Processing | Animated ring around mic icon |
| `SlideOver` | Open / Closed | Right-panel for case detail |
| `Toast` | Info / Success / Error / RBAC-denied | Auto-dismiss, max 3 stacked |

---

## 6. Interaction & motion guidelines

### 6.1 Transitions

| Action | Animation | Duration |
|--------|-----------|----------|
| Open slide-over panel | Slide from right | 300ms ease-out |
| Close slide-over | Slide to right | 250ms ease-in |
| New chat message | Fade in + slide up | 200ms ease-out |
| Answer card loading | Skeleton pulse | 1.5s infinite |
| Map cluster hover | Scale up 1.2× + glow | 150ms ease |
| Voice recording start | Ring pulse animation | 1s infinite |
| Sidebar collapse | Width transition | 250ms ease |
| Toast notification | Slide in from top-right | 300ms, auto-dismiss 5s |
| Graph node selection | Highlight ring + info panel | 200ms ease-out |

### 6.2 Micro-interactions

- **Citation hover**: tooltip shows brief case summary (CrimeNo, type, date, station) before clicking.
- **Suggested query chips**: hover shows the expected answer type icon (📊 table, 🗺️ map, 📈 chart, 🔗 graph).
- **Copy answer**: every answer card has a subtle copy button (📋) that copies the text to clipboard.
- **Typing indicator**: three dots cycling with the phase name ("Querying database..." → "Composing answer..." → "Verifying citations...").

### 6.3 Keyboard shortcuts

| Shortcut | Action |
|----------|--------|
| `Cmd/Ctrl + K` | Quick query (opens input bar focused) |
| `Cmd/Ctrl + /` | Toggle sidebar |
| `Escape` | Close slide-over panel |
| `Cmd/Ctrl + E` | Export current view as PDF |
| `Cmd/Ctrl + L` | Toggle language |

---

## 7. Responsive behavior

### Breakpoint strategy

| Breakpoint | Width | Layout |
|------------|-------|--------|
| Desktop | ≥1200px | Sidebar + main area side by side |
| Tablet | 768–1199px | Sidebar collapsed (icon-only), main area full width |
| Mobile | <768px | No sidebar (bottom tab bar), stacked layout |

**Primary target**: Desktop (1200px+) — this is a workstation tool. Tablet support is secondary. Mobile is best-effort (the voice input makes it usable on phones even if the UI is cramped).

### Critical mobile adaptations

- Chat view stacks vertically (no side panels).
- Maps go fullscreen on tap.
- Graph view shows a simplified list view on mobile (nodes as a scrollable list with relationship arrows), with an "Open full graph" button for desktop.

---

## 8. Accessibility requirements

- **WCAG 2.1 AA** compliance minimum.
- **Color contrast**: all text must meet 4.5:1 ratio against its background.
- **Keyboard navigation**: every interactive element must be reachable via Tab. Focus rings must be visible.
- **Screen reader labels**: all icons must have `aria-label`. Map markers need descriptive labels (not just "marker 1").
- **Language attribute**: `lang="kn"` on Kannada text, `lang="en"` on English text — critical for screen readers to switch pronunciation.
- **Reduced motion**: respect `prefers-reduced-motion` — disable pulse animations, use instant transitions.
- **Font scaling**: all text in `rem` units, must reflow at 200% zoom without horizontal scroll.

---

## 9. Guardrails — what the UI must enforce

These are non-negotiable legal/ethical constraints:

1. **No individual risk scores** — the system never labels a person as "high risk" or assigns threat levels. All profiling is descriptive narrative. If the AI generates a score-like label, the UI must not render it.

2. **Demographic masking** — age, gender, caste, and religion fields are masked as `**` for Constable-rank users. The masking happens server-side, but the UI should handle the masked display gracefully (no broken layout when fields are `**`).

3. **Caste/religion never in charts** — demographic visualizations show only aggregate distributions (bar charts of crime type by district). No scatter plots, no individual-level demographic plots.

4. **Every answer has citations** — if the UI receives an answer without CrimeNo references, it must show a warning: *"This answer could not be verified against specific cases."*

5. **Audit trail visible** — every query and response is logged and the user can see their own audit trail. This is not hidden.

---

## 10. Voice input design

Voice is a first-class input, not an afterthought. Many officers will use this on a phone or tablet in a station.

### 10.1 Voice flow

```
User taps mic →
  Animation: ring pulses, "Listening..." text →
  User speaks →
  Waveform visualizes input →
  Silence detected (3s) →
  Text appears in input field (editable before send) →
  User confirms (auto-send or tap send) →
  Processing animation →
  Answer card appears
```

### 10.2 Voice-specific UI states

- **Not supported**: if browser lacks Web Speech API, hide mic button and show tooltip: *"Voice input not available in this browser. Use text input."*
- **Permission denied**: *"Microphone access denied. Please enable it in browser settings."*
- **No speech detected**: *"I didn't hear anything. Tap the mic and try again."*
- **Unrecognized language**: *"I detected [language]. Please speak in Kannada or English."*

### 10.3 Waveform visualization

Simple CSS animation — 5–7 vertical bars oscillating at different frequencies. No complex canvas drawing. The animation should feel alive but not distracting.

---

## 11. PDF export design

The PDF should look like an **official police document**, not a webpage print.

### 11.1 PDF layout

```
┌──────────────────────────────────┐
│  [KSP Emblem]                    │
│  KARNATAKA STATE POLICE          │
│  Crime Copilot — Export          │
│  ────────────────────────────────│
│  Date: 2025-07-01                │
│  Officer: Inspector R. Meena     │
│  Rank: Inspector                 │
│  Station: Whitefield PS          │
│  ────────────────────────────────│
│                                  │
│  CONVERSATION TRANSCRIPT         │
│                                  │
│  Q: Theft cases in Bengaluru...  │
│  A: 47 cases found...            │
│     [table of results]           │
│     Citations: 2025-0891, ...    │
│                                  │
│  Q: Only two-wheeler ones        │
│  A: 12 cases...                  │
│     [table of results]           │
│                                  │
│  ────────────────────────────────│
│  This document was generated by  │
│  KSP Crime Copilot. All data is  │
│  from the CCTNS database.        │
│  Audit ID: AUD-2025-07-01-0041   │
└──────────────────────────────────┘
```

### 11.2 PDF styling

- A4 paper size.
- Header with KSP emblem + "Confidential — For Official Use Only" watermark.
- Monospace font for CrimeNo references.
- Page numbers in footer.
- Generated via SmartBrowz (server-side rendering).

---

## 12. Empty states and edge cases

Every screen needs thoughtful empty states. Police officers should never see a blank screen with no guidance.

| Scenario | What to show |
|----------|-------------|
| First login, no queries yet | Welcome message + 3 suggested queries based on jurisdiction |
| Empty search results | "No cases match your filters. Try broadening the date range or removing a filter." |
| Graph view, no linked cases | "No linked cases found for this selection. This could mean the entity resolution found no matches." |
| Map view, no clusters | State map with all stations marked, message: "No crime clusters detected in the current time range." |
| Audit log, no entries | "No queries logged yet. Your activity will appear here as you use the system." |
| Briefing view, no alerts | "No early warnings at this time. The system monitors for trend anomalies continuously." |
| Network graph too large | "This network has [N] nodes. Showing the 2-hop neighborhood of the selected node. [Zoom out to see all →]" |
| System error | Friendly error + retry button + support contact: "Something went wrong. Please try again or contact SCRB support." |

---

## 13. Kannada localization notes

- The **entire UI chrome** (labels, buttons, menu items, error messages) must be translatable to Kannada.
- Use a simple Kannada terminology glossary:

| English | Kannada |
|---------|---------|
| Chat | ಸಂಭಾಷಣೆ |
| Search | ಹುಡುಕು |
| Map | ನಕ್ಷೆ |
| Trends | ಪ್ರವೃತ್ತಿಗಳು |
| Network | ಜಾಲ |
| Cases | ಪ್ರಕರಣಗಳು |
| Citations | ಉಲ್ಲೇಖಗಳು |
| Export | ರಫ್ತು |
| Audit Log | ಆಡಳಿತ ದಾಖಲೆ |
| Briefing | ಮಾಹಿತಿ ಕಡತ |
| Filter | ಫಿಲ್ಟರ್ |
| Results | ಫಲಿತಾಂಶಗಳು |
| Crime Type | ಅಪರಾಧದ ಪ್ರಕಾರ |
| Station | ಪೊಲೀಸ್ ಠಾಣೆ |
| District | ಜಿಲ್ಲೆ |

- **CrimeNos, names, and IDs are never transliterated or translated.** They pass through exactly as stored.
- Right-to-left is not a concern (Kannada is left-to-right), but **Kannada text renders wider** than English — UI containers must accommodate this (15–20% wider minimum).
- When language is toggled, the transition should be instant (no page reload).

---

## 14. Deliverables expected from this design phase

| # | Deliverable | Format |
|---|-------------|--------|
| 1 | **Style guide** — color, typography, spacing, component specs | Figma / PDF |
| 2 | **High-fidelity mockups** — all 8 views (V1–V8) for desktop breakpoint | Figma |
| 3 | **Responsive variants** — chat view for tablet and mobile | Figma |
| 4 | **Interaction specs** — transitions, animations, micro-interactions | Figma prototype or annotated screens |
| 5 | **Component library** — reusable components with all states | Figma components |
| 6 | **Voice input flow** — mic states, waveform, error states | Figma |
| 7 | **PDF export template** — layout for the official document | Figma / HTML |
| 8 | **Kannada UI labels** — all translatable strings in Kannada | Spreadsheet or Figma overlay |

---

## 15. Reference material

- **[PLAN.md](PLAN.md)** — full architecture, data flow diagrams, demo runbook, and cut lines
- **[Technical Report](KSP-Datathon2026-Conversational-AI-Technical-Report.html)** — original strategy document with persona analysis, evaluation metrics, and the "dossier" visual language that the color palette is derived from
- **[ER Diagram](Police_FIR_ER_Diagram.md)** — 26-table database schema. The designer should understand the data model to know what fields are available for display (e.g., CrimeNo, CrimeHead, StationName, DistrictName, IncidentFromDate)

---

*This brief is the source of truth for UI/UX design decisions. For questions about data flow, backend architecture, or feature prioritization, refer to PLAN.md.*
