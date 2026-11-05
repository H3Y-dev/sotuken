import unittest
from unittest.mock import patch

import cv2
import numpy as np
import qrcode

import scale_value_detect as scale


class TestQrOcrMask(unittest.TestCase):
    def test_non_images_are_left_unchanged(self):
        for image in (None, object(), np.empty((0, 0, 3), np.uint8)):
            self.assertIs(image, scale._mask_qr_for_ocr(image))

    def test_existing_scale_result_is_preserved_without_masking(self):
        image = np.zeros((200, 200, 3), np.uint8)
        result = {'min_value': 0, 'max_value': 100}
        with patch.object(scale, '_detect_scale_values', return_value=result), \
                patch.object(scale, '_mask_qr_for_ocr') as mask:
            self.assertIs(result, scale.detect_scale_values(image, [], (100, 100), use_vlm=False))
        mask.assert_not_called()

    def test_failed_scale_retries_masked_pixels_in_same_coordinates(self):
        image = np.zeros((200, 200, 3), np.uint8)
        masked = np.full_like(image, 220)
        ticks = [{'centroid': (100, 20)}]
        result = {'min_value': 0, 'max_value': 100}
        received = []

        def detect(img, input_ticks, center, *args, **kwargs):
            self.assertIs(ticks, input_ticks)
            self.assertEqual((100, 100), center)
            received.append(img)
            return result if img is masked else None

        with patch.object(scale, '_detect_scale_values', side_effect=detect), \
                patch.object(scale, '_mask_qr_for_ocr', return_value=masked), \
                patch.object(scale, 'read_scale_numbers', return_value=[]), \
                patch.object(scale, '_is_consistent_recovery', return_value=True):
            self.assertIs(result, scale.detect_scale_values(image, ticks, (100, 100), use_vlm=False))
        self.assertEqual(2, len(received))

    def test_rejects_retry_that_does_not_fit_the_number_grid(self):
        image = np.zeros((200, 200, 3), np.uint8)
        diagnostics = {}
        points = {}

        def detect(img, *args, diagnostics_out=None, numbered_points_out=None, **kwargs):
            if img is image:
                diagnostics_out.update(decision='unidentified')
                return None
            diagnostics_out.update(decision='unsafe range')
            numbered_points_out.update(bound=['unsafe'])
            return {'min_value': 150, 'max_value': 250}

        with patch.object(scale, '_detect_scale_values', side_effect=detect), \
                patch.object(scale, '_mask_qr_for_ocr', return_value=image.copy()), \
                patch.object(scale, 'read_scale_numbers', return_value=[]), \
                patch.object(scale, '_is_consistent_recovery', return_value=False):
            self.assertIsNone(scale.detect_scale_values(
                image, [], (100, 100), use_vlm=False,
                diagnostics_out=diagnostics, numbered_points_out=points))
        self.assertEqual({'decision': 'unidentified'}, diagnostics)
        self.assertEqual({}, points)

    def test_masks_board_without_changing_dial_or_source(self):
        image = np.full((500, 700, 3), 220, np.uint8)
        cv2.circle(image, (240, 250), 190, (245, 245, 245), -1)
        cv2.putText(image, '50', (310, 160), cv2.FONT_HERSHEY_SIMPLEX,
                    1, (0, 0, 0), 2)
        qr = np.array(qrcode.make('meter-id-123').convert('RGB'))
        qr = cv2.resize(qr, (120, 120), interpolation=cv2.INTER_NEAREST)
        image[320:480, 520:680] = 255
        image[330:450, 540:660] = qr
        cv2.putText(image, '123', (565, 470), cv2.FONT_HERSHEY_SIMPLEX,
                    .4, (0, 0, 0), 1)
        original = image.copy()
        masked = scale._mask_qr_for_ocr(image)
        np.testing.assert_array_equal(original, image)
        np.testing.assert_array_equal(original[:, :500], masked[:, :500])
        self.assertTrue(np.all(masked[320:480, 520:680] == 220))

    def test_no_qr_keeps_image_unchanged(self):
        image = np.full((300, 400, 3), 230, np.uint8)
        cv2.rectangle(image, (280, 180), (380, 280), (255, 255, 255), -1)
        cv2.putText(image, '50', (100, 100), cv2.FONT_HERSHEY_SIMPLEX,
                    1, (0, 0, 0), 2)
        self.assertIs(image, scale._mask_qr_for_ocr(image))


if __name__ == '__main__':
    unittest.main()
