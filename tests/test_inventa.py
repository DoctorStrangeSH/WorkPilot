import unittest

from malenia.inventa import analyze_inventa, detect_header


class InventaAnalysisTests(unittest.TestCase):
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
        self.assertEqual(result["invalid_date_rows"], [5, 6])
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


if __name__ == "__main__":
    unittest.main()
