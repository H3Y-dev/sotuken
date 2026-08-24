# 作業をGitHubに共有する手順

作業が完了したら、この手順で共有してください。分からない操作があれば、
自分が使っているAI（Claude/Gemini）にこのファイルを見せて「この手順通りに
一緒にやってほしい」と頼めば、コマンドを一緒に実行してくれます。

---

## 0. 前提

**必ず最新のmainを取り込んでから作業結果をpushしてください。** これを飛ばすと、
自分の変更が「大量のファイル削除」として扱われてしまい、mainにマージしたときに
他の人の最近の作業が消えてしまいます（実際に古いブランチでこの問題が起きたため、
`legacy-`を付けて凍結しました）。

## 1. 最新のmainを取り込む

```bash
git fetch origin
git rebase origin/main
```

途中で「conflict（競合）」というエラーが出たら、自分で解決しようとせず、
使っているAIに「rebaseでconflictが出た、どうすればいい？」と聞いてください。
ファイルの中身を見ながら一緒に解決できます。

## 2. GitHubへpushする

分かりやすいブランチ名を付けてください（自分のニックネーム＋担当内容）。

```bash
git push -u origin <ブランチ名>
```

例:
- SKくん: `feature/t1-2-circle-fit`
- SRくん・KPくん: `feature/t6-manager`
- YMさん: `feature/t3-orientation`

初めてpushするとき、GitHubのユーザー名・パスワード（または認証）を聞かれることが
あります。分からなければAIに聞くか、本人（大久保）に連絡してください。

## 3. Pull Request（PR）を作る

1. pushが終わると、ターミナルに以下のようなリンクが表示されます。それをブラウザで開く。
   ```
   remote: Create a pull request for '<ブランチ名>' on GitHub by visiting:
   remote:      https://github.com/H3Y-dev/sotuken/pull/new/<ブランチ名>
   ```
2. リンクを開かなかった場合は、GitHubのリポジトリページ
   （https://github.com/H3Y-dev/sotuken）を開くと、緑や黄色のボタンで
   「Compare & pull request」と出ているのでそれを押す
3. タイトルに何をやったか一言（例:「T1-2 円フィッティングと選択ロジック」）
4. 説明欄に、日報の内容をそのまま貼ってOK
5. 「Create pull request」ボタンを押す

これで完了です。以降の確認・マージは本人（大久保）が行います。

## 4. その後

- PRを作ったら、Slackで「PR作りました」と一言連絡してください
- マージされるまで、同じブランチで作業を続けて構いません（追加のコミットは
  自動的にPRに反映されます）
- レビューで修正依頼が来ることがあります。その場合は指摘に沿って直し、
  再度pushすれば自動的にPRが更新されます

## 困ったときは

- 何が起きているか分からなくなったら、**まず`git status`を実行**してAIに結果を見せる
- 焦って`git reset --hard`や`git push --force`をしない（変更が消える可能性があります）。
  分からない操作の前に必ずAIか本人に確認する
