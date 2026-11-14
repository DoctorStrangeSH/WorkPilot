import unittest

from malenia.inventa import analyze_inventa, detect_header


class InventaAnalysisTests(unittest.TestCase):
    def test_actual_export_date_header_supplies_year_for_archive_sheet(self):
        rows=[["Дата выгрузки", "Id заказа", "main_partner_code_original", "Стоимость", "Статус"],
              ["2026-08-29", "TEST-1", "CARGO-1", 100, "Найден"]]
        result=analyze_inventa(rows,"29.08 (Архив)",audit_batch_limit=20)
        self.assertEqual(result["sheet_inventory_date"],"2026-08-29")
        self.assertEqual(result["eligible_audit_candidates"],1)
        override=analyze_inventa(rows,"29.08 (Архив)",audit_batch_limit=20,inventory_date="2026-09-26")
        self.assertEqual(override["audit_candidates"][0]["inventory_date"],"2026-09-26")
        self.assertNotEqual(override["audit_fingerprint"],result["audit_fingerprint"])
        for invalid in ["2026-02-30","29.08.2026",123]:
            with self.assertRaisesRegex(ValueError,"invalid_inventory_date"):
                analyze_inventa(rows,inventory_date=invalid)

    def setUp(self):
        self.rows = [
            ["Отчёт за период", None, None],
            ["Дата", "Id заказа", "main_partner_code_original", "Стоимость",
             "Наименование", "Комментарий", "Тикет", "Статус", "Группировка заказов", "впр"],
            ["2026-09-12", "LO-1", "P-1", 59880, "Куртка", "", "https://ticket/1", "В работе", "170 ЧП вне ячейки", "#N/A"],
            ["2026-09-12", "LO-1", "P-1", 59880, "Куртка", "", "", "Аномалия", "170 ЧП вне ячейки", "#N/A"],
            ["bad-date", "LO-3", "P-2", "not-money", "", "", "", "Потеря", "", ""],
            ["2026-09-12", "", "P-3", 0, "Товар", "", "", "", "", ""],
        ]

    def test_detects_real_inventa_headers_after_title_rows(self):
        row, columns = detect_header(self.rows)
        self.assertEqual(row, 1)
        self.assertEqual(columns["order_id"], 1)
        self.assertEqual(columns["status"], 7)
        self.assertEqual(columns["ticket"], 6)

    def test_analyzes_duplicates_statuses_and_invalid_rows_with_sheet_row_numbers(self):
        result = analyze_inventa(self.rows, "Тестовая ИНВента")
        self.assertEqual(result["rows_analyzed"], 4)
        self.assertEqual(result["sheet_title"], "Тестовая ИНВента")
        self.assertEqual(result["status_counts"], {"В работе": 1, "Аномалия": 1, "Потеря": 1})
        self.assertEqual(result["duplicate_order_ids"], [{"order_id": "LO-1", "rows": [3, 4]}])
        self.assertEqual(result["invalid_date_rows"], [5])
        self.assertEqual(result["invalid_cost_rows"], [5])
        self.assertEqual(result["missing_required"], {"name": 1, "order_id": 1, "status": 1})
        self.assertTrue(result["read_only"])

    def test_rejects_unrecognized_headers_and_oversized_input(self):
        with self.assertRaisesRegex(ValueError, "headers"):
            analyze_inventa([["A", "B"], ["x", "y"]])
        with self.assertRaisesRegex(ValueError, "row_limit"):
            analyze_inventa([[]] * 10001)

    def test_blank_rows_are_ignored(self):
        result = analyze_inventa(self.rows + [["", "", "", "", "", "", "", "", "", ""]])
        self.assertEqual(result["rows_analyzed"], 4)

    def test_first_order_requires_unique_id_cargo_and_valid_date(self):
        result = analyze_inventa(self.rows, "12.09.2026")
        self.assertEqual(result["first_order"]["order_id"], "LO-3")
        self.assertEqual(result["first_order"]["inventory_date"], "2026-09-12")
        rows = self.rows[:2] + [[46256, "LO-4", "CARGO-4", 100, "Товар", "", "", "В работе", "", ""]]
        first = analyze_inventa(rows, "22.08.2026")["first_order"]
        self.assertEqual((first["source_row"], first["order_id"], first["cargo_place"]), (3, "LO-4", "CARGO-4"))
        self.assertEqual(first["inventory_date"], "2026-08-22")

    def test_does_not_guess_cargo_place_from_order_id(self):
        rows = [["Дата", "Id заказа", "Стоимость", "Статус"],
                ["2026-09-12", "LO-1", 100, "В работе"]]
        result = analyze_inventa(rows, "12.09.2026")
        self.assertIsNone(result["first_order"])
        self.assertEqual(result["first_order_blocker"], "cargo_column_not_mapped")

    def test_sheet_date_overrides_row_date_and_status(self):
        rows = [["Дата", "Id заказа", "Грузоместо", "Стоимость", "Статус"],
                ["2026-08-20", "ORDER-1", "BOX-1", 100, "Выдан"],
                [46256, "ORDER-2", "BOX-2", 200, "Не найден"]]
        report = analyze_inventa(rows, "22.08 (Архив)")
        self.assertEqual(report["sheet_inventory_date"], "2026-08-22")
        self.assertEqual(report["first_order"]["order_id"], "ORDER-1")
        self.assertEqual(report["first_order"]["inventory_date"], "2026-08-22")

    def test_undated_or_ambiguous_archive_does_not_guess_year(self):
        rows = [["Дата", "Id заказа", "Грузоместо", "Стоимость", "Статус"],
                ["2025-08-22", "O-1", "B-1", 100, "Выдан"],
                ["2026-08-22", "O-2", "B-2", 100, "Выдан"]]
        self.assertEqual(analyze_inventa(rows, "22 августа")['first_order_blocker'], "sheet_date_not_verified")
        self.assertEqual(analyze_inventa(rows, "22 августа 2026")['sheet_inventory_date'], "2026-08-22")
        self.assertEqual(analyze_inventa(rows, "Архив")['first_order_blocker'], "sheet_date_not_verified")

    def test_audit_batch_paging_is_stable_and_fingerprint_detects_sheet_changes(self):
        rows = [["Дата", "Id заказа", "Грузоместо", "Стоимость", "Статус"]]
        rows += [["2026-08-22", f"ORD-{i}", f"BOX-{i}", 100, "В работе"] for i in range(23)]
        first = analyze_inventa(rows, "22.08.2026", audit_batch_limit=20)
        next_page = analyze_inventa(rows, "22.08.2026",
                                   audit_batch_limit=20, audit_batch_offset=20)
        self.assertEqual(len(first["audit_candidates"]), 20)
        self.assertEqual([x["cargo_place"] for x in next_page["audit_candidates"]],
                         ["BOX-20", "BOX-21", "BOX-22"])
        self.assertEqual(first["audit_fingerprint"], next_page["audit_fingerprint"])
        self.assertNotIn("audit_candidates", analyze_inventa(rows, "22.08.2026"))
        rows.append(["2026-08-22", "ORD-NEW", "BOX-NEW", 100, "В работе"])
        modified = analyze_inventa(rows, "22.08.2026", audit_batch_limit=20)
        self.assertNotEqual(first["audit_fingerprint"], modified["audit_fingerprint"])


if __name__ == "__main__":
    unittest.main()
