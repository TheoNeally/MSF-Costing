"""Calculation engine for the MSF radome costing tool.

The engine is intentionally independent of the HTTP server and GUI.  A future
geometry program can replace the approximation layer by supplying an exact BOM
without changing the costing or pricing stages.
"""

from __future__ import annotations

from copy import deepcopy
from math import ceil, pi, radians, sin, sqrt
from typing import Any


PROTOTYPE_DEFAULTS: dict[str, Any] = {
    "project": {
        "name": "Untitled MSF Radome",
        "customer": "",
        "project_type": "DoD",
        "estimator": "",
        "notes": "",
    },
    "geometry": {
        "diameter_ft": 30.0,
        "base_angle_deg": 142.623,
        "geometry_type": "quasi-random",
        "total_panels": 80,
        "total_base_panels": 10,
        "unique_main_panels": 12,
        "unique_base_panels": 5,
        "exact_membrane_area_sqft": 0.0,
    },
    "frame": {
        "cost_method": "panel_set",
        "panel_set_cost": 1150.0,
        "beam_set_cost": 260.0,
        "beam_sets_per_panel": 3.0,
        "size_factor": 1.0,
        "beam_factor": 1.0,
        "complexity_factor": 1.0,
        "fittings_per_panel": 0.0,
        "hardware_per_panel": 0.0,
        "fabrication_per_panel": 0.0,
        "setup_cost_per_unique": 0.0,
    },
    "membrane": {
        "fabric_rate_low": 4.0,
        "fabric_rate_base": 8.0,
        "fabric_rate_high": 12.0,
        "waste_pct": 10.0,
        "faceting_factor": 1.0,
        "fabrication_per_panel": 0.0,
    },
    "labor": {
        "engineering_base_hours": 0.0,
        "engineering_hours_per_unique": 0.0,
        "engineering_rate": 100.0,
        "shop_hours_per_panel": 0.0,
        "shop_setup_hours_per_unique": 0.0,
        "shop_rate": 60.0,
        "crew_size": 0.0,
        "field_rate": 85.0,
        "panels_per_day": 0.0,
        "hours_per_day": 8.0,
        "equipment_per_day": 0.0,
        "mobilization": 0.0,
        "travel_fixed": 0.0,
        "travel_days": 0.0,
        "per_diem": 0.0,
    },
    "other": {
        "packaging_freight": 0.0,
        "project_management": 0.0,
        "overhead_pct": 0.0,
        "warranty_pct": 0.0,
        "contingency_pct": 15.0,
    },
    "accessories": [],
    "pricing": {
        "basis": "fully_loaded",
        "mode": "target_margin",
        "target_margin_pct": 30.0,
        "entered_price": 0.0,
    },
}


def default_estimate() -> dict[str, Any]:
    """Return a mutable copy of the prototype defaults."""

    return deepcopy(PROTOTYPE_DEFAULTS)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


def _nonnegative(value: Any, default: float = 0.0) -> float:
    return max(0.0, _number(value, default))


def _section(payload: dict[str, Any], name: str) -> dict[str, Any]:
    value = payload.get(name, {})
    return value if isinstance(value, dict) else {}


def _accessory_totals(payload: dict[str, Any]) -> dict[str, float]:
    totals = {
        "manufacturing": 0.0,
        "delivered": 0.0,
        "installed": 0.0,
        "fully_loaded": 0.0,
    }
    accessories = payload.get("accessories", [])
    if not isinstance(accessories, list):
        return totals
    for item in accessories:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("stage", "manufacturing"))
        if stage not in totals:
            stage = "manufacturing"
        totals[stage] += _nonnegative(item.get("quantity", 0)) * _nonnegative(
            item.get("unit_cost", 0)
        )
    return totals


