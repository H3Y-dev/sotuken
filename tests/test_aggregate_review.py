import tempfile
from pathlib import Path
import unittest

from eval.aggregate_review import (
    REASON_CATEGORIES,
    TOLERANCE_PERCENT_FS,
    classify_reason,
    load_rows,
    parse_number,
    render_markdown,
    summarize,
)


HEADER = "番号,ファイル名,条件,止まった段階,誤差%FS,人の総合判定,いちばんの原因\n"
BODY = (
    "1,a.png,反射,ok,2.0,×,数字の検出ができていない\n"
    "2,b.png,反射,scale,-,×,画像が粗い\n"
    "3,c.png,斜め,ok,7.5,×,\n"
    "4,d.png,斜め,center,-,×,針の判定がずれている\n"
    "5,e.png,ブレ,ok,5.0,○,メモリの細かい判定ができていない\n"
)


def write_csv(text, directory, name="sample.csv"):
    path = Path(directory) / name
    path.write_text(text, encoding="utf-8-sig")
    return path


class AggregateReviewTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.path = write_csv(HEADER + BODY, self.tempdir.name)
        self.rows = load_rows([self.path])
        self.summary = summarize(self.rows)

    def test_reads_bom_csv_and_five_rows(self):
        self.assertEqual(len(self.rows), 5)
        self.assertEqual(self.rows[0]["ファイル名"], "a.png")

    def test_overall_counts(self):
        self.assertEqual(self.summary["total"], 5)
        self.assertEqual(self.summary["ok_count"], 3)
        self.assertEqual(self.summary["stopped_count"], 2)
        self.assertEqual(self.summary["stage_counts"],
                         {"ok": 3, "scale": 1, "center": 1})

    def test_condition_table(self):
        groups = self.summary["conditions"]
        self.assertEqual(list(groups), ["反射", "斜め", "ブレ"])

        self.assertEqual(groups["反射"]["total"], 2)
        self.assertEqual(groups["反射"]["unreadable"], 1)
        self.assertEqual(groups["反射"]["within"], 1)
        self.assertEqual(groups["反射"]["errors"], [2.0])

        self.assertEqual(groups["斜め"]["total"], 2)
        self.assertEqual(groups["斜め"]["unreadable"], 1)
        self.assertEqual(groups["斜め"]["within"], 0)
        self.assertEqual(groups["斜め"]["errors"], [7.5])

        self.assertEqual(groups["ブレ"]["within"], 1)  # 5.0 は許容内（5以下）
        self.assertEqual(groups["ブレ"]["errors"], [5.0])

    def test_stage_counts_and_reasons(self):
        self.assertEqual(self.summary["stage_counts"]["scale"], 1)
        self.assertEqual(self.summary["stage_counts"]["center"], 1)
        self.assertEqual(self.summary["reason_total"], 5)
        self.assertEqual(self.summary["reason_counts"], {
            "数字の検出": 1,
            "針": 1,            # 「針の判定がずれている」は針を優先
            "目盛り(メモリ)": 1,
            "画像が粗い": 1,
            "記入なし": 1,
        })

    def test_worst_three_sorted_descending(self):
        worst = self.summary["worst"]
        self.assertEqual([item["file"] for item in worst], ["c.png", "e.png", "a.png"])
        self.assertEqual([item["error"] for item in worst], [7.5, 5.0, 2.0])
        self.assertEqual(worst[0]["condition"], "斜め")
        self.assertEqual(worst[0]["source"], "sample.csv")

    def test_markdown_has_all_sections_and_rows(self):
        text = render_markdown(self.summary, [self.path])
        for heading in ("## (a) 全体", "## (b) 条件ごと",
                        "## (c) 止まった段階ごとの件数",
                        "## (d) 「いちばんの原因」の分類",
                        "## (e) 誤差が大きい画像 ワースト3"):
            self.assertIn(heading, text)
        self.assertIn("画像の総数: 5 件", text)
        self.assertIn("| 反射 | 2 | 1 | 1 | 2.00 |", text)
        self.assertIn("| 斜め | 2 | 1 | 0 | 7.50 |", text)
        self.assertIn("| ブレ | 1 | 0 | 1 | 5.00 |", text)
        self.assertIn("| 合計 | 5 | 2 | 2 | 4.83 |", text)
        self.assertIn("許容内 (5%FS以下)", text)
        self.assertIn("| 1 | c.png | 斜め | 7.50 | sample.csv |", text)

    def test_all_reason_categories_are_printed(self):
        text = render_markdown(self.summary, [self.path])
        for label in REASON_CATEGORIES:
            self.assertIn(f"| {label} |", text)


