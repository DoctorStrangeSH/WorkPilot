import unittest

from malenia.order_check import (
    DECISION_ASGARD,
    DECISION_FOUND,
    DECISION_MANUAL_REVIEW,
    evaluate_order,
)


class OrderCheckRuleTests(unittest.TestCase):
    def setUp(self):
        self.order = {"cargo_place": "CP-001", "inventory_date": "2026-11-10"}

    def scan(self, partner="CP-001", sc_id=101366, result="OK", scanned_at="2026-11-11"):
        return {
            "main_partner_code_original": partner,
            "sc_id": sc_id,
            "result": result,
            "scanned_at": scanned_at,
        }

    def test_latest_successful_scan_after_inventory_marks_found_green(self):
        scans = [
            self.scan(scanned_at="2026-11-09"),
            self.scan(result="FAILED", scanned_at="2026-11-14"),
            self.scan(scanned_at="2026-11-12"),
            self.scan(scanned_at="2026-11-11"),
        ]
        result = evaluate_order(self.order, scans)
        self.assertEqual(result["decision"], DECISION_FOUND)
        self.assertEqual(result["proposed_status"], "Найден")
        self.assertEqual(result["color"], "green")
        self.assertEqual(result["evidence"]["sc_id"], "101366")
        self.assertEqual(result["evidence"]["scan_date"], "2026-11-12")
        self.assertFalse(result["write_enabled"])

    def test_only_exact_partner_code_target_sc_and_success_result_are_used(self):
        scans = [
            self.scan(partner="CP-001-extra", scanned_at="2026-11-15"),
            self.scan(sc_id=101367, scanned_at="2026-11-15"),
            self.scan(result="ERROR", scanned_at="2026-11-15"),
            self.scan(scanned_at="2026-11-10"),
        ]
        result = evaluate_order(self.order, scans, {"status": "Принят на ФФ"})
        self.assertEqual(result["decision"], DECISION_ASGARD)
        self.assertEqual(result["comment"], "Принят на ФФ")

    def test_successful_scan_on_inventory_date_is_not_after_inventory_date(self):
        result = evaluate_order(
            self.order, [self.scan(scanned_at="2026-11-10")],
            {"status": "Выдан"},
        )
        self.assertEqual(result["decision"], DECISION_ASGARD)
        self.assertIsNone(result["comment"])

    def test_matching_successful_scan_with_invalid_date_requires_review(self):
        result = evaluate_order(
            self.order, [self.scan(scanned_at="unknown")],
            {"status": "Принят на ФФ"},
        )
        self.assertEqual(result["decision"], DECISION_MANUAL_REVIEW)
        self.assertEqual(result["reason_code"], "datalens_matching_scan_has_invalid_date")
        self.assertIsNone(result["proposed_status"])

    def test_asgard_accepted_at_fulfillment_maps_to_in_progress_orange(self):
        result = evaluate_order(self.order, [], {"status": "Принят на ФФ"})
        self.assertEqual(result["decision"], DECISION_ASGARD)
        self.assertEqual(result["proposed_status"], "В работе")
        self.assertEqual(result["comment"], "Принят на ФФ")
        self.assertEqual(result["color"], "orange")
        self.assertFalse(result["write_enabled"])

    def test_asgard_issued_maps_to_issued_green(self):
        result = evaluate_order(self.order, [], {"status": "Выдан"})
        self.assertEqual(result["proposed_status"], "Выдан")
        self.assertIsNone(result["comment"])
        self.assertEqual(result["color"], "green")

    def test_asgard_both_statuses_in_progress_maps_to_in_progress(self):
        result = evaluate_order(
            self.order, [],
            {"status": "В работе", "statuses": ["В работе", "В работе"]},
        )
        self.assertEqual(result["proposed_status"], "В работе")
        self.assertEqual(result["reason_code"], "asgard_both_statuses_in_progress")
        self.assertEqual(result["evidence"]["statuses"], ["В работе", "В работе"])
        self.assertEqual(result["color"], "orange")

    def test_asgard_partial_or_unknown_second_status_requires_review(self):
        result = evaluate_order(
            self.order, [],
            {"status": "В работе", "statuses": ["В работе", "Ожидает"]},
        )
        self.assertEqual(result["decision"], DECISION_MANUAL_REVIEW)

    def test_asgard_in_transit_requires_box_and_extended_history(self):
        missing_box = evaluate_order(
            self.order, [], {"status": "В пути", "extended_history_statuses": ["Выдан"]}
        )
        self.assertEqual(missing_box["decision"], DECISION_MANUAL_REVIEW)
        self.assertEqual(missing_box["reason_code"], "asgard_box_id_required_for_in_transit")

        missing_history = evaluate_order(
            self.order, [], {"status": "В пути", "box_id": "BOX-1"}
        )
        self.assertEqual(missing_history["decision"], DECISION_MANUAL_REVIEW)
        self.assertEqual(missing_history["reason_code"], "asgard_extended_history_required_for_in_transit")

    def test_asgard_in_transit_with_issued_extended_history_maps_to_two_barcodes_comment(self):
        result = evaluate_order(
            self.order, [],
            {"status": "В пути", "box_id": "BOX-1",
             "extended_history_statuses": ["Принят", "В пути", "Выдан"]},
        )
        self.assertEqual(result["decision"], DECISION_ASGARD)
        self.assertEqual(result["proposed_status"], "В работе")
        self.assertEqual(result["comment"], "2 ШК Выдан")
        self.assertEqual(result["color"], "orange")
        self.assertEqual(result["evidence"]["box_id"], "BOX-1")

    def test_asgard_in_transit_without_issued_history_requires_review(self):
        result = evaluate_order(
            self.order, [],
            {"status": "В пути", "box_id": "BOX-1",
             "extended_history_statuses": ["Принят", "В пути"]},
        )
        self.assertEqual(result["decision"], DECISION_MANUAL_REVIEW)
        self.assertEqual(result["reason_code"], "asgard_in_transit_without_confirmed_issued_history")

    def test_unknown_or_missing_asgard_status_requires_review(self):
        unknown = evaluate_order(self.order, [], {"status": "Ожидает"})
        self.assertEqual(unknown["decision"], DECISION_MANUAL_REVIEW)
        self.assertEqual(unknown["reason_code"], "unknown_asgard_status")

        missing = evaluate_order(self.order, [])
        self.assertEqual(missing["decision"], DECISION_MANUAL_REVIEW)
        self.assertEqual(missing["reason_code"], "asgard_record_required")

    def test_input_validation_fails_closed(self):
        for order in (
            {},
            {"cargo_place": "", "inventory_date": "2026-11-10"},
            {"cargo_place": "CP-1", "inventory_date": "10.11.2026"},
        ):
            with self.subTest(order=order), self.assertRaises(ValueError):
                evaluate_order(order, [])
        with self.assertRaises(ValueError):
            evaluate_order(self.order, {})


if __name__ == "__main__":
    unittest.main()
