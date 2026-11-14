import unittest

from malenia.order_batch import OrderBatchError, preview_batch


def entry(code="TEST-BOX-001", inv="2026-09-12", scan=None, asgard=None, source_row=1):
    return {
        "source_row": source_row,
        "order": {"cargo_place": code, "inventory_date": inv},
        "datalens_scans": ([] if scan is None else [{
            "main_partner_code_original": code,
            "sc_id": 101366,
            "result": "OK",
            "scanned_at": scan,
        }]),
        "asgard_record": asgard,
    }


class BatchPreviewTests(unittest.TestCase):
    def test_found_asgard_and_manual_review_summary(self):
        rows = [
            entry(scan="2026-09-26", source_row=8),
            entry(code="TEST-BOX-002", scan="2026-09-06",
                  asgard={"status": "Принят на ФФ"}, source_row=9),
            entry(code="TEST-BOX-003", source_row=10),
            entry(code="TEST-BOX-004", scan="2026-09-01",
                  asgard={"status": "В пути", "box_id": "BOX-4",
                          "extended_history_statuses": ["Выдан"]}, source_row=11),
        ]
        response = preview_batch(rows)
        self.assertEqual(response["summary"], {
            "found": 1, "in_progress": 2, "manual_review": 1
        })
        self.assertEqual(response["total"], 4)
        self.assertEqual([r["source_row"] for r in response["results"]], [8, 9, 10, 11])
        self.assertEqual(response["results"][0]["proposal"]["proposed_status"], "Найден")
        self.assertEqual(response["results"][1]["proposal"]["comment"], "Принят на ФФ")
        self.assertEqual(response["results"][3]["proposal"]["comment"], "2 ШК Выдан")
        self.assertFalse(response["write_enabled"])
        self.assertTrue(response["read_only"])
        self.assertTrue(all(not row["proposal"]["write_enabled"] for row in response["results"]))

    def test_duplicates_become_manual_review_without_merging_rows(self):
        first = entry()
        second = entry(source_row=42)
        result = preview_batch([first, second])
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["results"][1]["source_row"], 42)
        self.assertEqual(result["summary"]["manual_review"], 2)
        for row in result["results"]:
            self.assertEqual(row["proposal"]["reason_code"], "duplicate_cargo_place_and_date")
            self.assertIsNone(row["proposal"]["proposed_status"])

    def test_same_cargo_place_on_different_inventory_date_is_not_duplicate(self):
        result = preview_batch([
            entry(inv="2026-09-12"),
            entry(inv="2026-09-26", source_row=2),
        ])
        self.assertEqual(result["summary"]["manual_review"], 2)
        self.assertNotEqual(result["results"][1]["proposal"]["reason_code"],
                            "duplicate_cargo_place_and_date")

    def test_reject_invalid_input_and_excessive_rows(self):
        for rows in (
            None, [], [None], ["abc"], [{}],
            [entry()] * 101,
            [{**entry(), "extra": "not allowed"}],
            [{**entry(), "order": {"cargo_place": "TEST-BOX-001"}}],
            [{**entry(), "datalens_scans": "bad"}],
            [{**entry(), "datalens_scans": [{}] * 101}],
            [{**entry(), "asgard_record": []}],
            [{**entry(), "source_row": True}],
            [{**entry(), "source_row": -1}],
            [entry(inv="not-a-date")],
        ):
            with self.subTest(rows=str(rows)[:60]), self.assertRaises(OrderBatchError):
                preview_batch(rows)

    def test_empty_or_invalid_scans_fail_closed(self):
        row = entry(scan="2026-09-25")
        row["datalens_scans"] = [
            {"main_partner_code_original": "OTHER", "sc_id": 101366,
             "result": "OK", "scanned_at": "2026-09-27"}
        ]
        result = preview_batch([row])
        self.assertEqual(result["results"][0]["proposal"]["decision"], "manual_review")


if __name__ == "__main__":
    unittest.main()
