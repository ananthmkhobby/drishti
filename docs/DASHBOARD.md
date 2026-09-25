# ACI – Dashboard Specification

---

## Dashboard Roles

| Role | Dashboard | Access Scope |
|---|---|---|
| Teacher | Teacher Dashboard | Own sessions only |
| School Admin | Admin Dashboard | All classrooms in their school |
| CSR / NGO / Govt | CSR Dashboard | All schools in their program |

---

## Teacher Dashboard

**URL:** `/dashboard/teacher`
**Auth:** Teacher JWT

### Widgets

| Widget | Data Source | Description |
|---|---|---|
| Sessions Conducted | `sessions` count | Total sessions this week / month |
| Topics Covered | `ai_outputs.notes` headings | Curriculum coverage summary |
| AI Outputs Generated | `ai_outputs` count | Notes, quizzes, summaries produced |
| TiQer Sessions | `quiz_questions.tiqer_exported` | Count of quiz exports to TiQer |
| Missing Concepts | `ai_outputs.missing_concepts` | Concepts flagged as incomplete |
| Sync Status | `sessions.sync_status` | Pending uploads count + last sync time |

### Session List
- Date, subject, grade, status, sync status
- Expand to view: notes, quiz, bloom report, experiment suggestions
- Edit quiz questions before export
- One-click TiQer export per session

### Continue My Class Panel
- Shown at top when teacher opens app before starting a session
- Displays:
  - Last session recap (3 bullets)
  - Pending concepts from memory engine
  - Suggested next topic
  - One quick revision question

### Filters
- Date range picker
- Subject filter
- Grade filter
- Sync status filter (All / Pending / Synced)

---

## Admin Dashboard

**URL:** `/dashboard/admin`
**Auth:** Admin JWT (school-scoped)

### Widgets

| Widget | Data Source | Description |
|---|---|---|
| Classroom Activity | `sessions` by classroom | Heatmap of active classrooms |
| Topic Coverage | Aggregate AI notes headings | Subject-wise curriculum progress |
| Teacher Activity | `sessions` by teacher | Sessions per teacher this month |
| AI Usage | `ai_outputs` count | Volume of AI outputs generated |
| Infrastructure Status | `sessions.sync_status` | Devices with pending sync, last seen |
| TiQer Engagement | Exported quizzes count | Engagement activity school-wide |

### Teacher List
- Per-teacher: session count, last active, subjects, sync health
- Drill-down to individual teacher sessions (read-only)

### Classroom Coverage Map
- Grid of classrooms with colour-coded session frequency:
  - 🟢 Active (≥3 sessions/week)
  - 🟡 Moderate (1–2 sessions/week)
  - 🔴 Inactive (0 sessions/week)

---

## CSR / Government Dashboard

**URL:** `/dashboard/csr`
**Auth:** CSR JWT (program-scoped)

### Widgets

| Widget | Data Source | Description |
|---|---|---|
| School Activity | `sessions` by school | Sessions per school this period |
| Sessions Conducted | Aggregate session count | Total program-wide sessions |
| Teacher Adoption | Active teachers / enrolled teachers | Adoption rate % |
| Concept Coverage | Aggregate topic list | Topics taught across program |
| Connectivity Insights | Sync failure rates | Infrastructure quality signal |
| AI Outputs Generated | `ai_outputs` count | Evidence of learning material production |

### School List
- Per-school: sessions, active teachers, last activity, connectivity health
- Export to CSV / PDF for program reports

### Summary Report Generator
- Select date range
- Generate PDF report: sessions, adoption, topics, connectivity
- Used for donor/government reporting

---

## Sync Status Indicators (All Dashboards)

| Status | Display |
|---|---|
| All synced | Green dot — "Up to date" |
| Pending sync | Grey dot — "X sessions pending upload" |
| Sync in progress | Blue spinner — "Syncing..." |
| Sync failed | Orange warning — "X sessions failed — tap to retry" |

---

## API Endpoints

```
GET /dashboard/teacher/{teacher_id}          → Teacher summary
GET /dashboard/teacher/{teacher_id}/sessions → Paginated session list
GET /dashboard/admin/{school_id}             → Admin summary
GET /dashboard/admin/{school_id}/teachers    → Teacher list with stats
GET /dashboard/csr/{program_id}              → CSR summary
GET /dashboard/csr/{program_id}/schools      → School list with stats
GET /dashboard/csr/{program_id}/report       → Generates summary report
```

---

## Frontend Notes

- **Framework:** React + Next.js (App Router)
- **Charts:** Recharts or Chart.js (lightweight)
- **Data refresh:** SWR with 60s polling interval (no WebSockets in MVP)
- **Mobile view:** Teacher dashboard must be fully usable on Android browser (responsive)
- **Offline state:** If API unreachable, show last cached data with "Data may be outdated" banner
- **Export:** Quiz → JSON for TiQer; Report → PDF via server-side generation
