import unittest

from malenia.site_reconciliation import SiteSnapshotError, reconcile_tables


def snapshots():
    return {
        "inventory": {
            "columns": ["cargo_place", "inventory_date"],
            "rows": [["TEST-001", "2026-09-12"], ["TEST-002", "2026-09-12"]],
        },
        "datalens": {
            "columns": ["main_partner_code_original", "sc_id", "result", "scanned_at"],
            "rows": [["TEST-001", "101366", "OK", "2026-09-14T10:00:00"],
                     ["TEST-002", "222", "OK", "2026-09-19T11:00:00"]],
        },
        "asgard": {
            "columns": ["cargo_place", "status"],
            "rows": [["TEST-002", "Принят на ФФ"]],
        },
    }


class SiteReconciliationTests(unittest.TestCase):
    def test_joins_visible_tables_without_writes(self):
        value = reconcile_tables(snapshots())
        self.assertEqual(value["total"], 2)
        self.assertEqual(value["summary"], {
            "found": 1, "in_progress": 1, "manual_review": 0
        })
        self.assertFalse(value["write_enabled"])
        self.assertTrue(value["read_only"])
        self.assertNotIn("TEST-001", str(value))

    def test_unknown_data_requires_manual(self):
        data = snapshots()
        data["datalens"]["rows"] = []
        data["asgard"]["rows"] = []
        self.assertEqual(reconcile_tables(data)["summary"]["manual_review"], 2)

    def test_duplicate_asgard_is_ambiguous(self):
        data = snapshots()
        data["asgard"]["rows"].append(["TEST-002", "Выдан"])
        self.assertEqual(reconcile_tables(data)["summary"]["manual_review"], 1)

    def test_duplicate_inventory_fails_closed(self):
        data = snapshots()
        data["inventory"]["rows"].append(["TEST-001", "2026-09-12"])
        self.assertEqual(reconcile_tables(data)["summary"]["manual_review"], 2)

    def test_transit_history_is_not_inferred_from_summary_cell(self):
        data = snapshots()
        data["datalens"]["rows"] = []
        data["asgard"]["columns"] = [
            "cargo_place", "status", "box_id", "extended_history_statuses"
        ]
        data["asgard"]["rows"] = [["TEST-002", "В пути", "BOX-12", "Выдан"]]
        self.assertEqual(reconcile_tables(data)["summary"]["manual_review"], 2)

    def test_invalid_schema_does_not_guess(self):
        for transform in [
            lambda x: x["inventory"].update(columns=["barcode", "date"]),
            lambda x: x["datalens"].update(columns=["cargo_place", "sc", "status", "date"]),
            lambda x: x["asgard"].update(rows=[["TEST-002"]]),
            lambda x: x["inventory"].update(rows=[["TEST-001", "not-a-date"]]),
            lambda x: x["inventory"].update(rows=[["TEST-001", "2026-09-12"]] * 101),
        ]:
            data = snapshots()
            transform(data)
            with self.subTest(data=data), self.assertRaises(SiteSnapshotError):
                reconcile_tables(data)


if __name__ == "__main__":
    unittest.main()
