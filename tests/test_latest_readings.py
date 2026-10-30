import codecs
import csv
import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import chdir
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from manager.export import export_inspection_csv, latest_per_device
from manager.storage import MeterReading, Storage


def reading(row_id, name="圧力計", timestamp="2026-10-30T10:00:00", status="ok", value=12.5):
    return dict(id=row_id, device_name=name, timestamp=timestamp, status=status,
                value=value, image_path=f"images/{row_id}.jpg")


class LatestReadingsTest(unittest.TestCase):
    def test_latest_per_device_and_input_unchanged(self):
        rows = [reading(1), reading(2, timestamp="2026-10-30T11:00:00"), reading(3, "温度計")]
        self.assertEqual([r["id"] for r in latest_per_device(rows)], [2, 3])
        self.assertNotIn("display_name", rows[0])

    def test_same_timestamp_uses_larger_id(self):
        self.assertEqual(latest_per_device([reading(5), reading(2)])[0]["id"], 5)

    def test_unnamed_records_are_separate_and_require_review(self):
        rows = [reading(i, name) for i, name in enumerate([None, "", "  ", "unknown"])]
        rows.append(reading(5, "unknown", status="failed", value=None))
        result = latest_per_device(rows)
        self.assertEqual(len(result), 5)
        self.assertTrue(all(r["display_name"] == "名前なし" for r in result))
        self.assertEqual([r["status_label"] for r in result], ["失敗"] + ["要確認"] * 4)

    def test_status_then_newest_order_and_unknown_status(self):
        rows = [reading(1, "A"), reading(2, "B", status="failed"),
                reading(3, "C", status="low_confidence"), reading(4, "D", status=None),
                reading(5, "E", timestamp="2026-10-30T11:00:00", status="unexpected")]
        self.assertEqual([r["id"] for r in latest_per_device(rows)], [2, 5, 3, 4, 1])

    def test_none_value_and_storage_records(self):
        record = MeterReading("圧力計", None, "needle", "image.jpg", id=3,
                              timestamp="2026-10-30T10:00:00", status="failed")
        result = latest_per_device([record])[0]
        self.assertIsNone(result["value"])
        self.assertEqual(result["status_label"], "失敗")
        self.assertEqual(latest_per_device([]), [])


