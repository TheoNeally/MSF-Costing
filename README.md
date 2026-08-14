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

## Data and backups

Saved revisions are stored in `data/msf_costing.db`. Back up that file while the
application is stopped. The database and its temporary SQLite files are ignored
by Git.

## Automated tests

```powershell
python -m unittest discover -v
```

The test suite covers geometry, mutually exclusive frame costing, cost stages,
installation crew-days, pricing, validation, SQLite revision history, and the
HTTP API.

## Geometry-tool integration point

The calculation engine is isolated in `msf_costing/calculations.py`. A detailed
geometry adapter can later supply exact panel families, beam lengths, fittings,
hardware, and membrane quantities while retaining the same cost stages,
pricing logic, persistence, and GUI workflow.

## Prototype limitations

Results are intentionally labeled ROM. The initial BK-1 reference cost is
applied uniformly unless the user changes the size, beam, and complexity
factors. Engineering, shop labor, field installation, and accessory inputs
default to zero and therefore appear as explicit warnings rather than hidden
assumptions. The fabric range changes raw membrane cost only; it is not a
statistical confidence interval.
