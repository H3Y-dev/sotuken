"""
目盛り検出〜0/フルスケール自動判定までの全工程を1段階ずつ確認する診断スクリプト。

diagnose_vlm.pyでVLM単体は正常と分かったが、それでも自動スナップが
完全手動にフォールバックする場合に使う。VLMが値を答えられても、
目盛り線検出やOCRが弱いと「値は分かるが位置が特定できない」状態になり、
結局失敗することがあるため、各段階の検出数を可視化する。

使い方:
    python diagnose_pipeline.py <画像ファイルパス>
"""

import sys

import cv2
import numpy as np

import tick_detect
import scale_value_detect
import vlm_scale_value


def main():
    if len(sys.argv) < 2:
        print("使い方: python diagnose_pipeline.py <画像ファイルパス>")
        return

    path = sys.argv[1]
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print(f"NG: 画像を読み込めませんでした: {path}")
        return
    print(f"画像サイズ: {img.shape[1]}x{img.shape[0]}\n")

    print("=== 1. 中心点検出 ===")
    candidate = tick_detect.auto_detect_center(img)
    if candidate is not None:
        center = (candidate[0], candidate[1])
        print(f"OK (Hough円検出): center={center}")
    else:
        est = tick_detect.estimate_center_from_ticks(img)
        if est is not None:
            center = est
            print(f"OK (目盛りからの推定): center={center}")
        else:
            center = (img.shape[1] // 2, img.shape[0] // 2)
            print(f"NG: 円検出・推定とも失敗。画像中心を仮に使用: center={center}")

    print("\n=== 2. 目盛り線検出（CLAHE適用後） ===")
    enhanced = tick_detect.apply_clahe(img, clip_limit=2.0)
    ticks = tick_detect.detect_scale_ticks(enhanced, center)
    n_major = sum(t['is_major'] for t in ticks)
    print(f"検出数: {len(ticks)}本（うち主目盛り: {n_major}本）")
    if len(ticks) < 3:
        print("NG: 3本未満だと中心の再推定・数字との対応付けがほぼ機能しません")

    if len(ticks) >= 3:
        refined = tick_detect.refine_center_from_ticks(ticks, center, img.shape)
        if refined is not None:
            print(f"中心点を再推定: {center} -> {refined}")
            center = refined
        else:
            print("中心点の再推定は行われませんでした（変化が大きすぎたため棄却）")

    print("\n=== 3. OCRでの数字読み取り ===")
    numbers = scale_value_detect.read_scale_numbers(img)
    values = sorted({n['value'] for n in numbers})
    print(f"検出数: {len(numbers)}件、異なる値: {values}")
    if len(values) < 3:
        print("NG: OCRが読めた数字が少なすぎます（3種未満）")

    print("\n=== 4. 数字と目盛り線の対応付け ===")
    bound = scale_value_detect.bind_numbers_to_ticks(numbers, ticks, center)
    print(f"対応付け成功: {len(bound)}件")
    for b in sorted(bound, key=lambda b: b['angle']):
        print(f"    value={b['value']}")
    if len(bound) < 3:
        print("NG: 3件未満だとOCR+目盛り方式でのmin/max判定ができません"
              "（角度のズレで対応付けが弾かれている可能性）")

    print("\n=== 5. OCR+目盛り方式でのmin/max判定 ===")
    n_ocr_unique = len({n['value'] for n in numbers})
    result = scale_value_detect.determine_min_max(bound, n_ocr_unique=n_ocr_unique)
    print(f"結果: {result}")

    print("\n=== 6. VLMでのmin/max取得 ===")
    vlm_result = vlm_scale_value.read_min_max(img)
    print(f"結果: {vlm_result}")

    if vlm_result is not None:
        print("\n=== 7. VLMが答えた値の位置特定を試行 ===")
        min_value, max_value = vlm_result
        for label, target in [('min', min_value), ('max', max_value)]:
            pt = scale_value_detect.locate_value_on_ticks(numbers, ticks, center, target)
            source = "OCR数字から直接" if pt is not None else None
            if pt is None:
                pt = scale_value_detect.locate_value_by_extrapolation(bound, ticks, target)
                if pt is not None:
                    verified = scale_value_detect._verify_label_near_position(img, pt, target)
                    source = f"等間隔性からの推定（ローカル再OCR検証: {'成功' if verified else '失敗'}）"
                    if not verified:
                        pt = None
            print(f"  {label}={target}: pt={pt}  経路={source}")

    print("\n=== 8. 最終結果（アプリが実際に使う関数） ===")
    final = scale_value_detect.detect_scale_values(img, ticks, center)
    print(f"結果: {final}")
    if final is None:
        print("→ この画像では完全手動フォールバックになります。上記のどの段階で"
              "件数が少なくなっているかを確認してください。")


if __name__ == "__main__":
    main()
