"""
VLM（Ollama + Qwen3-VL）まわりの動作を診断するスクリプト。

main_sotuken.pyの通常のコードは失敗理由を問わず一律Noneを返す設計のため、
実際に何が起きているか（例外の中身）が画面から分からない。
このスクリプトは例外を握りつぶさずそのまま表示するので、
「アプリからの自動スナップだけ失敗する」原因の切り分けに使う。

使い方:
    python diagnose_vlm.py <画像ファイルパス>
"""

import sys
import time

import cv2
import numpy as np


def main():
    if len(sys.argv) < 2:
        print("使い方: python diagnose_vlm.py <画像ファイルパス>")
        return

    path = sys.argv[1]

    print("=== 1. ollamaパッケージのインポート確認 ===")
    try:
        import ollama
        print("OK: ollamaパッケージが見つかりました")
    except ImportError as e:
        print(f"NG: ollamaパッケージが見つかりません: {e}")
        return

    print("\n=== 2. Ollamaサーバーへの接続・モデル確認 ===")
    import vlm_scale_value
    available, reason = vlm_scale_value.check_availability()
    if available:
        print(f"OK: Ollamaサーバーに接続でき、{vlm_scale_value.MODEL_NAME}も取得済みです")
    else:
        print(f"NG: {reason}")
        return

    print("\n=== 3. 画像の読み込み ===")
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print(f"NG: 画像を読み込めませんでした: {path}")
        return
    print(f"OK: 画像サイズ {img.shape[1]}x{img.shape[0]}")

    print("\n=== 4. read_min_max()（アプリが実際に使う関数）を試行 ===")
    t0 = time.time()
    result = vlm_scale_value.read_min_max(img)
    elapsed = time.time() - t0
    print(f"結果: {result}  （{elapsed:.1f}秒）")
    if result is None:
        print("NG: read_min_max()がNoneを返しました。例外が握りつぶされているため、")
        print("     次のステップで生のollama.chat()呼び出しを行い、詳細を確認します。")
    else:
        print("OK: 正常に動作しました。ここまでは問題ありません。")
        return

    print("\n=== 5. 生のollama.chat()呼び出し（詳細なエラーを見るため） ===")
    import base64
    import io
    from PIL import Image

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

    t0 = time.time()
    res = ollama.chat(
        model=vlm_scale_value.MODEL_NAME,
        messages=[{'role': 'user', 'content': prompt, 'images': [img_b64]}],
        think=False,
        options={'num_predict': 200},
    )
    elapsed = time.time() - t0
    print(f"（{elapsed:.1f}秒）")
    print("content:", repr(res.message.content))
    print("thinking:", repr(getattr(res.message, 'thinking', None)))


if __name__ == "__main__":
    main()
