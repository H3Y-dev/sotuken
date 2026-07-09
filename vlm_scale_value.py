"""
Ollama経由のQwen3-VLに「このメーターの最小値・最大値は何か」だけを尋ねるモジュール。

以前の実装ではVLMに座標（クロック位置やピクセル座標）まで答えさせていたが、
VLMは画像全体を見た意味理解（盤面に書かれた数字が何か）は得意な一方、
精密な位置推定は苦手なことが分かっている。そのため、ここでは値の意味理解だけを
VLMに任せ、実際の位置はOCR＋目盛り線検出（scale_value_detect / tick_detect）側で
特定する役割分担にしている。
"""

import base64
import io
import json
import re

import cv2
from PIL import Image

MODEL_NAME = 'qwen3-vl:8b'


def read_min_max(img):
    """
    メーター画像から最小値・最大値をVLMに問い合わせる。
    失敗時（Ollama未起動、応答不正など）はNoneを返す。
    """
    try:
        import ollama

        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        max_side = 512
        if max(h, w) > max_side:
            scale = max_side / max(h, w)
            rgb = cv2.resize(rgb, (int(w * scale), int(h * scale)))

        buf = io.BytesIO()
        Image.fromarray(rgb).save(buf, format='JPEG', quality=85)
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        prompt = (
            "Look at this analog meter image. "
            "What is the minimum labeled value and the maximum labeled value on its scale? "
            "Respond with JSON only, no explanation:\n"
            '{"min_value": <number>, "max_value": <number>}'
        )

        # Qwen3-VLは思考モデルで、回答前に内部推論トークンを消費する
        # （think=Falseでもゼロにはならない）。num_predictが小さいと
        # 推論だけで使い切り、肝心のJSON本文が空になってしまうため、
        # 余裕を持たせている。
        res = ollama.chat(
            model=MODEL_NAME,
            messages=[{
                'role': 'user',
                'content': prompt,
                'images': [img_b64],
            }],
            think=False,
            options={'num_predict': 200}
        )

        match = re.search(r'\{.*?\}', res.message.content, re.DOTALL)
        if not match:
            return None
        data = json.loads(match.group())
        if not all(k in data for k in ('min_value', 'max_value')):
            return None

        min_value = float(data['min_value'])
        max_value = float(data['max_value'])
        if min_value == max_value:
            return None
        return (min_value, max_value)

    except Exception:
        return None


def detect_meter_bbox(img):
    """
    画像中のアナログメーター盤面のおおまかな矩形領域をVLMに問い合わせる。

    「精密な1点の位置」ではなく「盤面を過不足なく含む大まかな矩形」を
    答えさせるタスクなので、VLMの精密な位置推定が苦手という弱点の
    影響を受けにくい（多少ズレてもクロップ時に余白を持たせれば吸収できる）。
    背景の模様・文字・他の物体が中心検出や目盛り検出を誤らせることがあるため、
    このbboxで画像をクロップしてから以降の処理を行う目的で使う。

    戻り値: (x0, y0, x1, y1) を画像幅/高さに対する0.0-1.0の正規化座標で返す。
    失敗時、または矩形が極端に小さい/画像全体に近い場合はNoneを返す。
    """
    try:
        import ollama

        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        max_side = 512
        if max(h, w) > max_side:
            scale = max_side / max(h, w)
            rgb = cv2.resize(rgb, (int(w * scale), int(h * scale)))

        buf = io.BytesIO()
        Image.fromarray(rgb).save(buf, format='JPEG', quality=85)
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        prompt = (
            "Look at this image. It contains an analog gauge/meter "
            "(a circular or arc-shaped dial with a needle and a numbered scale). "
            "Find the bounding box that tightly contains the entire gauge face "
            "(the dial, its numbers, and its outer rim/bezel), excluding "
            "surrounding background. "
            "Respond with JSON only, no explanation:\n"
            '{"x0": <left>, "y0": <top>, "x1": <right>, "y1": <bottom>}\n'
            "All values are fractions of image width/height in range 0.0-1.0."
        )

        res = ollama.chat(
            model=MODEL_NAME,
            messages=[{
                'role': 'user',
                'content': prompt,
                'images': [img_b64],
            }],
            think=False,
            options={'num_predict': 200}
        )

        match = re.search(r'\{.*?\}', res.message.content, re.DOTALL)
        if not match:
            return None
        data = json.loads(match.group())
        if not all(k in data for k in ('x0', 'y0', 'x1', 'y1')):
            return None

        x0, y0, x1, y1 = (float(data[k]) for k in ('x0', 'y0', 'x1', 'y1'))
        if not all(0.0 <= v <= 1.0 for v in (x0, y0, x1, y1)):
            return None
        if x1 <= x0 or y1 <= y0:
            return None

        # 極端に小さい、または画像全体に近い（=検出できていない）矩形は信頼しない
        area = (x1 - x0) * (y1 - y0)
        if area < 0.05 or area > 0.98:
            return None

        return (x0, y0, x1, y1)

    except Exception:
        return None


