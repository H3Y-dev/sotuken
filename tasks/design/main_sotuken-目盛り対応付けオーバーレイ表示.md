# main_sotuken.py: 目盛り対応付けオーバーレイ表示の修正・追加

作成: 2026-08-27 ／ 担当: 本人（設計） → Codex（実装）

## 経緯

本人より（2026-08-27）:
> 「main_sotukenを実行した際に今までの変更点が適用されていないように見えた」
> 「目盛り対応付けオーバーレイ表示をmain_sotukenを実行した際にも確認できるようにしてほしい」

調査したところ、T1-6の修正自体（`scale_value_detect.py`）は正しく効いている
（`main_sotuken.py`もこのモジュールをimportして使っているので、実行時には
最新のロジックが動く）。**「変わって見えない」原因は、GUIのオーバーレイ表示が
実際に判定へ使われた目盛り分類とは別の、古い・粗いticks情報を描画しているため**
と判明した。これはT1-6の副作用ではなく、以前から存在するGUI側の表示バグ。

## 原因（実測で確認済み）

`main_sotuken.py` の `_on_ticks_detected()`（447行目付近）:

```python
def _on_ticks_detected(self, ticks, center, auto_scale, error, vlm_reason, request_id):
    ...
    self.detected_ticks = ticks          # ← tick_detect.detect_scale_ticks() の生の結果
    self.center_point = center
    self._draw_markers()

    if auto_scale is not None:
        self.auto_scale_candidate = auto_scale
        self._show_scale_candidate()      # ← ここで self.detected_ticks を描画に使う
        return
```

`ticks`（`self.detected_ticks`に入る）は、`_on_center_confirmed()`のworker内で
`tick_detect.detect_scale_ticks()`を呼んだ直後の**生の目盛り**。`is_major`は
長さベースの粗い判定のまま。

一方、実際にzero_pt/full_ptを決めているのは同じworker内で呼ばれる
`scale_value_detect.detect_scale_values()`で、その戻り値`auto_scale`には
`auto_scale['ticks']`として**OCR数字との対応付けで主目盛りを判定し直し、
足りない目盛りを外挿で補完した後のticks**（`extend_ticks_to_numbers`の結果、
`synthetic`フラグ付き）が入っている。`tools_render_overlays.py`（評価用の
目視検証ツール）は`result['ticks']`（＝この補正後のticks）を描画に使っているが、
**`main_sotuken.py`はこの補正後のticksを一度も使っていない。**

そのため、GUIで見える緑/グレーの目盛りマーカーの主目盛り判定は、実際に
zero_pt/full_ptが決まった根拠（OCR対応付け）とズレて見える。T1-6のようにOCR側の
判定が改善しても、GUIの表示は昔の粗い判定のままなので「変わっていないように見える」。

## 直すこと

対象ファイル: `main_sotuken.py`

### 1. `self.detected_ticks` を、OCR補正済みのtickに差し替える

`_on_ticks_detected()` で、`auto_scale is not None` かつ
`auto_scale.get('ticks')` があれば、`_show_scale_candidate()`を呼ぶ**前に**
`self.detected_ticks = auto_scale['ticks']` に更新する。

これにより、`_show_scale_candidate()`（484行目〜）だけでなく、`_draw_markers()`
（679行目〜）や、手動クリック時の`tick_detect.snap_to_tick()`（653/660行目、
`self.detected_ticks`を参照）も、実際の判定根拠と一致したticksを使うようになる
（自動候補を拒否して手動でクリックする場合の目盛りスナップ精度も上がる副次効果がある）。

**注意:** `auto_scale is None`（自動判定が失敗した場合）は、これまで通り生の
`ticks`（`tick_detect.detect_scale_ticks`の結果）のままでよい。

### 2. `_show_scale_candidate()` に「synthetic（外挿で補った目盛り）」の見分けを追加

