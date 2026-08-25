# SRくんへ: mainではなく作業ブランチにpushする手順

2026-08-25、`main`に直接pushされていました。**責める話ではありません**が、
mainが壊れると全員の作業が止まるので、手順を共有します。

このファイルの内容をまるごと自分が使っているAI（Gemini）に貼り付けて、
「この手順通りに一緒にやってほしい」と頼めば大丈夫です。

---

## 何が起きたか（結果だけ先に）

- `258e934 閾値追加 SR` が **`main`に直接入りました**
- その結果、**mainのT6のテストが壊れました**（`manager`配下の2件がimportエラー）
- 修正はこちら（大久保）で行い、push済みです。**今のmainは直っています**
- 閾値アラート機能と`app.py`はそのまま残してあります。作ったものは消えていません

**なので、まず最新のmainを取り込んでから作業を再開してください。**（手順は下記）

## なぜmainに直接pushしてはいけないか

mainは「全員が動く前提の本流」です。ここが壊れると、他のメンバーが
自分のコードを触っていないのにテストが落ちるようになり、
「自分のせいかも」と原因探しに時間を取られます。

ブランチで作業すれば、**壊れていてもその影響は自分の中だけに閉じます。**
確認して問題なければmainに取り込む、という順番にするためのルールです。

---

## 手順1: いま自分がどこにいるか確認する

```powershell
git branch --show-current
```

- `main` と表示された → **手順2へ**（ブランチを作る必要があります）
- `SRdevelopment-v2` と表示された → 既に正しいブランチにいます。**手順3へ**

## 手順2: 作業ブランチを作って移動する

まず、最新のmain（修正済み）を取り込みます。

```powershell
git fetch origin
git checkout main
git pull
```

> ここで **Vimという黒い画面が開いて操作できなくなったら**、
> `Esc`を押してから `:wq` と入力して`Enter`。それで抜けられます。
> 詳しくは`tasks/Git運用マニュアル.md`の「1.5」を見てください。

次に、そこから作業ブランチを作ります。

```powershell
git checkout -b SRdevelopment-v2
```

`Switched to a new branch 'SRdevelopment-v2'` と出れば成功です。

## 手順3: 作業して、ブランチにpushする

コードを編集したら、**pushする前に必ずテストを実行してください。**

```powershell
venv\Scripts\python.exe -m unittest discover -s manager -p "test_*.py"
venv\Scripts\python.exe -m unittest discover -s tests
```

**両方とも `OK` と出ることを確認してから**、次に進みます。
（`FAILED`のままpushすると、今回と同じことが起きます）

### VS CodeのGUIでpushする場合

1. 左側のソース管理アイコン（枝分かれのマーク）をクリック
2. 変更したファイルの「+」をクリックしてステージ
3. メッセージ欄に日本語で内容を書く（例:「閾値判定を追加」）
4. 「コミット」を押す
5. **画面下部の左端に表示されているブランチ名が`SRdevelopment-v2`になっていることを確認**
6. 「変更の同期」または「…」→「プッシュ」を押す
7. 初回は「リモートブランチを作成しますか？」と聞かれるので **OK** を選ぶ

### ターミナルでpushする場合

```powershell
git push -u origin SRdevelopment-v2
```

初回はこの`-u`付きで実行してください。2回目以降は `git push` だけでOKです。

## 手順4: pushできたか確認する

```powershell
git log --oneline -1 origin/SRdevelopment-v2
```

自分の最新コミットが表示されれば成功です。
そのあとSlackで「pushしました」と一言連絡してください。

---

## 今回の修正内容（参考。同じことを繰り返さないために）

こちらで直した3点です。**次から気をつけてもらえれば十分です。**

### 1. `manager/manager.py` のimportを元に戻しました

```python
# 今回入っていた書き方（これだとテストが壊れる）
from manager.storage import MeterReading, Storage

# 戻した書き方（両方の呼ばれ方で動く）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from storage import MeterReading, Storage
```

**理由:** テスト側（`test_manager.py` / `test_integration.py`）は
`sys.path`に`manager/`を追加してから `from manager import MeterManager` と
書いています。この呼び方だと`manager.py`が「パッケージ」ではなく
「1つのファイル」として読み込まれるため、その中で`from manager.storage`と
書くと `'manager' is not a package` というエラーになります。

**教訓:** importの書き方を変えるときは、**そのファイルを読み込んでいる側**
（テストや他のモジュール）が壊れないか確認してください。確認方法は
「テストを実行する」だけでOKです。

### 2. `process_image`の戻り値の変更にテストを追従させました

`process_image`が`MeterReading`ではなく辞書を返すようになっていました。
`app.py`が新しい辞書形式（`res["val"]`, `res["is_alert"]`など）を使っているので、
**戻り値の方は変えず、テスト側を新しい形に合わせました。** あわせて閾値
アラートのテスト（上限超過・下限割れ・正常・読み取り失敗）も追加しています。

**教訓:** 関数の戻り値の型を変えるのは「破壊的変更」と呼ばれ、その関数を
呼んでいる場所すべてに影響します。変えること自体は悪くないですが、
**変えたら呼び出し側とテストも一緒に直す**必要があります。

### 3. `manager.db` をgit管理から外しました

`.gitignore`に`manager.db`と`readings_export.csv`を追加しました。
これらは実行するたびに生成されるデータファイルなので、コードと一緒に
コミットしません（人によって中身が違い、毎回衝突の原因になります）。

---

## 補足: `app.py` について

`streamlit`と`pandas`を使っていますが、この2つは`requirements.txt`に
入っていないため、**他のメンバーの環境では`app.py`が動きません。**

`requirements.txt`は全員が使う共有ファイルなので、追加する前に一度相談してください。
特にPython 3.8対応版のバージョン指定が必要です（新しいstreamlitは3.9以上が必須）。
