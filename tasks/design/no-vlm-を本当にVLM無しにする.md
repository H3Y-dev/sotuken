# `--no-vlm` を本当に「VLMを使わない」にする

作成: 2026-08-26 ／ 設計: 本人 ／ 実装: Codexへ委任

## 何が問題か

**同じ画像を同じコードで処理しているのに、結果が実行ごとに変わる。**

`気密試験_昇圧後圧力計.jpg` を `read_meter(img, use_vlm=False)` で4回続けて処理した実測:

```
1回目: range=0.0-108.0  value=108.00
2回目: range=0.0-150.0  value=98.41
3回目: range=0.0-150.0  value=98.41
4回目: range=0.0-150.0  value=98.41
```

OCR（`read_scale_numbers`）は4回とも同じ値を返しており、**OCRは決定的**。
揺れているのは `read_meter` の中である。

## 原因

`use_vlm=False` は**盤面クロップのVLM呼び出しだけ**を飛ばしている。
`read_meter` のdocstring自身がそう書いている。

> なお目盛り数値の読み取り側（scale_value_detect）は、OCRの信頼度が低い場合に
> 内部でVLMを呼ぶため、こちらでは制御しない。

そのため `--no-vlm` を付けても、`scale_value_detect` の中から Ollama への
問い合わせが毎回飛ぶ。Ollamaはモデルが未ロードだと初回だけ応答に失敗するため、
**1回目と2回目以降で結果が変わる。**

### なぜ深刻か

`--no-vlm` は「決定的にA/B比較するための条件」として使ってきた。
その前提が成り立っていなかったので、**これまでの改善前後の数値比較は、
アルゴリズムの差ではなくOllamaの機嫌の差を測っていた可能性がある。**

2026-08-26のセッションで、`evaluate.py` と `tools_render_overlays.py` が
同じ画像に対して違う結果（範囲 0-108 と 0-150）を出したことで発覚した。

## 残っているVLM呼び出し箇所

| ファイル | 行 | 呼び出し | 現状 |
|---|---|---|---|
| `meter_pipeline.py` | 99 | `detect_meter_bbox` | `use_vlm` で制御済み |
| `scale_value_detect.py` | 922 | `read_min_max` | **制御されていない** |
| `scale_value_detect.py` | 553 | `check_needle_overlaps_zero` | **制御されていない** |

## 変更内容

### 1. `detect_scale_values` に `use_vlm` を足す

```python
def detect_scale_values(img, ticks, center, max_angle_deg=12.0, min_points=3,
                        use_vlm=True):
```

- `use_vlm=False` のとき、`vlm_scale_value.read_min_max(img)` を**呼ばず**に
  `vlm_result = None` とする。
- `use_vlm=False` のとき、`_make_occlusion_check(img)` が返す関数が
  VLMを呼ばないようにする。`_make_occlusion_check(img, use_vlm=True)` に変え、
  `False` なら常に `False` を返す関数を返す。呼び出し箇所も合わせる。
- **デフォルトは `True`。** 既存の呼び出し側（`diagnose_pipeline.py`,
  `main_sotuken.py`）は変更しない。

### 2. `read_meter` が渡す

`meter_pipeline.py` の
`scale_value_detect.detect_scale_values(img, ticks, center)` を
`scale_value_detect.detect_scale_values(img, ticks, center, use_vlm=use_vlm)` にする。

### 3. `read_meter` のdocstringを直す

「こちらでは制御しない」の一文を消し、
**「`False` にするとVLMを使う処理をすべて飛ばす。測定を再現可能にしたいときは
必ず `False` にする」**の主旨に書き換える。
なぜそうしたのか（上記の非決定性）が後から分かるように理由も1〜2文で残す。

### 4. 回帰テストを足す

`use_vlm=False` で同じ画像を2回読んで結果が一致することを確かめる。

- 画像は **git管理下の `eval/images/meter1.png`** を使う。
- **企業提供画像（`C:\卒研\images\` 配下）は絶対に使わない。**
- 比較するキー: `stage`, `n_ticks`, `min_value`, `max_value`, `value`
- 既存テストと同じ `unittest` の書き方に合わせる。

## 完了条件

- `venv\Scripts\python.exe -m unittest discover -s tests -q` が全て通る
- 上記の回帰テストが追加されている
- `read_meter(img, use_vlm=False)` を4回繰り返して結果が全て一致する

## 制約

- 企業提供画像をリポジトリにコミットしない（`tasks/企業提供画像の取り扱い.md`）
- 上記以外の公開関数のシグネチャを変えない
