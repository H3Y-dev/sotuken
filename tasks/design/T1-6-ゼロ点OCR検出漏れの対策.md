# T1-6: OCRが「0」を読めない問題への対策

作成: 2026-08-27 ／ 担当: 本人（設計） → Codex（実装）

対象: `耐圧試験_昇圧前圧力計.jpg`（true_value=0.12, 0〜400MPa）/
`耐圧試験_昇圧後圧力計.jpg`（true_value=139.55, 0〜400MPa、映り込みあり）

## 現状（実測、2026-08-27朝）

```
venv\Scripts\python.exe evaluate.py eval/groundtruth.json --no-vlm --scope round
```

```
耐圧試験_昇圧前圧力計.jpg   真値0.12   読取100.00   誤差24.97%FS  NG（範囲誤検出）
耐圧試験_昇圧後圧力計.jpg   真値139.55 読取140.51   誤差0.24%FS   OK（だが範囲は誤検出、たまたま値が近かっただけ）
```

範囲誤検出リストにも両方とも「検出100.0〜400.0 / 正解0.0〜400.0」として出ている。

## 根本原因（3段階、すべて実測で確認済み）

### 1. RapidOCRの文字検出（detection）が「0」の文字領域を一切提案しない

`scale_value_detect.read_scale_numbers()` の元になっているRapidOCRの生出力を
両画像で直接ダンプしたところ、`100`/`200`/`300`/`400`/`PRESSURE GAUGE`/
銘板の文字列などは全てscore 1.0前後で正しく検出されるのに対し、**「0」に対応する
文字領域そのものがdetection結果に一切現れない**（低スコアで棄却されたのでもなく、
そもそも1件も無い）。1桁の小さな文字がティック線に近接しているための
detection側の再現率不足と考えられる（誤読ではなく検出漏れ）。

### 2. `determine_min_max` が「0」の欠落に気づけない

`bind_numbers_to_ticks` で対応付けられるのは100/200/300/400の4点のみ。
これ自体は単調増加で`min_points=3`を満たすため、`determine_min_max`は
何の疑いもなく **100を最小値（zero_pair）として確定してしまう。**
「本来もっと外側に0があるはず」という発想がそもそも入っていない。

### 3. 既存のセーフティネット（`locate_value_by_extrapolation` →
`_verify_label_near_position`）が、VLM前提の分岐にしか実装されていない

`_resolve_scale_position()` には本来「等間隔性から欠測値の位置を予測し、
その位置を拡大再OCRで裏取りする」という仕組みが既にある。しかし
**`is_zero=True` かつ `occlusion_check()`（VLMへの問い合わせ）がTrueの場合しか
この経路が働かない。** `--no-vlm` では `occlusion_check` は常に `lambda: False`
（`_make_occlusion_check`）なので、この経路が一切使われない。

さらに、2026-08-26時点の設計書 `主目盛り判定の再設計.md` では「針が0の目盛りを
隠している」という仮説を立てていたが、**実際は針の遮蔽ではなく、OCR検出モデルが
単独の小さい「0」を拾えていないだけ**と判明した（上記1）。VLM
(`check_needle_overlaps_zero`)を4Bモデルで試して機能しなかった、という
2026-08-25の記録はこの経路自体の限界であり、遮蔽仮説が誤りだったので
今回はVLMを使わない方向で解く。

## 検証済みの解決策

`locate_value_by_extrapolation` で候補tickが見つからない場合の最終手段
（`_synthesize_tick_point` で目盛り線が無くても角度と平均半径から座標を合成する）
を、**VLMの遮蔽確認なしに、`_verify_label_near_position` の拡大再OCRだけで
裏取りする経路として使えるようにする。** 実際に手動で検証済み。

```python
predicted_angle = _predict_angle_for_value(bound, 0.0)   # 2.7096 rad
synth = _synthesize_tick_point(ticks, center, predicted_angle)  # (388, 593)
_verify_label_near_position(img, synth, 0.0, radius=100, upscale=4)  # → True
```

**ただし、有効なcrop半径は画像によって違う。**

| 画像 | radius=60 | radius=80 | radius=100 | radius=120 |
|---|---|---|---|---|
| 耐圧試験_昇圧前 | False | False | **True** | (未検証) |
| 耐圧試験_昇圧後 | False | **True** | False | False |

→ **単一のradiusでは両方は救えない。複数のradiusを順番に試し、
どれか1つで対象の値が確認できればそれを採用する方式にする。**
（周辺のノイズ量によって最適な拡大範囲が変わるため。実際、後者の画像は
映り込みグレアと「263.03」という誤検出数字が近くにあり、広く切り取りすぎると
むしろ悪化する）

## 実装方針

対象ファイル: `scale_value_detect.py`

1. **`_verify_label_near_position` を複数半径で試す形に変える。**
   例: `radii=(60, 80, 100, 130)` を順に試し、最初に成功したものを採用する
   小さい関数（`_verify_label_near_position_multi` 等）を追加するか、
   既存関数に `radii` 引数を持たせて呼び出し側でリストを渡す。
   **既存の呼び出し（100/200/300/400側の検証など）を壊さないこと**
   （デフォルト引数で後方互換を保つ）。

2. **`_resolve_scale_position` のis_zero分岐から、VLM (`occlusion_check`) への
   依存を外す。** 具体的には696〜710行目付近:
   - 現状: `locate_value_by_extrapolation`が失敗した場合、
     `is_zero and occlusion_check()`がTrueの時だけ`_synthesize_tick_point`を試す
   - 変更後: `is_zero`であれば`occlusion_check`の結果によらず
     `_synthesize_tick_point` → 複数半径での`_verify_label_near_position`
     による裏取りを試す。**裏取りに成功した場合のみ採用する**
     （根拠のない値を採用しないという既存の安全性は維持する）
   - `occlusion_check`/VLM自体は残してよい（他の経路・将来のために削除はしない）。
     ただし`is_zero`のこの経路が動くために必須ではなくする

3. **`locate_value_by_extrapolation`自体の`is_major`限定も緩めるかどうかを検討する。**
   今回はticks自体が候補周辺に存在しなかった（`_synthesize_tick_point`で
   座標を合成する経路）ため必須ではないが、他の画像で「is_majorではないが
   実在するtickが候補になるべき」ケースがないか、`tests/`の既存テストと
   9枚評価の結果で退行が無いか確認すること。

## 検証方法（実装後、必須）

```
venv\Scripts\python.exe -m unittest discover -s tests
venv\Scripts\python.exe evaluate.py eval/groundtruth.json --no-vlm --scope round
venv\Scripts\python.exe tools_render_overlays.py --no-vlm
```

- **退行が無いこと**: 既存50件超のテストが全てパスし、他7枚の評価数値が悪化しないこと
- **この2枚が改善すること**: 検出範囲が「0.0〜400.0」になること
  （耐圧試験_昇圧前の引用誤差が24.97%FSから大きく下がることを期待。
  昇圧後は既にOKだったので誤差の変化より「範囲誤検出」フラグが消えることを確認する）
- **数値だけで判定せず、`eval/overlays/`の2枚を目視確認する。**
  ゼロ点（マゼンタ等の該当マーカー）が実際の「0」の目盛り位置に来ているか見る

## 関連

[[主目盛り判定の再設計]]（今回否定された「針の遮蔽」仮説の元になった設計書）/
`eval/groundtruth.json` / `tasks/todo.md` T1-6
