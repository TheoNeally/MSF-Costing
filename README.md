# MSF Radome Costing Tool

A local, single-user ROM estimator for metal space frame radomes. It combines
approximate truncated-sphere geometry, prototype frame and membrane rates,
labor and installation inputs, staged cost bases, and gross-margin pricing in a
functional browser interface.

The application uses only Python's standard library. Estimate data remains on
the local computer in SQLite.

## Start the application

On Windows, double-click `launch.bat`, or run:

```powershell
python app.py
```

The tool opens at <http://127.0.0.1:8765>. Press `Ctrl+C` in the terminal to
stop it.

To run without opening a browser automatically:

```powershell
python app.py --no-browser
```

## Current capabilities

- Diameter and base-angle geometry inputs
- Quasi-random and regular geometry classification
- Total, base, and unique panel counts
- Derived height, base diameter, shell area, truncation, and average panel size
- Optional exact membrane-area override
- Mutually exclusive panel-set and component frame-cost methods
- Seed rates for the $1,150 BK-1 frame set, $260 beam set, and $4–$12/ft² fabric
- Engineering, shop labor, field crew, travel, equipment, and per-diem inputs
- Accessories assigned to manufacturing, delivered, installed, or loaded stages
- Manufacturing, delivered, installed, and fully loaded cost bases
- Price-from-margin and margin-from-price calculations
- Low/base/high raw-fabric scenarios
- Versioned rate library with per-rate source, effective date, and confidence
- Rate change log and library-version stamp on every saved estimate
- Immutable saved estimate revisions
- Print-friendly internal estimate view

## Geometry assumptions

Base angle is the polar angle from the zenith axis to the truncation plane. For
sphere diameter `D` and base angle `phi`:

```text
truncation fraction = sin²(phi / 2)
height              = D × sin²(phi / 2)
base diameter       = D × sin(phi)
spherical-cap area  = pi × D × height
```

When exact panel areas are unavailable, membrane area begins with the
spherical-cap area and applies editable faceting and waste factors. Approximate
average panel edge length assumes equal-area equilateral triangles and is a
quantity check, not production geometry.

## Cost behavior

The frame cost methods are deliberately exclusive:

- **Panel-set method:** total panels × BK-1 reference cost × scaling factors.
- **Component method:** beam sets, fittings, hardware, and fabrication.

Raw membrane cost uses the selected scenario's fabric rate and purchased area.
Membrane fabrication is a separate per-panel input.

Loaded overhead, warranty, and contingency percentages share the same base:
installed cost plus project management and fully-loaded-stage accessories. This
keeps the build-up transparent and avoids compounding hidden percentages.

## Rate library

Every price, rate, factor, and percentage the tool starts from lives in
`rates.json` at the project root, not in the calculation code. Each of the 36
managed rates carries its own provenance:

| Field | Meaning |
| --- | --- |
| `value` | The number used to seed new estimates |
| `effective_date` | When this value took effect |
| `source` | Quote number, vendor, job number, or data set |
| `confidence` | `actual`, `quoted`, `benchmark`, `estimate`, or `placeholder` |
| `review_by` | Optional date after which the rate is flagged as overdue |
| `note` | Scope, exclusions, or validity window |

Open the library with the **Rates** button. Editing a value there writes
`rates.json`, increments the library version, and appends one record per
changed rate to `rates_history.jsonl`, so "when did $8/ft² become $9.40, and
why" stays answerable. A source is required whenever confidence is anything
other than `placeholder`; a rejected batch leaves every rate untouched.

Three layers stay deliberately separate:

1. **The library** seeds new estimates.
2. **An open estimate** can override any seeded value without touching the
   library. Saving new rates never rewrites the estimate on screen — use
   **Apply library to open estimate** to pull them in explicitly.
3. **Saved revisions** are immutable. Each stores the library stamp that
   produced it, so reopening revision 3 shows the rates it was priced with, and
   the printed estimate carries that stamp.

Rates seeded before any real data arrived are marked `placeholder`, and the
count of unvalidated rates appears on the estimate itself. As quotes and job
cost data arrive, the work is converting placeholders into `quoted` and
`actual` values with real sources.

Both `rates.json` and `rates_history.jsonl` are tracked by Git, so
`git log -p rates.json` is a second, independent record of every rate change.

## Data and backups

Saved revisions are stored in `data/msf_costing.db`. Back up that file while the
application is stopped. The database and its temporary SQLite files are ignored
by Git. The rate library (`rates.json`) and its change log
(`rates_history.jsonl`) are tracked by Git and should be committed after a rate
update.

To run against a different library or database, use `--rates` and `--database`:

```powershell
python app.py --rates rates.json --database data/msf_costing.db
```

## Automated tests

```powershell
python -m unittest discover -v
```

The test suite covers geometry, mutually exclusive frame costing, cost stages,
installation crew-days, pricing, validation, SQLite revision history, the rate
library (seeding, validation, change history, staleness, and recovery from a
malformed file), and the HTTP API.

## Geometry-tool integration point

The calculation engine is isolated in `msf_costing/calculations.py`. A detailed
geometry adapter can later supply exact panel families, beam lengths, fittings,
hardware, and membrane quantities while retaining the same cost stages,
pricing logic, persistence, and GUI workflow.

## Prototype limitations

Results are intentionally labeled ROM. Every seeded rate ships at
`placeholder` confidence, and the estimate reports how many remain unvalidated.
The initial BK-1 reference cost is applied uniformly unless the user changes the
size, beam, and complexity factors. Engineering, shop labor, field installation, and accessory inputs
default to zero and therefore appear as explicit warnings rather than hidden
assumptions. The fabric range changes raw membrane cost only; it is not a
statistical confidence interval.