class ValueHandlingTest(unittest.TestCase):
    def test_dash_blank_and_unreadable_are_not_numbers(self):
        for value in ("", "  ", "-", None, "—", "未検出"):
            self.assertIsNone(parse_number(value))
        self.assertEqual(parse_number(" 3.5 "), 3.5)
        self.assertEqual(parse_number("5%"), 5.0)

    def test_classify_reason_priority_and_fallbacks(self):
        self.assertEqual(classify_reason("針がメモリとずれている"), "針")
        self.assertEqual(classify_reason("数字の検出ができていない"), "数字の検出")
        self.assertEqual(classify_reason(""), "記入なし")
        self.assertEqual(classify_reason("原因が分からない"), "その他")

    def test_tolerance_is_inclusive_at_five(self):
        self.assertEqual(TOLERANCE_PERCENT_FS, 5.0)


class MissingColumnTest(unittest.TestCase):
    def test_missing_columns_do_not_crash_and_are_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_csv("ファイル名\nx.png\ny.png\n", directory, "min.csv")
            summary = summarize(load_rows([path]))
            text = render_markdown(summary, [path])

        self.assertEqual(summary["total"], 2)
        self.assertIsNone(summary["ok_count"])
        self.assertIsNone(summary["stopped_count"])
        self.assertIsNone(summary["conditions"])
        self.assertIsNone(summary["reason_counts"])
        self.assertEqual(summary["worst"], [])
        self.assertIn("「止まった段階」列がない", text)
        self.assertIn("「条件」列がない", text)
        self.assertIn("「いちばんの原因」列がない", text)
        self.assertIn("「誤差%FS」列がない", text)

    def test_missing_stage_and_error_only_skips_those_columns(self):
        text = "ファイル名,条件\nx.png,反射\n"
        with tempfile.TemporaryDirectory() as directory:
            path = write_csv(text, directory, "partial.csv")
            summary = summarize(load_rows([path]))
            markdown = render_markdown(summary, [path])

        self.assertEqual(summary["conditions"]["反射"]["total"], 1)
        self.assertIn("| 反射 | 1 |", markdown)
        self.assertNotIn("読めなかった数", markdown)
        self.assertNotIn("許容内", markdown)

    def test_reason_counts_only_rows_with_reason_column(self):
        with tempfile.TemporaryDirectory() as directory:
            with_reason = write_csv(
                "ファイル名,条件,止まった段階,いちばんの原因\n"
                "a.png,反射,ok,針がずれている\n",
                directory, "with.csv")
            without_reason = write_csv(
                "ファイル名,条件,止まった段階\n"
                "b.png,反射,ok\n",
                directory, "without.csv")
            summary = summarize(load_rows([with_reason, without_reason]))
            text = render_markdown(summary, [with_reason, without_reason])

        self.assertEqual(summary["reason_total"], 1)
        self.assertEqual(summary["reason_counts"], {"針": 1})
        self.assertIn("「いちばんの原因」列がある 1 件のみ", text)

    def test_blank_lines_are_ignored(self):
        text = "ファイル名,条件,止まった段階\n\nx.png,反射,ok\n\n"
        with tempfile.TemporaryDirectory() as directory:
            path = write_csv(text, directory, "blank.csv")
            rows = load_rows([path])
        self.assertEqual(len(rows), 1)


class MultipleFilesTest(unittest.TestCase):
    def test_files_are_combined_and_source_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            one = write_csv(
                "ファイル名,条件,止まった段階,誤差%FS\nA,反射,ok,1\n",
                directory, "one.csv")
            two = write_csv(
                "ファイル名,条件,止まった段階,誤差%FS\nB,反射,scale,-\n",
                directory, "two.csv")
            summary = summarize(load_rows([one, two]))
            text = render_markdown(summary, [one, two])

        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["conditions"]["反射"]["total"], 2)
        self.assertEqual(summary["conditions"]["反射"]["unreadable"], 1)
        self.assertIn("`one.csv`", text)
        self.assertIn("`two.csv`", text)


if __name__ == "__main__":
    unittest.main()