`tools_render_overlays.py`の描画規則に合わせる（`thickness = 2 if t.get('synthetic') else -1`、
つまり実際に検出された目盛りは塗りつぶし円、外挿で座標だけ合成した目盛りは
輪郭だけの円）。現状の`_show_scale_candidate()`は塗りつぶし円のみ:

```python
for t in self.detected_ticks:
    color = (0, 200, 255) if t['is_major'] else (110, 110, 110)
    radius = 4 if t['is_major'] else 2
    pt = (int(round(t['centroid'][0])), int(round(t['centroid'][1])))
    cv2.circle(overlay, pt, radius, color, -1)
```

これを、`t.get('synthetic')`がTrueなら`thickness=2`（輪郭のみ）、Falseなら
`thickness=-1`（塗りつぶし）に変える。色・半径のロジックは変えなくてよい。

### 3. OCRで読めた数字とその対応付けを、オーバーレイ上にラベル表示する

**これが今回のメイン要望（「対応付けを確認できるようにしてほしい」）。**

`_show_scale_candidate()`内で、`self.image_original`に対して
`scale_value_detect.read_scale_numbers(self.image_original)`を呼び、
`scale_value_detect.bind_numbers_to_ticks(numbers, self.detected_ticks, self.center_point, max_angle_deg=12.0)`
で対応付けを取得する（`max_angle_deg=12.0`は`detect_scale_values`のデフォルト値
と揃える）。

戻り値（`bound`、`[{'value', 'tick', 'angle'}, ...]`形式。`scale_value_detect.py`の
`bind_numbers_to_ticks`のdocstring・戻り値の形を確認して使うこと）の各要素について、
対応する目盛りの`centroid`近くに、OCRで読んだ`value`を小さく描画する
（例: `cv2.putText(overlay, f"{b['value']:.4g}", (centroid_x+6, centroid_y+14), font, 0.4, (255,255,0), 1)`。
色は他の描画と重ならない黄色系などにする）。

これにより、ユーザーはオーバーレイを見るだけで「どのOCR数字がどの目盛りに
対応付けられたか」を確認できるようになる。

**このOCR呼び出しはメインスレッドで行うと画面がブロックする可能性があるので、
`_on_center_confirmed()`のworker内（scale_value_detect.detect_scale_valuesを
呼んでいるのと同じ場所、421〜423行目付近）で`numbers`も計算し、
`self.root.after(...)`経由で`_on_ticks_detected`に渡し、`self.detected_numbers`
のようなインスタンス変数に保持しておくこと。** `_show_scale_candidate()`から
毎回OCRを呼び直すとUIがカクつくため避ける。

## 検証方法

**GUIなので自動テストだけでなく、実際に起動して目で確認すること。**

```
venv\Scripts\python.exe main_sotuken.py
```

- `images/meter1.png` 等のストック画像（企業提供画像は使わない）を読み込み、
  中心点をクリックして自動検出候補が表示された段階で:
  - 主目盛り（塗りつぶし）と外挿目盛り（輪郭のみ）が視覚的に区別できる
  - 各主目盛りの近くにOCRで読んだ数字（100, 200, 300...等）が表示される
  - 表示されているzero_pt/full_ptの位置と、ラベル表示された数字が矛盾しない
    （例えばzero_ptの近くに"0"のラベルが出ている）
- 既存の動作（中心点クリック→自動検出→確定/入れ替え/手動選択、手動クリックでの
  目盛りスナップ）が壊れていないこと

自動テストがあれば実行:
```
venv\Scripts\python.exe -m unittest discover -s tests
```
（`main_sotuken.py`のGUI部分に既存のunittestは無い可能性が高いので、
無ければ無理に追加しなくてよい。既存tests一式の退行が無いことだけ確認する）

## 関連

`tasks/design/T1-6-ゼロ点OCR検出漏れの対策.md` / `tools_render_overlays.py`
（同じ描画規則の参照元） / `scale_value_detect.py`の`bind_numbers_to_ticks`,
`extend_ticks_to_numbers`, `read_scale_numbers`