def calculate_estimate(payload: dict[str, Any]) -> dict[str, Any]:
    """Calculate a complete estimate from an untrusted JSON-compatible payload."""

    if not isinstance(payload, dict):
        payload = {}

    geometry = _section(payload, "geometry")
    frame = _section(payload, "frame")
    membrane = _section(payload, "membrane")
    labor = _section(payload, "labor")
    other = _section(payload, "other")
    pricing = _section(payload, "pricing")

    errors: list[str] = []
    warnings: list[str] = []

    diameter = _number(geometry.get("diameter_ft"), 0)
    base_angle_deg = _number(geometry.get("base_angle_deg"), 0)
    total_panels = int(_nonnegative(geometry.get("total_panels")))
    total_base_panels = int(_nonnegative(geometry.get("total_base_panels")))
    unique_main = int(_nonnegative(geometry.get("unique_main_panels")))
    unique_base = int(_nonnegative(geometry.get("unique_base_panels")))
    total_unique = unique_main + unique_base

    if diameter <= 0:
        errors.append("Sphere diameter must be greater than zero.")
    if not 0 < base_angle_deg < 180:
        errors.append("Base angle must be between 0 and 180 degrees.")
    if total_panels <= 0:
        errors.append("Total panel count must be greater than zero.")
    if total_base_panels > total_panels:
        errors.append("Base-panel quantity cannot exceed total panel quantity.")
    if total_unique > total_panels and total_panels > 0:
        warnings.append("Unique panel count exceeds total panel count.")
    if unique_base > total_base_panels and total_base_panels > 0:
        warnings.append("Unique base-panel count exceeds total base-panel quantity.")

    phi = radians(base_angle_deg)
    radius = diameter / 2 if diameter > 0 else 0.0
    truncation_fraction = sin(phi / 2) ** 2 if 0 < base_angle_deg < 180 else 0.0
    height = diameter * truncation_fraction
    base_diameter = diameter * sin(phi) if 0 < base_angle_deg < 180 else 0.0
    shell_area = pi * diameter * height
    base_circumference = pi * base_diameter
    average_panel_area = shell_area / total_panels if total_panels else 0.0
    average_edge_length = (
        sqrt(4 * average_panel_area / sqrt(3)) if average_panel_area > 0 else 0.0
    )
    approximate_panelized_beam_length = total_panels * 3 * average_edge_length

    exact_membrane_area = _nonnegative(geometry.get("exact_membrane_area_sqft"))
    faceting_factor = _nonnegative(membrane.get("faceting_factor"), 1.0)
    if faceting_factor == 0:
        faceting_factor = 1.0
    net_membrane_area = exact_membrane_area or shell_area * faceting_factor
    waste_pct = _nonnegative(membrane.get("waste_pct"))
    purchased_membrane_area = net_membrane_area * (1 + waste_pct / 100)

    geometry_type = str(geometry.get("geometry_type", "quasi-random"))
    if exact_membrane_area <= 0:
        warnings.append(
            "Membrane area is approximated from the theoretical spherical cap."
        )
    if geometry_type == "quasi-random":
        warnings.append(
            "Quasi-random panel dimensions are approximated; import the detailed BOM when available."
        )

    size_factor = _nonnegative(frame.get("size_factor"), 1.0)
    beam_factor = _nonnegative(frame.get("beam_factor"), 1.0)
    complexity_factor = _nonnegative(frame.get("complexity_factor"), 1.0)
    for label, value in (
        ("Frame size", size_factor),
        ("Beam", beam_factor),
        ("Complexity", complexity_factor),
    ):
        if value == 0:
            errors.append(f"{label} factor must be greater than zero.")

    cost_method = str(frame.get("cost_method", "panel_set"))
    beam_sets = total_panels * _nonnegative(frame.get("beam_sets_per_panel"), 3)
    component_frame_detail = {
        "beam_sets": beam_sets,
        "beam_cost": 0.0,
        "fittings": 0.0,
        "hardware": 0.0,
        "fabrication": 0.0,
    }
    if cost_method == "components":
        component_frame_detail["beam_cost"] = (
            beam_sets
            * _nonnegative(frame.get("beam_set_cost"))
            * size_factor
            * beam_factor
        )
        component_frame_detail["fittings"] = total_panels * _nonnegative(
            frame.get("fittings_per_panel")
        )
        component_frame_detail["hardware"] = total_panels * _nonnegative(
            frame.get("hardware_per_panel")
        )
        component_frame_detail["fabrication"] = (
            total_panels
            * _nonnegative(frame.get("fabrication_per_panel"))
            * complexity_factor
        )
        frame_cost = sum(
            component_frame_detail[key]
            for key in ("beam_cost", "fittings", "hardware", "fabrication")
        )
        if not any(
            _nonnegative(frame.get(key))
            for key in (
                "fittings_per_panel",
                "hardware_per_panel",
                "fabrication_per_panel",
            )
        ):
            warnings.append(
                "Component frame method currently excludes fittings, hardware, and frame fabrication."
            )
    else:
        cost_method = "panel_set"
        frame_cost = (
            total_panels
            * _nonnegative(frame.get("panel_set_cost"))
            * size_factor
            * beam_factor
            * complexity_factor
        )
        warnings.append(
            "The BK-1 reference panel-set cost is applied uniformly to all panel shapes."
        )

    unique_setup_cost = total_unique * _nonnegative(
        frame.get("setup_cost_per_unique")
    )
    membrane_fabrication = total_panels * _nonnegative(
        membrane.get("fabrication_per_panel")
    )

    engineering_hours = _nonnegative(labor.get("engineering_base_hours")) + (
        total_unique * _nonnegative(labor.get("engineering_hours_per_unique"))
    )
    engineering_cost = engineering_hours * _nonnegative(labor.get("engineering_rate"))
    shop_hours = (
        total_panels * _nonnegative(labor.get("shop_hours_per_panel"))
        + total_unique * _nonnegative(labor.get("shop_setup_hours_per_unique"))
    )
    shop_cost = shop_hours * _nonnegative(labor.get("shop_rate"))
    if engineering_hours == 0:
        warnings.append("Engineering labor is not included.")
    if shop_hours == 0:
        warnings.append("Shop labor is not included.")

    crew_size = _nonnegative(labor.get("crew_size"))
    panels_per_day = _nonnegative(labor.get("panels_per_day"))
    installation_days = (
        ceil(total_panels / panels_per_day)
        if total_panels and crew_size and panels_per_day
        else 0
    )
    field_labor = (
        installation_days
        * crew_size
        * _nonnegative(labor.get("hours_per_day"), 8)
        * _nonnegative(labor.get("field_rate"))
    )
    equipment = installation_days * _nonnegative(labor.get("equipment_per_day"))
    mobilization = _nonnegative(labor.get("mobilization"))
    travel_fixed = _nonnegative(labor.get("travel_fixed"))
    travel_days = _nonnegative(labor.get("travel_days"))
    per_diem = (
        crew_size
        * (installation_days + travel_days)
        * _nonnegative(labor.get("per_diem"))
    )
    installation_cost = field_labor + equipment + mobilization + travel_fixed + per_diem
    if installation_cost == 0:
        warnings.append("Installation, travel, and field equipment are not included.")

    accessory_costs = _accessory_totals(payload)
    packaging_freight = _nonnegative(other.get("packaging_freight"))
    project_management = _nonnegative(other.get("project_management"))
    overhead_pct = _nonnegative(other.get("overhead_pct"))
    warranty_pct = _nonnegative(other.get("warranty_pct"))
    contingency_pct = _nonnegative(other.get("contingency_pct"))

    fabric_rates = {
        "low": _nonnegative(membrane.get("fabric_rate_low"), 4),
        "base": _nonnegative(membrane.get("fabric_rate_base"), 8),
        "high": _nonnegative(membrane.get("fabric_rate_high"), 12),
    }
    if not fabric_rates["low"] <= fabric_rates["base"] <= fabric_rates["high"]:
        warnings.append("Fabric low/base/high rates are not in ascending order.")

    scenario_results: dict[str, dict[str, Any]] = {}
    for scenario, fabric_rate in fabric_rates.items():
        membrane_material = purchased_membrane_area * fabric_rate
        manufacturing = (
            frame_cost
            + unique_setup_cost
            + membrane_material
            + membrane_fabrication
            + engineering_cost
            + shop_cost
            + accessory_costs["manufacturing"]
        )
        delivered = manufacturing + packaging_freight + accessory_costs["delivered"]
        installed = delivered + installation_cost + accessory_costs["installed"]
        loaded_base = (
            installed + project_management + accessory_costs["fully_loaded"]
        )
        overhead = loaded_base * overhead_pct / 100
        warranty = loaded_base * warranty_pct / 100
        contingency = loaded_base * contingency_pct / 100
        fully_loaded = loaded_base + overhead + warranty + contingency
        scenario_results[scenario] = {
            "fabric_rate": fabric_rate,
            "membrane_material": membrane_material,
            "cost_bases": {
                "manufacturing": manufacturing,
                "delivered": delivered,
                "installed": installed,
                "fully_loaded": fully_loaded,
            },
            "loaded_adjustments": {
                "overhead": overhead,
                "warranty": warranty,
                "contingency": contingency,
            },
        }

    base_scenario = scenario_results["base"]
    breakdown = {
        "Frame": frame_cost,
        "Unique-panel setup/tooling": unique_setup_cost,
        "Raw membrane": base_scenario["membrane_material"],
        "Membrane fabrication": membrane_fabrication,
        "Engineering labor": engineering_cost,
        "Shop labor": shop_cost,
        "Manufacturing accessories": accessory_costs["manufacturing"],
        "Packaging and freight": packaging_freight,
        "Delivered-stage accessories": accessory_costs["delivered"],
        "Field labor": field_labor,
        "Field equipment": equipment,
        "Mobilization": mobilization,
        "Travel": travel_fixed,
        "Per diem": per_diem,
        "Installed-stage accessories": accessory_costs["installed"],
        "Project management": project_management,
        "Fully-loaded accessories": accessory_costs["fully_loaded"],
        "Overhead": base_scenario["loaded_adjustments"]["overhead"],
        "Warranty allowance": base_scenario["loaded_adjustments"]["warranty"],
        "Contingency": base_scenario["loaded_adjustments"]["contingency"],
    }

    basis = str(pricing.get("basis", "fully_loaded"))
    if basis not in base_scenario["cost_bases"]:
        basis = "fully_loaded"
    selected_cost = base_scenario["cost_bases"][basis]
    pricing_mode = str(pricing.get("mode", "target_margin"))
    target_margin_pct = _number(pricing.get("target_margin_pct"), 0)
    entered_price = _nonnegative(pricing.get("entered_price"))
    if pricing_mode == "entered_price":
        selling_price = entered_price
        if selling_price <= 0:
            warnings.append("Enter a selling price to calculate achieved margin.")
    else:
        pricing_mode = "target_margin"
        if not 0 <= target_margin_pct < 100:
            errors.append("Target gross margin must be at least 0% and less than 100%.")
            selling_price = 0.0
        else:
            selling_price = selected_cost / (1 - target_margin_pct / 100)

    gross_profit = selling_price - selected_cost
    gross_margin_pct = (
        gross_profit / selling_price * 100 if selling_price > 0 else 0.0
    )
    markup_pct = gross_profit / selected_cost * 100 if selected_cost > 0 else 0.0

    return {
        "ok": not errors,
        "estimate_class": "ROM",
        "errors": errors,
        "warnings": list(dict.fromkeys(warnings)),
        "geometry": {
            "radius_ft": radius,
            "height_ft": height,
            "base_diameter_ft": base_diameter,
            "base_circumference_ft": base_circumference,
            "truncation_fraction": truncation_fraction,
            "truncation_pct": truncation_fraction * 100,
            "shell_area_sqft": shell_area,
            "net_membrane_area_sqft": net_membrane_area,
            "purchased_membrane_area_sqft": purchased_membrane_area,
            "average_panel_area_sqft": average_panel_area,
            "average_equilateral_edge_ft": average_edge_length,
            "approximate_panelized_beam_length_ft": approximate_panelized_beam_length,
            "total_unique_panels": total_unique,
        },
        "quantities": {
            "total_panels": total_panels,
            "total_base_panels": total_base_panels,
            "beam_sets": beam_sets,
            "engineering_hours": engineering_hours,
            "shop_hours": shop_hours,
            "installation_days": installation_days,
        },
        "frame": {
            "method": cost_method,
            "cost": frame_cost,
            "component_detail": component_frame_detail,
        },
        "breakdown": breakdown,
        "scenarios": scenario_results,
        "pricing": {
            "basis": basis,
            "mode": pricing_mode,
            "selected_cost": selected_cost,
            "selling_price": selling_price,
            "gross_profit": gross_profit,
            "gross_margin_pct": gross_margin_pct,
            "markup_pct": markup_pct,
        },
    }
