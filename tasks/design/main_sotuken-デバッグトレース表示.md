# main_sotuken.py: アルゴリズムの動きをトレースできるデバッグ表示の追加

作成: 2026-08-27 ／ 担当: 本人（設計） → Codex（実装）

## 要望（本人より）

> 「main_sotukenを実行したときに下に表示されるメッセージをもっとアルゴリズムの
> 動きが詳細にトレースできるようにして動きのデバッグの補助にしたい」
> 「メッセージ形式でなくても大丈夫です、フローチャート等の図などの見た目で
> わかりやすい物も併用して実装すると便利ですね」

現状、画面下部の`status_var`（1行のラベル）が処理段階ごとに上書きされるだけで、
**過去の段階の情報が残らず、途中経過を後から追えない。** また「中心点候補が
Hough検出とtick再推定のどちらだったか」「OCRで何個の数字が読めたか」
「クロスチェックで何パターン試して何個一致したか」といった、既に内部で
計算されている情報が画面に一切出ていない。

## 方針

**普段の操作性は変えない。** 新しいデバッグ表示は**トグルボタンで表示/非表示を
切り替えられる追加パネル**とし、デフォルトは非表示のままにする（既存のUIフローに
割り込まない）。表示すると以下の2つが並ぶ:

1. **フローチャート（Canvas）**: パイプラインの4段階を箱で表し、各段階の状態を
   色で示す（未実行=グレー／実行中=青／成功=緑／警告あり=オレンジ／失敗=赤）
2. **詳細トレースログ（Text、スクロール可）**: 各段階で実際に使われた値・
   判定根拠をタイムスタンプ付きで積み上げて表示する（消えずに残る）

**核心のアルゴリズム・判定ロジックは一切変更しない。** 既にpipelineが計算して
いる値をより詳しく画面に出すだけ（例外は「実装内容」2番目の、`attempts`という
追加情報だけを返す加算的な変更）。

## 実装内容

### 1. UIにデバッグパネルを追加する

対象ファイル: `main_sotuken.py`

- ヘッダー（`_build_ui`内、97〜111行目付近、既存の「🔄 リセット」ボタンの近く）に
  トグルボタン「🐞 デバッグ」を追加。押すたびに`self.debug_visible`を反転し、
  デバッグフレームの表示/非表示を切り替える
- `status_frame`（191行目付近）の直前に、新しい`self.debug_frame`
  （`tk.Frame`）を追加する。中身は:
  - `self.flow_canvas`（`tk.Canvas`、高さ70px程度、背景は他のUIと合わせて
    `#1e1e2e`か`#2a2a3e`）: 「① 中心検出」「② 目盛り検出」「③ OCR対応付け」
    「④ 針検出」の4つの角丸矩形（`create_rectangle`でよい）を横に並べ、
    間を矢印（`create_line`に`arrow=tk.LAST`）でつなぐ。各矩形の中に
    ラベルテキストも描画する
  - `self.trace_text`（`tk.Text`、高さ8〜10行、`state=tk.DISABLED`を基本にし、
    書き込み時だけ`NORMAL`にしてから戻す、等幅フォント推奨）＋
    `tk.Scrollbar`を右に添える
- ヘルパーメソッドを追加:
  - `_flow_reset()`: 4段階の矩形を全て「未実行」色に戻し、`trace_text`の中身を
    空にする。`reset()`メソッド（225行目付近）から呼ぶ
  - `_flow_set_stage(stage_key, state)`: `stage_key`は`'center'`/`'ticks'`/
    `'ocr'`/`'needle'`のいずれか、`state`は`'running'`/`'ok'`/`'warn'`/`'fail'`。
    該当する矩形の色を変える（グレー→状態に応じた色）
  - `_trace(message)`: `trace_text`に`[HH:MM:SS] message`の形式で1行追記し、
    自動で最下部へスクロールする（`self.trace_text.see(tk.END)`）

### 2. 各パイプライン段階でトレースを出力する

以下の4箇所に、既存の変数からトレース文を組み立てて`_flow_set_stage`と
`_trace`を呼ぶ処理を追加する。**新しい検出処理は書かない。既に計算済みの
変数を使うだけ。**

#### ① 中心検出（`_on_center_confirmed`のworker関数、394〜417行目付近）

`hough`と`refined`が計算された直後、`center`/`center_source`が決まった時点で:

