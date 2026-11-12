# 記録画面 React 試作

ダミーデータで機器の読み取り履歴を確認する試作です。実データやデータベースには接続しません。

```sh
npm install
npm run dev -- --host 127.0.0.1 --port 5199
npm test
npm run build
```

`src/mock` にダミーデータ、`src/api` に仮の API、`src/lib` に絞り込みと書き出しの処理があります。

`cn` は UI 部品のクラス名の結合に使っています。

## 部品の比較

| ライブラリ | 使用箇所と制約 |
| --- | --- |
| shadcn/ui | メイン画面のカード、表、ボタンなど |
| Magic UI | `npx shadcn@latest add @magicui/number-ticker --yes` で取得した NumberTicker を件数に使用 |
| Astryx 0.7.13 | `#astryx` の比較画面に Card、VStack、Table、Badge を使用。絞り込みは標準の select と日付入力 |

## Astryxの評価

- Viteの本番ビルドはStyleXプラグイン追加なしで成功。配布済みの `astryx.css` を読み込む。
- 比較画面のCSSは遅延読み込みに分離した。同ページでのTailwindとの衝突はブラウザで未確認。
- 日本語の文字列を使用したが、表示とフォントはブラウザで未確認。
- CLIの `astryx component Table` によると、並び替えと行選択はプラグインで利用可能。比較画面には未実装。
- 比較前のビルドはJS 759.52 kB、CSS 26.85 kB。比較画面追加後はメインJS 761.66 kB、CSS 26.85 kBに加え、遅延チャンクのJS合計519.44 kB、CSS 269.18 kB（いずれも圧縮前）。
- v0.xのためAPIやスタイルが変更されるリスクがある。導入前に固定バージョンでの検証が必要。
- `astryx doctor` は fail 0。npm install時にpostinstallが許可待ちとの警告が出た。

## Streamlit画面との対応

| 機能 | 状態 |
| --- | --- |
| 点検・機器・日付の絞り込み、最新値、履歴、グラフ、書き出し | ダミーのみ |
| 画像プレビュー | ダミーのみ |
| 自動更新の実データ連動、再処理、点検ルート作成 | 未再現 |
| 点検の受信状態、機器の判定 | 未再現 |

## 計器盤の見本（方向性A）

`/#gauge` が点検の一覧、`/#gauge/I-MULTI-20261112` が1件の点検の詳細です。デザインの決まりは `DESIGN.md` にあります。コードは `src/gauge/`、ダミーデータは `src/mock/inspections.ts` にあります。npm の依存は増やしていません。shadcn/ui の Alert・Toggle・ToggleGroup を追加しました。

比較画面は開発サーバーの `/#astryx` を直接開きます。通常画面に戻るには `/` を開き直します。
