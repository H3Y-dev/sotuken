# 工程別評価ツール (Stage Errors Evaluation)

合成画像・実画像データセットに対して、各処理工程（盤面中心、0点・満尺点目盛り、目盛り範囲、針検出）ごとの誤差を逐次記録・集計するためのスクリプト群です。

## 構成
- `eval/stage_errors.py`: 画像ごとの工程別誤差を計算し、1行ずつJSONL形式で出力・フラッシュする評価実行スクリプト。中断時の再開（レジューム）対応。
- `eval/summarize_stage.py`: `stage_errors.py` が出力したJSONLファイルを読み込み、条件別・工程別の集計表およびワースト症例をMarkdown形式で標準出力に表示するスクリプト。
- `tests/test_stage_errors.py`: 各種幾何計算・誤差集計・再開ロジックの単体テスト。

## 使い方

リポジトリルート（`C:\卒研\git_stk\sotuken` 等）から実行します。

### 1. 誤差評価の実行
```bash
python eval/stage_errors.py <正解JSONパス> -o <出力先JSONLパス> [オプション]
```

主なオプション:
- `-o, --output PATH`: 出力先JSONLファイルパス（必須）
- `--local-read`: 局所読み取り方式を使用する（既定: 全体読み取り）
- `--needle-angle {segment,tip}`: 針の角度算出元（既定: segment）
- `--limit N`: 先頭 N 件のみを評価（中断・再開時は完了分を含めてカウント）

※ `meter_pipeline.read_meter` は常に `use_vlm=False`（再現性確保のため）で実行されます。
※ 処理中に例外が発生した場合もプロセスは停止せず、該当行に `error` を記録して次の画像へ進みます。

### 2. 集計結果の確認（Markdown出力）
```bash
python eval/summarize_stage.py <出力先JSONLパス>
```
標準出力に、条件別集計表（ALL、メーター種類、カメラ画角、照明、ボケ）、工程別内訳、および引用誤差（%FS）のワースト症例がMarkdown表として出力されます。

## 保存済み評価DBの機器別集計

`by_device.py` は、取り込み済みのDBから機器別の精度を集計します。
DBは読み取り専用で開き、パイプラインを再実行しません。
正解の機器IDと `eval/devices.csv` の機器名を使うため、QRを読めなかった画像も正しい機器の母数に入ります。

```powershell
python eval/by_device.py `
  --db 'C:\卒研\合成画像\テスト用QR付き_20261030\評価DB\sidecar.db' `
  --qr-db 'C:\卒研\合成画像\テスト用QR付き_20261030\評価DB\qr_only.db' `
  --groundtruth 'C:\卒研\合成画像\テスト用_20261021\groundtruth_synthetic.json' `
  --images-source 'C:\卒研\合成画像\テスト用QR付き_20261030\取り込み用_サイドカーに機器あり' `
  --output-dir 'C:\卒研\合成画像\テスト用QR付き_20261030\評価DB' `
  --field-images 'C:\卒研\合成画像\テスト用_20261021\現場想定セット'
```

画像は元の正解ファイルと取り込みフォルダのファイル名で対応させ、取り込み画像のSHA-256でDBと照合します。
QRを貼る前後で画像のSHAが変わるため、`--images-source` には取り込み時のQR付き画像を指定してください。
同じ画像に複数のDB記録がある場合は、評価する記録を勝手に選ばずエラーにします。

出力は `機器別精度_全部入り.md/csv`、`機器別精度_現場想定.md/csv`、`QRのみ_機器ID取得率.md` です。
許容内率の母数は対象画像すべてで、未取込と値算出失敗も含みます。
平均・中央値・最大の引用誤差は値を算出できた画像だけで計算します。
式と許容内判定、集計にはルートの `evaluate.py` を再利用します（`eval/evaluate.py` はありません）。
`status=low_confidence` でもパイプラインの `stage=ok` なら既存評価と同じく採点します。
範囲誤り数と、上下限のどちらかを推定できなかった範囲不明数は別々に出します。

### 現場想定セットの選別

`select_field_set(entries)` は次のどれかに当てはまる画像を除外し、採用した正解と除外理由を返します。

- `condition.blur != "none"`
- `condition.lighting != "normal"`
- `abs(condition.camera_yaw) > 30` または `abs(condition.camera_pitch) > 30`
- `degradations` 内のどれかの `strength > 0.5`
- `appearance.max_pointer == true`（置き針。2026-11-04の追加指示）

角度30°と強さ0.5は残します。紛らわしい文字の `distractors` は強い劣化の除外条件に含めません。
元の294枚では94枚が残ります（正面30、斜め18、汚れ8、紛らわしい文字24、背景と画質14）。
除外理由は重複するため、理由別件数の合計は除外画像数と一致しない場合があります。

<!-- 実データ確認: 2026-11-04、groundtruth_synthetic.json 全294件。
degradations は {劣化名: {strength: 数値, seed: 整数}}。空のもの210件、非空84件。
汚れ6種: dial_yellowing, glass_droplets, glass_scratches, dial_dirt, faded_print, glass_fog。
strength の実測値は 0.3 / 0.6 / 0.9。
背景と画質8種: cluttered_background, partial_crop, jpeg_compression, small_in_frame,
color_cast, sensor_noise, uneven_lighting, partial_occlusion。strength は 0.5 / 0.9。
今回の strength の実測範囲は0.3〜0.9。seed は乱数種で強さではない。
紛らわしい文字は degradations={}、distractors 内の strength は別条件なので採否に使わない。
max_pointer は appearance 内の真偽値で全294件中123件がtrue。
置き針除外前166枚、除外後94枚（72枚を追加除外）。 -->

`--field-images` を指定すると集計前に元画像を条件別フォルダへコピーし、
全画像の名前と採否理由を `_選別結果.csv` に保存します。元画像は移動しません。
コピー先は新しいフォルダか、同じ選別条件で作ったフォルダを使ってください。
条件を変えた場合、以前コピーした画像の自動削除は行いません。
