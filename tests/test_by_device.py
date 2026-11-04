import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from eval.by_device import aggregate, build_rows, copy_field_set, read_database, select_field_set


def entry(**condition):
    return {
        "image": "sample.png",
        "condition": dict(blur="none", lighting="normal", camera_yaw=0,
                          camera_pitch=0, **condition),
        "degradations": {},
    }


class FieldSetTest(unittest.TestCase):
    def test_keeps_boundary_angles_and_strength(self):
        item = entry()
        item["condition"].update(camera_yaw=-30, camera_pitch=30)
        item["degradations"] = {"sensor_noise": {"strength": 0.5, "seed": 1294}}
        selected, excluded = select_field_set([item])
        self.assertEqual(selected, [item])
        self.assertEqual(excluded, [])

    def test_reports_all_reasons_and_ignores_seed(self):
        item = entry()
        item["condition"].update(blur="motion", lighting="glare", camera_yaw=31,
                                 camera_pitch=-31)
        item["degradations"] = {"glass_fog": {"strength": 0.6, "seed": 1}}
        selected, excluded = select_field_set([item])
        self.assertEqual(selected, [])
        self.assertEqual(excluded[0]["reasons"],
                         ["blur", "lighting", "camera_yaw", "camera_pitch",
                          "degradation:glass_fog"])

    def test_keeps_distractors_and_light_dirt(self):
        item = entry()
        item["distractors"] = [{"strength": 0.9}]
        item["degradations"] = {"dial_dirt": {"strength": 0.3, "seed": 1180}}
        self.assertEqual(select_field_set([item])[0], [item])

    def test_excludes_max_pointer(self):
        item = entry()
        item["appearance"] = {"max_pointer": True}
        selected, excluded = select_field_set([item])
        self.assertEqual(selected, [])
        self.assertEqual(excluded[0]["reasons"], ["max_pointer"])

    def test_copy_keeps_category_and_audits_exclusions(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "正面" / "sample.png"
            source.parent.mkdir()
            source.write_bytes(b"original")
            item = entry()
            item["image"] = str(source)
            excluded = entry()
            excluded["condition"]["blur"] = "motion"
            excluded["image"] = "missing_excluded.png"
            output = Path(directory) / "selected"
            self.assertEqual(copy_field_set([item, excluded], output), (1, 1))
            self.assertEqual((output / "正面" / "sample.png").read_bytes(), b"original")
            self.assertTrue(source.exists())
            self.assertIn("missing_excluded.png,,blur",
                          (output / "_選別結果.csv").read_text(encoding="utf-8-sig"))


class AggregationTest(unittest.TestCase):
    def truth(self, image="one.png", **kwargs):
        return dict(image=image, true_value=0, min_value=-20, max_value=80,
                    device_id="SYN-001", category="正面", **kwargs)

    def reading(self, image="one.png", **kwargs):
        raw = dict(stage="ok", min_value=-20, max_value=80)
        return dict(image_path=image, image_sha256="abc", value=2.5,
                    device_id="WRONG", device_id_source="pc_qr", status="low_confidence",
                    raw_data_json=json.dumps(raw), **kwargs)

    def test_truth_grouping_and_inclusive_tolerance_use_full_span(self):
        rows = build_rows([self.truth()], [self.reading()])
        result = aggregate(rows, {"SYN-001": {"device_name": "test"}})[0]
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["within_tolerance"], 1)
        self.assertEqual(result["mean_reference_error"], 2.5)
        self.assertEqual(result["device_id"], "SYN-001")
        self.assertFalse(rows[0]["id_correct"])

    def test_missing_and_failed_readings_stay_in_denominator(self):
        truths = [self.truth(), self.truth("two.png"), self.truth("three.png")]
        failed = self.reading("two.png")
        failed.update(value=None, raw_data_json=json.dumps(dict(stage="scale")))
        rows = build_rows(truths, [self.reading(), failed])
        result = aggregate(rows, {})[0]
        self.assertEqual(result["total"], 3)
        self.assertAlmostEqual(result["within_percent"], 100 / 3)
        self.assertEqual(result["read_ok"], 1)
        self.assertEqual(result["scale_unavailable"], 2)
        self.assertEqual(result["mean_reference_error"], 2.5)

    def test_incorrect_range_and_median_maximum(self):
        first = self.reading()
        second = self.reading("two.png")
        second.update(value=10, raw_data_json=json.dumps(dict(stage="ok", min_value=0, max_value=80)))
        rows = build_rows([self.truth(), self.truth("two.png")], [first, second])
        result = aggregate(rows, {})[0]
        self.assertEqual(result["scale_wrong"], 1)
        self.assertEqual(result["median_reference_error"], 6.25)
        self.assertEqual(result["max_reference_error"], 10)

    def test_hash_join_uses_imported_qr_image_not_original_hash(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "one.png"
            source.write_bytes(b"QR-image")
            reading = self.reading("stored/hash.png")
            reading["image_sha256"] = hashlib.sha256(b"QR-image").hexdigest()
            rows = build_rows([self.truth("original/one.png")], [reading], directory)
            self.assertEqual(rows[0]["stage"], "ok")

    def test_duplicate_readings_are_rejected(self):
        with self.assertRaises(ValueError):
            build_rows([self.truth()], [self.reading(), self.reading()])

    def test_read_database_is_read_only_and_does_not_create_missing_db(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "evaluation.db"
            with self.assertRaises(sqlite3.OperationalError):
                read_database(db)
            self.assertFalse(db.exists())
            with sqlite3.connect(db) as connection:
                connection.execute("CREATE TABLE meter_readings (value REAL)")
                connection.execute("INSERT INTO meter_readings VALUES (2.5)")
            connection.close()
            before = db.read_bytes()
            self.assertEqual(read_database(db), [{"value": 2.5}])
            self.assertEqual(db.read_bytes(), before)

    def test_all_failures_have_no_numeric_error_and_zero_success(self):
        result = aggregate(build_rows([self.truth()], []), {})[0]
        self.assertEqual(result["within_percent"], 0)
        self.assertIsNone(result["mean_reference_error"])
        self.assertIsNone(result["median_reference_error"])
        self.assertIsNone(result["max_reference_error"])


if __name__ == "__main__":
    unittest.main()
