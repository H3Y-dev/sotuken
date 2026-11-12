effort: medium

# 依頼: PC側の2つの小さな修正(Python)— manifestのnull許容、ルートの機器件数の制限

作業場所(この中だけ触る): C:\卒研\git_stk\sotuken-wt-fx (ブランチ fix/pc-manifest-null、main最新から)
Pythonは C:\卒研\git_stk\sotuken\venv\Scripts\python.exe を使う(新しいworktreeにvenvが無い)。テスト: `& C:\卒研\git_stk\sotuken\venv\Scripts\python.exe -m unittest discover -s tests -q`(いまのmainは575件OK)。

## 背景
Android側(点検フロー)が、設計書 `tasks/design/Android-点検フロー実装設計.md` の §3.3 と §11 に従って manifest を送る。PC側(P2、#120)の `manager/routes.py` が、その設計の取り決めより厳しく、受け付けられない。取り決めの正本は `tasks/design/点検フロー設計.md`「取り決め」の節と、上の設計書 §3.3・§11。

## 修正1: manifest の null 許容(`manager/routes.py` の `validate_manifest`・`save_manifest`・点検の状態判定)
Androidが送る manifest で、次の項目が `null` になることがある(設計書 §11)。PC側はこれらを**拒否せず受け付ける**こと。
- トップレベルの `operator`・`place`・`route_id`: `null` 可(`operator`・`place` は文字列なら今の検証=256文字以下・制御文字なし、のまま)。DBには NULL で保存する(`inspections` の列が NOT NULL なら、NULL許容に直すマイグレーション。既存DBを壊さない)。
- 各写真の `sha256`: `null` 可(端末の画像ファイルが無く計算できなかった写真)。文字列のときは今の検証(64桁16進)。**sha256 が null の写真は、受信済みの画像と突き合わせられないので、「未着」(`missing_photos` に file_name を入れる)として数える。**
- 各写真の `device_id`・`device_id_source` の null は今のまま許容。
- `missing`・`extra` は、配列で空もあり得る(今のまま)。
- 他の厳しさ(版 `v`、`inspection_id` 一致、写真名の形式と重複、日時の検証)は変えない。

## 修正2: ルートの機器件数の制限(`manager/routes.py` の `save_route`)
ルートの機器は **1〜200件**(設計書 §6)。`save_route` で、0件と201件以上を拒否する(`ValueError`。画面のルート作成フォームでも、エラーが画面に出る既存の流儀に合わせる。例: 0件では保存できない旨のメッセージ)。`list_routes` の `count` はそのまま。既存のテストで0件のルートを保存しているものがあれば、止めてメインへ質問する(期待値を勝手に変えない)。

## 完了条件
- テストを追加: manifestの null(operator・place・route_id・sha256)の受け付けと保存、sha256 null の写真が未着になる、null入りmanifestをHTTP(`POST /inspections/<id>/manifest`)で送って200・`missing_photos`に載る、ルート保存の0件・201件の拒否と1件・200件の受け付け。
- **既存テストの期待値は変えない**(件数が増えるのは追加テストのみ)。全テストOK。件数を報告に書く。
- コミットしてブランチをpushし、PRを出す(マージは私がやる)。1作業を単独で進める。子エージェントは使わない。
