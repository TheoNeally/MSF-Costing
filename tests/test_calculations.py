from __future__ import annotations

import math
import unittest

from msf_costing.calculations import calculate_estimate, default_estimate


class GeometryTests(unittest.TestCase):
    def test_hemisphere_geometry(self) -> None:
        payload = default_estimate()
        payload["geometry"].update(
            diameter_ft=20,
            base_angle_deg=90,
            total_panels=20,
            exact_membrane_area_sqft=0,
        )
        result = calculate_estimate(payload)

        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["geometry"]["height_ft"], 10)
        self.assertAlmostEqual(result["geometry"]["base_diameter_ft"], 20)
        self.assertAlmostEqual(result["geometry"]["truncation_pct"], 50)
        self.assertAlmostEqual(result["geometry"]["shell_area_sqft"], 200 * math.pi)

    def test_notion_reference_base_angle(self) -> None:
        payload = default_estimate()
        payload["geometry"].update(diameter_ft=100, base_angle_deg=142.62263185935032)
        result = calculate_estimate(payload)

        self.assertAlmostEqual(result["geometry"]["height_ft"], 89.7327236146)
        self.assertAlmostEqual(result["geometry"]["truncation_pct"], 89.7327236146)

    def test_exact_membrane_area_overrides_cap_area(self) -> None:
        payload = default_estimate()
        payload["geometry"]["exact_membrane_area_sqft"] = 1000
        payload["membrane"]["waste_pct"] = 12
        result = calculate_estimate(payload)

        self.assertEqual(result["geometry"]["net_membrane_area_sqft"], 1000)
        self.assertAlmostEqual(
            result["geometry"]["purchased_membrane_area_sqft"], 1120
        )
        self.assertNotIn(
            "Membrane area is approximated from the theoretical spherical cap.",
            result["warnings"],
        )


class CostTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = default_estimate()
        self.payload["geometry"].update(
            diameter_ft=10,
            base_angle_deg=90,
            total_panels=10,
            total_base_panels=2,
            unique_main_panels=3,
            unique_base_panels=2,
            exact_membrane_area_sqft=100,
        )
        self.payload["membrane"].update(
            fabric_rate_low=4,
            fabric_rate_base=8,
            fabric_rate_high=12,
            waste_pct=0,
            fabrication_per_panel=0,
        )
        self.payload["other"].update(
            packaging_freight=0,
            project_management=0,
            overhead_pct=0,
            warranty_pct=0,
            contingency_pct=0,
        )

    def test_panel_set_method_does_not_add_beam_quote(self) -> None:
        self.payload["frame"].update(
            cost_method="panel_set",
            panel_set_cost=1150,
            beam_set_cost=999999,
            setup_cost_per_unique=0,
        )
        result = calculate_estimate(self.payload)

        self.assertEqual(result["frame"]["cost"], 11500)
        self.assertEqual(result["scenarios"]["base"]["cost_bases"]["manufacturing"], 12300)

    def test_component_method_builds_frame_from_components(self) -> None:
        self.payload["frame"].update(
            cost_method="components",
            beam_set_cost=100,
            beam_sets_per_panel=3,
            fittings_per_panel=20,
            hardware_per_panel=10,
            fabrication_per_panel=30,
            setup_cost_per_unique=50,
        )
        result = calculate_estimate(self.payload)

        self.assertEqual(result["frame"]["cost"], 3600)
        self.assertEqual(result["breakdown"]["Unique-panel setup/tooling"], 250)
        self.assertEqual(result["scenarios"]["base"]["cost_bases"]["manufacturing"], 4650)

    def test_accessory_cost_stages(self) -> None:
        self.payload["frame"]["panel_set_cost"] = 0
        self.payload["accessories"] = [
            {"description": "Door", "quantity": 1, "unit_cost": 100, "stage": "manufacturing"},
            {"description": "Freight allowance", "quantity": 2, "unit_cost": 50, "stage": "delivered"},
            {"description": "Crane", "quantity": 1, "unit_cost": 200, "stage": "installed"},
            {"description": "Warranty item", "quantity": 1, "unit_cost": 300, "stage": "fully_loaded"},
        ]
        result = calculate_estimate(self.payload)

        self.assertEqual(result["scenarios"]["base"]["cost_bases"]["manufacturing"], 900)
        self.assertEqual(result["scenarios"]["base"]["cost_bases"]["delivered"], 1000)
        self.assertEqual(result["scenarios"]["base"]["cost_bases"]["installed"], 1200)
        self.assertEqual(result["scenarios"]["base"]["cost_bases"]["fully_loaded"], 1500)

    def test_target_margin_and_entered_price(self) -> None:
        self.payload["pricing"].update(
            basis="manufacturing", mode="target_margin", target_margin_pct=20
        )
        result = calculate_estimate(self.payload)
        cost = result["pricing"]["selected_cost"]

        self.assertAlmostEqual(result["pricing"]["selling_price"], cost / 0.8)
        self.assertAlmostEqual(result["pricing"]["gross_margin_pct"], 20)

        self.payload["pricing"].update(mode="entered_price", entered_price=20000)
        result = calculate_estimate(self.payload)
        expected = (20000 - result["pricing"]["selected_cost"]) / 20000 * 100
        self.assertAlmostEqual(result["pricing"]["gross_margin_pct"], expected)

    def test_installation_uses_complete_crew_days(self) -> None:
        self.payload["labor"].update(
            crew_size=4,
            panels_per_day=3,
            hours_per_day=8,
            field_rate=50,
            equipment_per_day=100,
        )
        result = calculate_estimate(self.payload)

        self.assertEqual(result["quantities"]["installation_days"], 4)
        self.assertEqual(result["breakdown"]["Field labor"], 6400)
        self.assertEqual(result["breakdown"]["Field equipment"], 400)

    def test_invalid_inputs_are_rejected(self) -> None:
        self.payload["geometry"].update(diameter_ft=0, base_angle_deg=180, total_panels=0)
        self.payload["pricing"].update(target_margin_pct=100)
        result = calculate_estimate(self.payload)

        self.assertFalse(result["ok"])
        self.assertGreaterEqual(len(result["errors"]), 4)


if __name__ == "__main__":
    unittest.main()
