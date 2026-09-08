import os
from typing import Any, Dict, Optional
import cv2
import numpy as np

import meter_pipeline


def execute_pipeline(image_path: str, use_vlm: bool = False) -> Dict[str, Any]:
    """
    画像ファイルパスを受け取り、meter_pipeline.read_meter を実行して結果を返す。
    日本語パス等に対応するため cv2.imdecode を使用。
    ファイルが存在しない場合や画像として読み込めない場合は failure 情報を返す。
    """
    if not os.path.exists(image_path):
        return {
            "stage": "image_not_found",
            "value": None,
            "error": f"Image file not found: {image_path}",
        }

    try:
        # Windowsの日本語パス対応
        img = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception as e:
        return {
            "stage": "image_unreadable",
            "value": None,
            "error": f"Failed to decode image: {str(e)}",
        }

    if img is None:
        return {
            "stage": "image_unreadable",
            "value": None,
            "error": "cv2.imdecode returned None",
        }

    try:
        result = meter_pipeline.read_meter(img, use_vlm=use_vlm)
        return result
    except Exception as e:
        return {
            "stage": "pipeline_error",
            "value": None,
            "error": str(e),
        }
