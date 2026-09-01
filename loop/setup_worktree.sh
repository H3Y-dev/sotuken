#!/usr/bin/env bash
# loop/setup_worktree.sh — サンドボックス(git worktree)を用意する。
# mainを直接汚さないための必須ステップ。ループ本体(run_loop.sh)はこれを前提にする。
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source loop/config.env

if [[ -d "$WORKTREE_DIR" ]]; then
  echo "既に worktree が存在します: $WORKTREE_DIR"
  git -C "$REPO_MAIN" worktree list
  exit 0
fi

if git show-ref --verify --quiet "refs/heads/$LOOP_BRANCH"; then
  echo "ブランチ $LOOP_BRANCH は既存です。それを使って worktree を追加します。"
  git -C "$REPO_MAIN" worktree add "$WORKTREE_DIR" "$LOOP_BRANCH"
else
  git -C "$REPO_MAIN" worktree add "$WORKTREE_DIR" -b "$LOOP_BRANCH"
fi

echo "worktree 作成完了: $WORKTREE_DIR (branch: $LOOP_BRANCH)"
echo "評価実行時は main 側の venv ($REPO_MAIN/venv) をインタプリタとして使うため、"
echo "worktree 側に venv を作る必要はありません(config.env の PYTHON_EXE 参照)。"