def read_min_max_with_positions(img):
    """
    最小値・最大値に加えて、その目盛り線の位置（正規化座標）もVLMに問い合わせる。

    これはOCR＋目盛り線対応付け方式との精度比較のために用意したもので、
    通常の運用では read_min_max() ＋ scale_value_detect側の位置特定を使う方針。
    モジュールdocstringの通り、VLMは精密な位置推定が苦手なことが分かっているため、
    ここで得られる座標をそのまま本番の位置決めに使うことは推奨しない。

    失敗時はNoneを返す。
    戻り値: {'zero_pt': (x, y), 'full_pt': (x, y), 'min_value': float, 'max_value': float}
    """
    try:
        import ollama

        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        max_side = 512
        if max(h, w) > max_side:
            scale = max_side / max(h, w)
            rgb = cv2.resize(rgb, (int(w * scale), int(h * scale)))

        buf = io.BytesIO()
        Image.fromarray(rgb).save(buf, format='JPEG', quality=85)
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        prompt = (
            "Look at this analog meter image. "
            "Find the exact tick mark for the minimum (zero) value and the exact tick "
            "mark for the maximum (full-scale) value. "
            "Respond with JSON only, no explanation:\n"
            "{\n"
            '  "min_value": <minimum scale number>,\n'
            '  "max_value": <maximum scale number>,\n'
            '  "zero_point": [<x>, <y>],\n'
            '  "full_point": [<x>, <y>]\n'
            "}\n"
            "x and y are the position of the tick mark itself (not the number label), "
            "as fractions of image width/height in range 0.0-1.0. "
            "x=0.0 is the left edge, x=1.0 is the right edge, "
            "y=0.0 is the top edge, y=1.0 is the bottom edge."
        )

        res = ollama.chat(
            model=MODEL_NAME,
            messages=[{
                'role': 'user',
                'content': prompt,
                'images': [img_b64],
            }],
            think=False,
            options={'num_predict': 250}
        )

        match = re.search(r'\{.*?\}', res.message.content, re.DOTALL)
        if not match:
            return None
        data = json.loads(match.group())
        if not all(k in data for k in ('min_value', 'max_value', 'zero_point', 'full_point')):
            return None

        min_value = float(data['min_value'])
        max_value = float(data['max_value'])
        if min_value == max_value:
            return None

        zx, zy = float(data['zero_point'][0]), float(data['zero_point'][1])
        fx, fy = float(data['full_point'][0]), float(data['full_point'][1])
        if not all(0.0 <= v <= 1.0 for v in (zx, zy, fx, fy)):
            return None

        orig_h, orig_w = img.shape[:2]
        zero_pt = (int(round(zx * (orig_w - 1))), int(round(zy * (orig_h - 1))))
        full_pt = (int(round(fx * (orig_w - 1))), int(round(fy * (orig_h - 1))))

        return {
            'zero_pt': zero_pt,
            'full_pt': full_pt,
            'min_value': min_value,
            'max_value': max_value,
        }

    except Exception:
        return None