```python
self._trace(
    f"中心検出: Hough={hough if hough else '検出なし'} / "
    f"再推定={refined if refined else '未実施'} → 採用={center}"
    f"（{ {'hough':'Hough単独','corrected':'再推定で補正','ticks':'目盛りのみ'}.get(center_source, center_source) }）"
)
self._flow_set_stage('center', 'ok' if center_source else 'warn')
```

（`center`/`center_source`は既にこの関数内でローカル変数として計算されている。
`self.root.after`経由でメインスレッドに渡す既存の仕組みに、これらの値も
一緒に運ぶ必要がある。現状`_on_ticks_detected`へは`ticks, numbers, center,
auto_scale, error, vlm_reason, request_id`が渡っているので、`hough`と`refined`
（あるいはそれらをまとめた文字列）も追加で渡すこと）

#### ② 目盛り検出（同じworker、ticks検出直後）

```python
n_major_raw = sum(1 for t in ticks if t.get('is_major'))
self._trace(f"目盛り検出: {len(ticks)}本検出（うち主目盛り候補{n_major_raw}本、暫定判定）")
self._flow_set_stage('ticks', 'ok' if ticks else 'warn')
```

#### ③ OCR対応付け（`_on_ticks_detected`、`auto_scale`が入った直後）

```python
numbers_str = ", ".join(f"{n['value']:.4g}(score={n['score']:.2f})" for n in numbers) or "なし"
self._trace(f"OCR検出数字: {numbers_str}")

if auto_scale is not None:
    n_major_final = sum(1 for t in auto_scale.get('ticks', []) if t.get('is_major'))
    n_synthetic = sum(1 for t in auto_scale.get('ticks', []) if t.get('synthetic'))
    self._trace(
        f"OCR対応付け: 最小値={auto_scale['min_value']:.4g} 最大値={auto_scale['max_value']:.4g} "
        f"（対応 {auto_scale['n_used']}/{auto_scale['n_total']}件、"
        f"source={auto_scale.get('source')}、confident={auto_scale.get('is_confident')}）"
        f" 主目盛り{n_major_final}本（うち外挿補完{n_synthetic}本）"
    )
    if auto_scale.get('needle_overlap_zero'):
        self._trace("⚠️ 針が0の目盛りに重なっており、0の位置は目視確認できていません")
    # attempts（下記2番目の変更で追加される場合のみ）があれば、各試行も列挙する
    for a in auto_scale.get('attempts', []):
        self._trace(
            f"  試行[{a['label']}]: 最小値={a['min_value']:.4g} 最大値={a['max_value']:.4g} "
            f"対応{a['n_used']}/{a['n_total']}件"
        )
    self._flow_set_stage(
        'ocr',
        'warn' if (not auto_scale.get('is_confident', True)
                   or auto_scale.get('needle_overlap_zero')) else 'ok')
else:
    self._trace(f"OCR対応付け: 自動判定に失敗（{vlm_reason or '理由不明'}）")
    self._flow_set_stage('ocr', 'fail')
```

#### ④ 針検出（`_detect_and_show`、`reading`が求まった直後、735行目付近）

```python
if reading is not None:
    self._trace(
        f"針検出: 角度={reading['angle_deg']:.2f}° ratio={reading['ratio']:.4f} "
        f"→ 値={reading['value']:.4g}"
    )
    self._flow_set_stage('needle', 'ok')
    ...(既存の描画処理)...
else:
    self._trace("針検出: 直線を検出できませんでした")
    self._flow_set_stage('needle', 'fail')
```

**手動クリックのフロー（自動判定を使わずStep 1〜3をクリックで進めた場合）でも、
最低限「④針検出」のトレースは出るようにすること。** ①〜③はクリック操作時は
「手動」であることが分かるトレース文（例:「中心検出: 手動クリックで指定」）
に差し替える。

### 3.（加算的な変更）`scale_value_detect.detect_scale_values`に`attempts`を追加する

対象ファイル: `scale_value_detect.py`

`detect_scale_values`内で、`_run_ocr_tick`を複数の前処理バリアント
（元画像・CLAHE 1.5・CLAHE 2.5、1026〜1043行目付近）に対して呼んでいる箇所がある。
**この各試行の結果（クロスチェックで採用されなかったものも含む）を、
最終的に返す辞書に`'attempts'`という新しいキーとして追加する。**

具体的には、`results`リストに追加している各`result`に、どのバリアントの
試行だったかを示すラベル（例: `'original'`, `'clahe1.5'`, `'clahe2.5'`）を
`result['label']`として付与しておき（`_run_ocr_tick`呼び出し直後、
`results.append(result)`の前に`result['label'] = ラベル名`を追加するだけでよい）、
`agreed`が確定した後（1053行目`if agreed is not None:`の直後あたり）に:

```python
agreed['attempts'] = [
    {'label': r.get('label', '?'), 'min_value': r['min_value'],
     'max_value': r['max_value'], 'n_used': r['n_used'], 'n_total': r['n_total']}
    for r in results
]
```

を追加する。**既存のどの戻り値・判定ロジックも変更しない。新しいキーを
1つ追加するだけ**であることを必ず守ること（`determine_min_max`や
`_find_agreeing_result`等の判定関数は一切触らない）。

VLMフォールバック側の戻り値（1104行目以降）にも、同様に`attempts`（この場合は
`results`が空になっているはずなので空リストでよい）を追加して、
呼び出し側が`auto_scale.get('attempts', [])`で常に安全に読めるようにする。

## 検証方法

```
venv\Scripts\python.exe -m unittest discover -s tests
```

（`scale_value_detect.py`の変更は新しいキーの追加のみなので、既存テストの
アサーションには影響しないはず。もし`agreed`辞書のキー集合を厳密に比較する
テストがあれば、その内容を確認し、`attempts`キーの追加が問題にならないか
確認すること）

**GUIなので、可能であれば実際に起動して確認すること:**
```
venv\Scripts\python.exe main_sotuken.py
```
- ストック画像（`images/meter1.png`等、企業提供画像`C:\卒研\images\`は使わない）
  を開き、「🐞 デバッグ」ボタンでパネルが表示/非表示できる
- 中心点クリック→自動候補確認まで進めると、フローチャートの①②③が順に色付き、
  トレースログに検出内容が積み上がる
- 最後まで進めると④も色付き、角度・値のトレースが出る
- 「🔄 リセット」でフローチャート・トレースログが両方クリアされる

自動化が難しい部分（実際の目視でのGUI操作）は本人が別途行うので、
起動確認・構文チェック・可能な範囲のロジック確認を行った上で正直に報告すること。

## 完了条件・禁止事項

- 既存のunittestが全てパスすること
- `tick_detect.py`・`meter_reader.py`の判定ロジックは一切変更しないこと
- `scale_value_detect.py`は`attempts`キーの追加以外、一切変更しないこと
  （既存の判定・戻り値を変えない）
- 企業提供画像をコミット・アップロードしないこと
- pushやコミットは不要。作業ツリーの変更のまま報告する

## 関連

`tasks/design/main_sotuken-目盛り対応付けオーバーレイ表示.md`（直前の関連作業）

---

## 2026-08-31追補: OCR / LLMの候補値・採用元を分離表示

本人から「最小値・最大値にOCRとLLMのどちらを使ったかGUIでは分からない」
「評価時もどちらが不正確か判定したい」と要望があったため、初版の表示仕様を拡張した。

- フローチャートの第3段階を「OCR/LLM判定」とし、内部処理
  `OCR数字検出 → 前処理4条件 → 条件間照合 → LLM照合 → 最終採用`を明記
- OCR候補、LLM候補、最終採用の最小値・最大値を3行の表で表示
- 最小値・最大値ごとに採用元を保持し、片方だけLLMへ置換した場合は
  `source=hybrid`として表示
- OCRが検出した全数字を、値・信頼度・画像上の座標付きリストで表示
- ログへ各OCR試行、OCR/LLMの一致・不一致、フォールバック有無、採用理由を記録
- 自動判定に失敗しても`diagnostics_out`へ候補と失敗理由を返し、GUIで確認可能にした
- デバッグ表示中は画像キャンバスを縮め、900px高でも表とログが切れないようにした
- `evaluate.py`ではgroundtruthを使い、`両方正しい`、`OCRだけ誤り`、
  `LLMだけ誤り`、`両方誤り`、`片方未実行/未検出`に分類する

GUIにはgroundtruthが無いため、GUI上ではどちらが「誤り」とは断定せず、
候補の一致・不一致と採用判断だけを表示する。正誤の断定は評価スクリプト側で行う。

検証結果:

- unittest 73件合格
- 丸型9枚の`--no-vlm`評価は読取9/9、許容誤差内8/9、平均引用誤差1.37%FS
- `気密試験_昇圧後圧力計.jpg`はOCR 0〜108（誤り）／LLM未実行と個別表示
- 1100×900pxでGUIを実描画し、候補表3行・OCR一覧・ログを目視確認