class InspectionCsvTest(unittest.TestCase):
    def test_documents_lookup_returns_absolute_path(self):
        from manager.export import _documents_dir
        self.assertTrue(_documents_dir().is_absolute())

    def test_bom_columns_crlf_quoting_formula_and_collision(self):
        rows = latest_per_device([
            reading(1, '=SUM(1,2)', value=-2.5),
            reading(2, '+name', status="failed", value=None),
            dict(reading(3, '-name'), image_path='@image,"quoted".jpg'),
            reading(4, '@name'),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime(2026, 10, 30, 12, 34, 56)
            paths = [Path(export_inspection_csv(rows, tmp, now)) for _ in range(3)]
            self.assertEqual([p.name for p in paths], ["点検_20261030_123456.csv",
                             "点検_20261030_123456_2.csv", "点検_20261030_123456_3.csv"])
            data = paths[0].read_bytes()
            self.assertTrue(data.startswith(codecs.BOM_UTF8))
            self.assertNotIn(b"\n", data.replace(b"\r\n", b""))
            table = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
            self.assertEqual(table[0], ["メーター名称", "読み取り値", "状態", "取込時刻", "画像参照"])
            self.assertEqual(table[1][0:3], ["'+name", "", "失敗"])
            self.assertEqual(table[2][0:2], ["'=SUM(1,2)", "-2.5"])
            self.assertEqual(table[3][4], "'@image,\"quoted\".jpg")
            self.assertTrue(all(p.read_bytes() == data for p in paths))

    def test_creates_directory_and_uses_default_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("manager.export._documents_dir", return_value=Path(tmp)):
                path = Path(export_inspection_csv([]))
            self.assertEqual(path.parent, Path(tmp) / "メーター点検")
            self.assertTrue(path.is_file())

    def test_failed_replace_removes_temporary_file_and_keeps_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime(2026, 10, 30)
            existing = Path(export_inspection_csv([], tmp, now))
            original = existing.read_bytes()
            with patch("manager.export.os.replace", side_effect=OSError("write failed")):
                with self.assertRaisesRegex(OSError, "write failed"):
                    export_inspection_csv([], tmp, now)
            self.assertEqual(list(Path(tmp).iterdir()), [existing])
            self.assertEqual(existing.read_bytes(), original)

    def test_failed_write_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("manager.export.csv.writer", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    export_inspection_csv([], tmp)
            self.assertEqual(list(Path(tmp).iterdir()), [])


class LatestReadingsAppTest(unittest.TestCase):
    def setUp(self):
        from streamlit import cache_data, cache_resource
        cache_data.clear()
        cache_resource.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "manager.db"
        self.out = self.root / "exports"
        self.storage = Storage(str(self.db))
        for row in self.sample_rows():
            self.add_record(row)
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        from streamlit.testing.v1 import AppTest
        self.at = AppTest.from_file(str(app_path), default_timeout=30)
        self.addCleanup(cache_data.clear)
        self.addCleanup(cache_resource.clear)

    @staticmethod
    def sample_rows():
        return [reading(1, "圧力計A", value=10), reading(2, "圧力計A", "2026-10-30T11:00:00", value=11),
                reading(3, "温度計B", value=20), reading(4, "温度計B", "2026-10-30T11:10:00", value=21),
                reading(5, "流量計C", value=30), reading(6, "流量計C", "2026-10-30T11:20:00", "low_confidence", 31),
                reading(7, "", "2026-10-30T11:30:00", value=40),
                reading(8, "unknown", "2026-10-30T11:40:00", value=41),
                reading(9, "故障計", "2026-10-30T11:50:00", "failed", None),
                reading(10, "圧力計A", "2026-10-30T09:00:00", value=9)]

    def add_record(self, row):
        record_id = self.storage.save_reading(row["device_name"], row["image_path"],
            dict(value=row["value"], stage="ok" if row["value"] is not None else "needle", status=row["status"]))
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE meter_readings SET timestamp = ? WHERE id = ?", (row["timestamp"], record_id))

    def run_app(self, button=None):
        with chdir(self.root), \
             patch("manager.receiver.init_receiver_for_app", return_value=dict(running=False, error="test", url="test", token="test")), \
             patch("manager.export._documents_dir", return_value=self.out):
            (button.click() if button else self.at).run()
        self.assertEqual(len(self.at.exception), 0, str(self.at.exception))
        return self.at

    def test_latest_table_export_and_cache_refresh(self):
        at = self.run_app()
        self.assertIn("各メーターの最新の読み取り", [h.value for h in at.header])
        table = at.dataframe[0].value
        self.assertEqual(list(table.columns), ["メーター名", "読み取り値", "時刻", "状態"])
        self.assertEqual(table["メーター名"].tolist(), ["故障計", "名前なし", "名前なし", "流量計C", "温度計B", "圧力計A"])
        self.assertEqual(table["読み取り値"].tolist(), ["-", "41.0", "40.0", "31.0", "21.0", "11.0"])
        self.assertEqual(at.expander[0].label, "全履歴")
        self.assertIn("要確認 3件・失敗 1件・名前なし 2件", [c.value for c in at.caption])
        self.assertTrue(at.dataframe[0].proto.styler.styles)
        button = next(b for b in at.button if b.label == "点検の結果を書き出す")
        self.run_app(button)
        files = list((self.out / "メーター点検").glob("*.csv"))
        self.assertEqual(len(files), 1)
        self.assertEqual(len(list(csv.reader(io.StringIO(files[0].read_text(encoding="utf-8-sig"))))), 7)
        old_mtime = self.db.stat().st_mtime
        self.add_record(reading(11, "圧力計A", "2026-10-30T12:00:00", value=99))
        os.utime(self.db, (old_mtime + 1, old_mtime + 1))
        self.run_app()
        updated = at.dataframe[0].value
        self.assertEqual(updated[updated["メーター名"] == "圧力計A"]["読み取り値"].iloc[0], "99.0")

    def test_filters_apply_to_latest_and_history_and_empty_result(self):
        at = self.run_app()
        at.selectbox[0].select("圧力計A")
        self.run_app()
        self.assertEqual(at.dataframe[0].value["メーター名"].tolist(), ["圧力計A"])
        self.assertEqual(len(at.dataframe[1].value), 3)
        at.date_input[0].set_value(date(2026, 10, 31))
        self.run_app()
        self.assertEqual(len(at.dataframe[0].value), 0)
        self.assertIn("表示できる記録がありません。", [i.value for i in at.info])

    def test_display_limit_does_not_truncate_export(self):
        for i in range(11, 66):
            self.add_record(reading(i, f"機器{i}", value=123456.789101))
        at = self.run_app()
        self.assertEqual(len(at.dataframe[0].value), 50)
        self.assertIn("123456.789101", at.dataframe[0].value["読み取り値"].tolist())
        self.assertIn("ほか11件は全履歴で確認できます", [c.value for c in at.caption])
        self.run_app(next(b for b in at.button if b.label == "点検の結果を書き出す"))
        exported = next((self.out / "メーター点検").glob("*.csv"))
        self.assertEqual(len(list(csv.reader(io.StringIO(exported.read_text(encoding="utf-8-sig"))))), 62)

    def test_export_failure_is_visible_and_folder_failure_is_silent(self):
        at = self.run_app()
        with patch("manager.export.export_inspection_csv", side_effect=OSError("disk full")):
            self.run_app(next(b for b in at.button if b.label == "点検の結果を書き出す"))
        self.assertTrue(any("disk full" in error.value for error in at.error))
        self.run_app(next(b for b in at.button if b.label == "点検の結果を書き出す"))
        if os.name == "nt":
            with patch("os.startfile", side_effect=OSError("folder unavailable")) as open_folder:
                self.run_app(next(b for b in at.button if b.label == "フォルダを開く"))
            open_folder.assert_called_once_with(str(self.out / "メーター点検"))
            self.assertFalse(any("folder unavailable" in error.value for error in at.error))


if __name__ == "__main__":
    unittest.main()
