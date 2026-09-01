"""Versioned rate library with provenance for the MSF costing tool.

The calculation engine stays free of rate policy.  This module owns the
question "what number do we start from, where did it come from, and how much do
we trust it", then hands the calculation engine an ordinary estimate payload.

Import direction is one-way: ``rates`` depends on ``calculations``, never the
reverse, so the engine remains independently testable.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .calculations import PROTOTYPE_DEFAULTS


SCHEMA_VERSION = 1

#: Ordered from strongest evidence to weakest.
CONFIDENCE_LEVELS: tuple[str, ...] = (
    "actual",
    "quoted",
    "benchmark",
    "estimate",
    "placeholder",
)

CONFIDENCE_LABELS: dict[str, str] = {
    "actual": "Actual — from completed job cost data",
    "quoted": "Quoted — vendor or subcontractor quote in hand",
    "benchmark": "Benchmark — comparable project or published data",
    "estimate": "Estimate — engineering judgment",
    "placeholder": "Placeholder — seed value, not validated",
}

#: Confidence levels that should not sit quietly inside a customer price.
UNVALIDATED_CONFIDENCE = frozenset({"estimate", "placeholder"})

#: Every rate seeded before any real quote arrived shares this effective date.
SEED_EFFECTIVE_DATE = "2026-01-01"

_SEED_ZERO_SOURCE = (
    "Not yet quantified; zero keeps the exclusion visible in estimate warnings"
)

MAX_SOURCE_LENGTH = 500
MAX_NOTE_LENGTH = 2000


class RateValidationError(ValueError):
    """Raised when a proposed rate change is rejected."""

    def __init__(self, details: list[str]) -> None:
        super().__init__("; ".join(details))
        self.details = details


@dataclass(frozen=True)
class RateField:
    """Catalog entry describing one library-managed value."""

    path: str
    label: str
    unit: str
    category: str
    kind: str
    step: float = 1.0
    minimum: float = 0.0
    maximum: float | None = None
    seed_source: str = _SEED_ZERO_SOURCE
    help: str = ""


RATE_FIELDS: tuple[RateField, ...] = (
    # --- Frame system -----------------------------------------------------
    RateField(
        "frame.panel_set_cost",
        "Reference panel-frame set",
        "$ / panel set",
        "Frame system",
        "currency",
        step=10,
        seed_source="BK-1 prototype frame set, internal build reference",
        help="Complete panel frame excluding membrane. Used by the panel-set method.",
    ),
    RateField(
        "frame.beam_set_cost",
        "Beam set",
        "$ / beam set",
        "Frame system",
        "currency",
        step=10,
        seed_source="Prototype beam set reference",
        help="Used by the component build-up method only.",
    ),
    RateField(
        "frame.beam_sets_per_panel",
        "Beam sets per panel",
        "sets / panel",
        "Frame system",
        "count",
        step=0.1,
        seed_source="Three beams per triangular panel, nominal",
    ),
    RateField(
        "frame.fittings_per_panel",
        "Fittings",
        "$ / panel",
        "Frame system",
        "currency",
        step=10,
    ),
    RateField(
        "frame.hardware_per_panel",
        "Hardware",
        "$ / panel",
        "Frame system",
        "currency",
        step=10,
    ),
    RateField(
        "frame.fabrication_per_panel",
        "Frame fabrication",
        "$ / panel",
        "Frame system",
        "currency",
        step=10,
    ),
    RateField(
        "frame.setup_cost_per_unique",
        "Setup and tooling",
        "$ / unique shape",
        "Frame system",
        "currency",
        step=10,
    ),
    RateField(
        "frame.size_factor",
        "Size factor",
        "multiplier",
        "Frame system",
        "factor",
        step=0.05,
        minimum=0.01,
        seed_source="Neutral until size-driven cost data exists",
    ),
    RateField(
        "frame.beam_factor",
        "Beam-size factor",
        "multiplier",
        "Frame system",
        "factor",
        step=0.05,
        minimum=0.01,
        seed_source="Neutral until beam-section cost data exists",
    ),
    RateField(
        "frame.complexity_factor",
        "Complexity factor",
        "multiplier",
        "Frame system",
        "factor",
        step=0.05,
        minimum=0.01,
        seed_source="Neutral until quasi-random fabrication data exists",
    ),
    # --- Membrane ---------------------------------------------------------
    RateField(
        "membrane.fabric_rate_low",
        "Fabric rate — low",
        "$ / ft²",
        "Membrane",
        "currency",
        step=0.25,
        seed_source="Prototype fabric range, low end of supplier indications",
    ),
    RateField(
        "membrane.fabric_rate_base",
        "Fabric rate — base",
        "$ / ft²",
        "Membrane",
        "currency",
        step=0.25,
        seed_source="Prototype fabric range, midpoint of supplier indications",
    ),
    RateField(
        "membrane.fabric_rate_high",
        "Fabric rate — high",
        "$ / ft²",
        "Membrane",
        "currency",
        step=0.25,
        seed_source="Prototype fabric range, high end of supplier indications",
    ),
    RateField(
        "membrane.waste_pct",
        "Cutting waste",
        "%",
        "Membrane",
        "percent",
        step=1,
        maximum=200,
        seed_source="Nominal 10% cutting allowance pending real nesting data",
    ),
    RateField(
        "membrane.faceting_factor",
        "Faceting factor",
        "multiplier",
        "Membrane",
        "factor",
        step=0.01,
        minimum=0.01,
        seed_source="Neutral until faceted panel areas are measured",
    ),
    RateField(
        "membrane.fabrication_per_panel",
        "Membrane fabrication",
        "$ / panel",
        "Membrane",
        "currency",
        step=10,
    ),
    # --- Engineering and shop labor --------------------------------------
    RateField(
        "labor.engineering_rate",
        "Engineering rate",
        "$ / hr",
        "Engineering and shop labor",
        "currency",
        step=5,
        seed_source="Planning placeholder pending payroll and burden data",
    ),
    RateField(
        "labor.engineering_base_hours",
        "Base engineering hours",
        "hr",
        "Engineering and shop labor",
        "hours",
        step=1,
    ),
    RateField(
        "labor.engineering_hours_per_unique",
        "Engineering hours per unique shape",
        "hr / unique shape",
        "Engineering and shop labor",
        "hours",
        step=0.5,
    ),
    RateField(
        "labor.shop_rate",
        "Burdened shop rate",
        "$ / hr",
        "Engineering and shop labor",
        "currency",
        step=5,
        seed_source="Planning placeholder pending payroll and burden data",
    ),
    RateField(
        "labor.shop_hours_per_panel",
        "Shop hours per panel",
        "hr / panel",
        "Engineering and shop labor",
        "hours",
        step=0.25,
    ),
    RateField(
        "labor.shop_setup_hours_per_unique",
        "Shop setup hours per unique shape",
        "hr / unique shape",
        "Engineering and shop labor",
        "hours",
        step=0.25,
    ),
    # --- Field installation ----------------------------------------------
    RateField(
        "labor.field_rate",
        "Field rate per person",
        "$ / hr",
        "Field installation",
        "currency",
        step=5,
        seed_source="Planning placeholder pending field payroll data",
    ),
    RateField(
        "labor.crew_size",
        "Crew size",
        "people",
        "Field installation",
        "count",
        step=1,
    ),
    RateField(
        "labor.panels_per_day",
        "Panels per crew-day",
        "panels / day",
        "Field installation",
        "count",
        step=0.5,
        help="Field productivity. Drives installation duration and per diem.",
    ),
    RateField(
        "labor.hours_per_day",
        "Hours per day",
        "hr / day",
        "Field installation",
        "hours",
        step=0.5,
        maximum=24,
        seed_source="Standard eight-hour field day",
    ),
    RateField(
        "labor.equipment_per_day",
        "Field equipment",
        "$ / day",
        "Field installation",
        "currency",
        step=50,
    ),
    RateField(
        "labor.mobilization",
        "Mobilization",
        "$ / job",
        "Field installation",
        "currency",
        step=100,
    ),
    RateField(
        "labor.travel_fixed",
        "Fixed travel",
        "$ / job",
        "Field installation",
        "currency",
        step=100,
    ),
    RateField(
        "labor.per_diem",
        "Per diem",
        "$ / person-day",
        "Field installation",
        "currency",
        step=5,
    ),
    # --- Overhead and allowances -----------------------------------------
    RateField(
        "other.packaging_freight",
        "Packaging and freight",
        "$ / job",
        "Overhead and allowances",
        "currency",
        step=100,
    ),
    RateField(
        "other.project_management",
        "Project management",
        "$ / job",
        "Overhead and allowances",
        "currency",
        step=100,
    ),
    RateField(
        "other.overhead_pct",
        "Overhead",
        "%",
        "Overhead and allowances",
        "percent",
        step=0.5,
        maximum=200,
    ),
    RateField(
        "other.warranty_pct",
        "Warranty allowance",
        "%",
        "Overhead and allowances",
        "percent",
        step=0.5,
        maximum=200,
    ),
    RateField(
        "other.contingency_pct",
        "Contingency",
        "%",
        "Overhead and allowances",
        "percent",
        step=0.5,
        maximum=200,
        seed_source="Prototype ROM contingency pending estimate-accuracy history",
    ),
    # --- Pricing policy ---------------------------------------------------
    RateField(
        "pricing.target_margin_pct",
        "Target gross margin",
        "%",
        "Pricing policy",
        "percent",
        step=0.5,
        maximum=99.99,
        seed_source="Management target pending program-level margin policy",
    ),
)

RATE_FIELDS_BY_PATH: dict[str, RateField] = {field.path: field for field in RATE_FIELDS}

CATEGORIES: tuple[str, ...] = tuple(
    dict.fromkeys(field.category for field in RATE_FIELDS)
)


def _get_path(mapping: dict[str, Any], path: str) -> Any:
    cursor: Any = mapping
    for part in path.split("."):
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(part)
    return cursor


def _set_path(mapping: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cursor = mapping
    for part in parts[:-1]:
        child = cursor.get(part)
        if not isinstance(child, dict):
            child = {}
            cursor[part] = child
        cursor = child
    cursor[parts[-1]] = value


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _clean_text(value: Any, limit: int) -> str:
    text = "" if value is None else str(value)
    return text.strip()[:limit]


def seed_entry(field: RateField) -> dict[str, Any]:
    """Build the untouched starting entry for one catalog field."""

    return {
        "value": float(_get_path(PROTOTYPE_DEFAULTS, field.path) or 0.0),
        "effective_date": SEED_EFFECTIVE_DATE,
        "source": field.seed_source,
        "confidence": "placeholder",
        "review_by": "",
        "note": "",
    }


def seed_library() -> dict[str, Any]:
    """Build a complete library of untouched seed values."""

    return {
        "schema_version": SCHEMA_VERSION,
        "library_version": 1,
        "updated_at": f"{SEED_EFFECTIVE_DATE}T00:00:00+00:00",
        "rates": {field.path: seed_entry(field) for field in RATE_FIELDS},
    }


class RateLibrary:
    """A JSON-backed set of rates, each carrying its own provenance."""

    def __init__(self, path: str | Path, data: dict[str, Any] | None = None) -> None:
        self.path = Path(path)
        self.history_path = self.path.with_name(f"{self.path.stem}_history.jsonl")
        self.load_error: str | None = None
        self._data = data if data is not None else seed_library()

    # -- loading and saving ------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> "RateLibrary":
        """Load a library, seeding the file when it does not exist yet.

        A malformed file is never overwritten automatically: the library falls
        back to seed values in memory and reports the problem so the operator
        can repair the file by hand.
        """

        library = cls(path)
        if not library.path.exists():
            library._data = seed_library()
            library._write()
            return library
        try:
            raw = json.loads(library.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("Rate library must be a JSON object")
            library._data = library._normalize(raw)
        except (OSError, ValueError) as exc:
            library.load_error = f"{library.path.name} could not be read ({exc}). Seed rates are in use."
            library._data = seed_library()
        return library

    def _normalize(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Fill in missing rates from seeds and drop paths outside the catalog."""

        stored = raw.get("rates")
        stored = stored if isinstance(stored, dict) else {}
        rates: dict[str, Any] = {}
        unknown: list[str] = []
        for path in stored:
            if path not in RATE_FIELDS_BY_PATH:
                unknown.append(path)
        for field in RATE_FIELDS:
            entry = stored.get(field.path)
            seed = seed_entry(field)
            if not isinstance(entry, dict):
                rates[field.path] = seed
                continue
            try:
                value = float(entry.get("value", seed["value"]))
            except (TypeError, ValueError):
                value = seed["value"]
            if value != value or value in (float("inf"), float("-inf")):
                value = seed["value"]
            effective = _clean_text(entry.get("effective_date"), 32) or seed["effective_date"]
            try:
                _parse_date(effective)
            except ValueError:
                effective = seed["effective_date"]
            review_by = _clean_text(entry.get("review_by"), 32)
            if review_by:
                try:
                    _parse_date(review_by)
                except ValueError:
                    review_by = ""
            confidence = _clean_text(entry.get("confidence"), 32)
            if confidence not in CONFIDENCE_LEVELS:
                confidence = seed["confidence"]
            rates[field.path] = {
                "value": max(field.minimum, value),
                "effective_date": effective,
                "source": _clean_text(entry.get("source"), MAX_SOURCE_LENGTH) or seed["source"],
                "confidence": confidence,
                "review_by": review_by,
                "note": _clean_text(entry.get("note"), MAX_NOTE_LENGTH),
            }
        if unknown:
            self.load_error = (
                f"{self.path.name} contains {len(unknown)} rate path(s) outside the "
                f"catalog, which were ignored: {', '.join(sorted(unknown)[:5])}"
            )
        try:
            version = int(raw.get("library_version", 1))
        except (TypeError, ValueError):
            version = 1
        return {
            "schema_version": SCHEMA_VERSION,
            "library_version": max(1, version),
            "updated_at": _clean_text(raw.get("updated_at"), 64) or f"{SEED_EFFECTIVE_DATE}T00:00:00+00:00",
            "rates": rates,
        }

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._data, indent=2, sort_keys=False) + "\n"
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            delete=False,
        )
        try:
            with handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, self.path)
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)
            raise

    # -- reading -----------------------------------------------------------

    @property
    def version(self) -> int:
        return int(self._data["library_version"])

    def entry(self, path: str) -> dict[str, Any]:
        return dict(self._data["rates"][path])

    def values(self) -> dict[str, float]:
        return {path: float(entry["value"]) for path, entry in self._data["rates"].items()}

    def entries(self, today: date | None = None) -> list[dict[str, Any]]:
        """Return catalog metadata joined with stored values, in catalog order."""

        moment = today or datetime.now(timezone.utc).date()
        rows: list[dict[str, Any]] = []
        for field in RATE_FIELDS:
            entry = self._data["rates"][field.path]
            default_value = float(_get_path(PROTOTYPE_DEFAULTS, field.path) or 0.0)
            rows.append(
                {
                    "path": field.path,
                    "label": field.label,
                    "unit": field.unit,
                    "category": field.category,
                    "kind": field.kind,
                    "step": field.step,
                    "minimum": field.minimum,
                    "maximum": field.maximum,
                    "help": field.help,
                    "value": float(entry["value"]),
                    "effective_date": entry["effective_date"],
                    "source": entry["source"],
                    "confidence": entry["confidence"],
                    "confidence_label": CONFIDENCE_LABELS[entry["confidence"]],
                    "review_by": entry["review_by"],
                    "note": entry["note"],
                    "unvalidated": entry["confidence"] in UNVALIDATED_CONFIDENCE,
                    "stale": self._is_stale(entry, moment),
                    "seed_value": default_value,
                    "at_seed_value": float(entry["value"]) == default_value,
                }
            )
        return rows

    @staticmethod
    def _is_stale(entry: dict[str, Any], moment: date) -> bool:
        review_by = entry.get("review_by") or ""
        if not review_by:
            return False
        try:
            return _parse_date(review_by) < moment
        except ValueError:
            return False

    def stamp(self, today: date | None = None) -> dict[str, Any]:
        """Summarize the library for display on an estimate."""

        moment = today or datetime.now(timezone.utc).date()
        rates = self._data["rates"].values()
        effective_dates = []
        for entry in rates:
            try:
                effective_dates.append(_parse_date(entry["effective_date"]))
            except ValueError:
                continue
        newest = max(effective_dates).isoformat() if effective_dates else SEED_EFFECTIVE_DATE
        unvalidated = sum(
            1 for entry in rates if entry["confidence"] in UNVALIDATED_CONFIDENCE
        )
        stale = sum(1 for entry in rates if self._is_stale(entry, moment))
        return {
            "version": self.version,
            "updated_at": self._data["updated_at"],
            "newest_effective_date": newest,
            "total": len(self._data["rates"]),
            "unvalidated": unvalidated,
            "stale": stale,
            "label": f"Rates v{self.version} · newest {newest}",
        }

    def apply_to(self, estimate: dict[str, Any]) -> dict[str, Any]:
        """Overlay library values onto an estimate payload and stamp it."""

        for path, value in self.values().items():
            _set_path(estimate, path, value)
        estimate["rate_library"] = self.stamp()
        return estimate

    # -- writing -----------------------------------------------------------

    def update(
        self,
        updates: dict[str, Any],
        changed_by: str = "",
        reason: str = "",
    ) -> list[dict[str, Any]]:
        """Validate and apply rate changes, then persist and log them.

        All updates are validated before any of them are applied, so a rejected
        batch leaves the library untouched.
        """

        if not isinstance(updates, dict) or not updates:
            raise RateValidationError(["No rate changes were supplied."])

        details: list[str] = []
        proposed: dict[str, dict[str, Any]] = {}
        for path, raw in updates.items():
            field = RATE_FIELDS_BY_PATH.get(path)
            if field is None:
                details.append(f"{path} is not a library-managed rate.")
                continue
            if not isinstance(raw, dict):
                details.append(f"{field.label}: update must be an object.")
                continue
            try:
                proposed[path] = self._validate(field, raw)
            except RateValidationError as exc:
                details.extend(exc.details)
        if details:
            raise RateValidationError(details)

        changes: list[dict[str, Any]] = []
        timestamp = _now()
        for path, entry in proposed.items():
            previous = self._data["rates"][path]
            if previous == entry:
                continue
            changes.append(
                {
                    "timestamp": timestamp,
                    "library_version": self.version + 1,
                    "path": path,
                    "label": RATE_FIELDS_BY_PATH[path].label,
                    "unit": RATE_FIELDS_BY_PATH[path].unit,
                    "previous_value": previous["value"],
                    "value": entry["value"],
                    "previous_confidence": previous["confidence"],
                    "confidence": entry["confidence"],
                    "effective_date": entry["effective_date"],
                    "source": entry["source"],
                    "note": entry["note"],
                    "changed_by": _clean_text(changed_by, 120),
                    "reason": _clean_text(reason, MAX_NOTE_LENGTH),
                }
            )
            self._data["rates"][path] = entry
        if not changes:
            return []

        self._data["library_version"] = self.version + 1
        self._data["updated_at"] = timestamp
        self._write()
        self._append_history(changes)
        return changes

    def _validate(self, field: RateField, raw: dict[str, Any]) -> dict[str, Any]:
        previous = self._data["rates"][field.path]
        details: list[str] = []

        if "value" in raw:
            try:
                value = float(raw["value"])
            except (TypeError, ValueError):
                value = None
                details.append(f"{field.label}: value must be a number.")
            if value is not None:
                if value != value or value in (float("inf"), float("-inf")):
                    details.append(f"{field.label}: value must be a finite number.")
                elif value < field.minimum:
                    details.append(
                        f"{field.label}: value must be at least {field.minimum:g} {field.unit}."
                    )
                elif field.maximum is not None and value > field.maximum:
                    details.append(
                        f"{field.label}: value must not exceed {field.maximum:g} {field.unit}."
                    )
        else:
            value = float(previous["value"])

        confidence = _clean_text(raw.get("confidence", previous["confidence"]), 32)
        if confidence not in CONFIDENCE_LEVELS:
            details.append(
                f"{field.label}: confidence must be one of {', '.join(CONFIDENCE_LEVELS)}."
            )

        effective_date = _clean_text(
            raw.get("effective_date", previous["effective_date"]), 32
        )
        try:
            _parse_date(effective_date)
        except ValueError:
            details.append(f"{field.label}: effective date must be YYYY-MM-DD.")

        review_by = _clean_text(raw.get("review_by", previous["review_by"]), 32)
        if review_by:
            try:
                _parse_date(review_by)
            except ValueError:
                details.append(f"{field.label}: review date must be YYYY-MM-DD.")

        source = _clean_text(raw.get("source", previous["source"]), MAX_SOURCE_LENGTH)
        if confidence != "placeholder" and not source:
            details.append(
                f"{field.label}: a source is required for {confidence} confidence."
            )

        if details:
            raise RateValidationError(details)

        return {
            "value": float(value),
            "effective_date": effective_date,
            "source": source,
            "confidence": confidence,
            "review_by": review_by,
            "note": _clean_text(raw.get("note", previous["note"]), MAX_NOTE_LENGTH),
        }

    # -- history -----------------------------------------------------------

    def _append_history(self, changes: Iterable[dict[str, Any]]) -> None:
        lines = "".join(
            json.dumps(change, separators=(",", ":")) + "\n" for change in changes
        )
        if not lines:
            return
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(lines)

    def history(self, limit: int = 100, path: str | None = None) -> list[dict[str, Any]]:
        """Return recorded rate changes, newest first."""

        if not self.history_path.exists():
            return []
        safe_limit = min(max(int(limit), 1), 1000)
        records: list[dict[str, Any]] = []
        try:
            with self.history_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(record, dict) and (path is None or record.get("path") == path):
                        records.append(record)
        except OSError:
            return []
        records.reverse()
        return records[:safe_limit]
