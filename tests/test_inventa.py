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
        self.assertEqual(result["rows_analyzed"], 3)
        self.assertEqual(result["non_order_rows_skipped"], 1)
        self.assertEqual(result["sheet_title"], "Тестовая ИНВента")
        self.assertEqual(result["status_counts"], {"В работе": 1, "Аномалия": 1, "Потеря": 1})
        self.assertEqual(result["duplicate_order_ids"], [{"order_id": "LO-1", "rows": [3, 4]}])
        self.assertEqual(result["invalid_date_rows"], [5])
        self.assertEqual(result["invalid_cost_rows"], [5])
        self.assertEqual(result["missing_required"], {"name": 0, "status": 0})
        self.assertTrue(result["read_only"])
        self.assertEqual(result["first_order_preview"], {
            "row": 3, "order_id": "LO-1", "partner_code": "P-1",
            "date": "2026-09-12", "cost": "59880", "name": "Куртка",
            "ticket": "https://ticket/1", "status": "В работе",
            "group": "170 ЧП вне ячейки",
        })
        self.assertEqual(result["first_order_cross_check"]["state"], "needs_external_sources")
        self.assertFalse(result["first_order_cross_check"]["verified"])
        self.assertFalse(result["first_order_cross_check"]["write_enabled"])

    def test_recognizes_actual_inventa_export_with_unlabelled_status_column(self):
        rows = [
            ["Дата выгрузки", "Id заказа", "main_partner_code_original", "Стоимость",
             "Наименование", "Комментарий", "Тикет", "", "Группировка заказов", "ВПР"],
            ["2026-08-22", "PZV_FBS_RET_7720160", "PZV_FBS_RET_7720160", 29980,
             "Кеды RALF RINGER", "", "https://ticket.example/1", "В СКК",
             "170 ЧП вне ячейки ВП", "#N/A"],
            ["2026-08-22", "5891405835", "5891405835", 24319,
             "Кроссовки", "Найден, исключить", "", "Найден",
             "170 ЧП вне ячейки ВП", "#N/A"],
            ["2026-08-22", "6001908482", "6001908482", 5283,
             "Комплект", "", "", "Аномалия", "170 ЧП вне ячейки ВП", "#N/A"],
        ]
        header, columns = detect_header(rows)
        self.assertEqual(header, 0)
        self.assertEqual(columns["date"], 0)
        self.assertEqual(columns["order_id"], 1)
        self.assertEqual(columns["partner"], 2)
        self.assertEqual(columns["status"], 7)
        self.assertEqual(columns["group"], 8)
        report = analyze_inventa(rows, "ИНВента")
        self.assertEqual(report["rows_analyzed"], 3)
        self.assertEqual(report["first_order_preview"]["order_id"], "PZV_FBS_RET_7720160")
        self.assertEqual(report["first_order_preview"]["status"], "В СКК")
        self.assertEqual(report["first_order_preview"]["ticket"], "https://ticket.example/1")
        self.assertEqual(report["status_counts"], {"В СКК": 1, "Найден": 1, "Аномалия": 1})
        self.assertTrue(report["read_only"])

    def test_real_archive_layout_infers_blank_product_name_and_normalizes_serial_date(self):
        rows = [
            ["Дата выгрузки", "Id заказа", "main_partner_code_original", "Стоимость",
             "", "Комментарий", "Тикет", "", "Группировка заказов", "ВПР"],
            [46256, "PVZ_FBS_RET_7720160", "PVZ_FBS_RET_7720160", 29980,
             "Кеды RALF RINGER", "В СКК 2026/10/27 00:26:29",
             "FA254276C66034580038", "Исключение",
             "170 ЧП вне ячейки ВП", "#N/A"],
            [46256, "", "", "", "", "Итого", "", "", "", ""],
            [46256, "5891405835", "5891405835", 24319,
             "Кроссовки", "Найден, исключить", "",
             "Найден, исключить", "170 ЧП вне ячейки ВП", "#N/A"],
        ]
        header, columns = detect_header(rows)
        self.assertEqual(header, 0)
        self.assertEqual(columns["name"], 4)
        self.assertEqual(columns["status"], 7)
        report = analyze_inventa(rows, "22.08 (Архив)")
        self.assertEqual(report["rows_analyzed"], 2)
        self.assertEqual(report["non_order_rows_skipped"], 1)
        first = report["first_order_preview"]
        self.assertEqual(first["row"], 2)
        self.assertEqual(first["order_id"], "PVZ_FBS_RET_7720160")
        self.assertEqual(first["partner_code"], "PVZ_FBS_RET_7720160")
        self.assertEqual(first["date"], "2026-08-22")
        self.assertEqual(first["cost"], "29980")
        self.assertEqual(first["name"], "Кеды RALF RINGER")
        self.assertEqual(first["status"], "Исключение")
        self.assertEqual(first["ticket"], "FA254276C66034580038")
        self.assertEqual(report["missing_ticket_rows"], [4])
        self.assertEqual(report["invalid_date_rows"], [])

    def test_header_requires_all_core_columns(self):
        rows = [
            ["Комментарий", "Тикет", "Наименование", "Группировка"],
            ["x", "https://ticket", "Товар", "Группа"],
        ]
        with self.assertRaisesRegex(ValueError, "headers"):
            detect_header(rows)

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
