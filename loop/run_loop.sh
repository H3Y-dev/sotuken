#!/usr/bin/env bash
#
# loop/run_loop.sh — Evaluator-Optimizer loop for メーター読み取り精度改善
#
# 生成者(GENERATOR) = Codex (gpt-5.6-terra, ai-cli-mcp を介さずCLI直叩き。会話履歴あり)
# 検証者(EVALUATOR)  = evaluate.py + loop/check_exit.py (決定的・数値閾値判定。LLM判断なし)
#
# ガードレール:
#   1. 検証可能な終了条件: mean_reference_error < THRESHOLD_MEAN_REF_ERROR (loop/check_exit.py)
#   2. 最大反復回数: MAX_ITERS (for ループでハード制御)
#   3. 予算上限: BUDGET_ITERS (形式チェック。実質はMAX_ITERSと同じ値で反復回数が上限として機能)
#   4. サンドボックス: git worktree ($WORKTREE_DIR) 上の $LOOP_BRANCH でのみ変更・コミット
#   5. 人間チェックポイント: mainへの反映(マージ/PR)はしない。ユーザーが手動で行う。
#
# 使い方:
#   bash loop/setup_worktree.sh   # 初回のみ: worktree作成
#   bash loop/run_loop.sh         # ループ実行
#
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source loop/config.env

if [[ ! -d "$WORKTREE_DIR" ]]; then
  echo "worktree が見つかりません。先に loop/setup_worktree.sh を実行してください。" >&2
  exit 2
fi

RUN_ID="$(date +%Y%m%d_%H%M%S)"
RUN_DIR="loop/runs/$RUN_ID"
mkdir -p "$RUN_DIR"
echo "run dir: $RUN_DIR"

feedback="(初回ラウンドです。前ラウンドの結果はありません。)"
spent_iters=0

pass=0
for ((i = 1; i <= MAX_ITERS; i++)); do
  echo "=== Round $i/$MAX_ITERS (budget iters used: $spent_iters/$BUDGET_ITERS) ==="

  # --- ガードレール#3: 予算チェック(形式的。実質MAX_ITERSと同義) ---
  if (( spent_iters >= BUDGET_ITERS )); then
    echo "予算上限(BUDGET_ITERS=$BUDGET_ITERS)に到達したため停止します。" >&2
    exit 2
  fi

  # --- プロンプト組み立て ---
  prompt_file="$RUN_DIR/prompt_round${i}.md"
  sed -e "s#{{PYTHON_EXE}}#$PYTHON_EXE#g" \
      -e "s#{{EVAL_SCRIPT}}#$EVAL_SCRIPT#g" \
      -e "s#{{GROUNDTRUTH}}#$GROUNDTRUTH#g" \
      loop/generator_prompt.md > "$prompt_file.tmp"
  # {{FEEDBACK}} は複数行になり得るので awk で置換(sedの区切り文字衝突を避ける)
  awk -v fb="$feedback" '{ gsub(/{{FEEDBACK}}/, fb); print }' "$prompt_file.tmp" > "$prompt_file"
  rm -f "$prompt_file.tmp"

  # --- GENERATOR: Codex ---
  gen_log="$RUN_DIR/codex_round${i}.log"
  echo "--- Codex 実行中 (round $i) ---"
  if [[ "$i" -eq 1 ]]; then
    "$CODEX_EXE" exec \
      -C "$WORKTREE_DIR" \
      -s workspace-write \
      --skip-git-repo-check \
      -m "$CODEX_MODEL" \
      - < "$prompt_file" | tee "$gen_log"
  else
    "$CODEX_EXE" exec resume --last \
      -C "$WORKTREE_DIR" \
      -s workspace-write \
      --skip-git-repo-check \
      -m "$CODEX_MODEL" \
      - < "$prompt_file" | tee "$gen_log"
  fi

  # --- EVALUATOR: evaluate.py (決定的、LLMなし) ---
  report_file="eval/report_loop_round${i}.json"
  echo "--- evaluate.py 実行中 (round $i) ---"
  ( cd "$WORKTREE_DIR" && "$PYTHON_EXE" "$EVAL_SCRIPT" "$GROUNDTRUTH" --no-vlm --scope "$EVAL_SCOPE" -o "$report_file" ) \
    | tee "$RUN_DIR/evaluate_round${i}.log"

  # --- 判定 ---
  verdict_line="$("$PYTHON_EXE" loop/check_exit.py "$WORKTREE_DIR/$report_file" "$THRESHOLD_MEAN_REF_ERROR")" \
    && rc=0 || rc=$?
  echo "$verdict_line" | tee "$RUN_DIR/verdict_round${i}.txt"

  spent_iters=$((spent_iters + 1))

  if [[ "$rc" -eq 0 ]]; then
    echo "PASS: round $i で目標達成。 $verdict_line"
    echo "worktree: $WORKTREE_DIR (branch: $LOOP_BRANCH)"
    ( cd "$WORKTREE_DIR" && git add -A && git commit -m "loop: round ${i} で目標達成 ($verdict_line)" )
    echo "コミット済み。mainへの反映は手動で確認・マージしてください(このループは自動マージしません)。"

    # --- ガードレール#6(新設): 数値だけで合格にしない。目盛りの目視確認用オーバーレイを生成する ---
    overlay_dir="eval/overlays_loop_round${i}"
    echo "--- 目視確認用オーバーレイ生成中 (round $i) ---"
    ( cd "$WORKTREE_DIR" && "$PYTHON_EXE" tools_render_overlays.py "$GROUNDTRUTH" --no-vlm --scope "$EVAL_SCOPE" -o "$overlay_dir" ) \
      | tee "$RUN_DIR/overlays_round${i}.log"
    echo "オーバーレイ: $WORKTREE_DIR/$overlay_dir"
    echo "【重要】このループは数値判定のみで自動PASSしている。マージ前に必ず人(Claude/本人)が"
    echo "上記オーバーレイ画像を目視確認すること。恒久指示7章のチェックリスト参照。"
    pass=1
    break
  elif [[ "$rc" -eq 1 ]]; then
    echo "FAIL: round $i は未達。次ラウンドへ。 $verdict_line"
    feedback="前ラウンド($i)の結果: $verdict_line
report: $WORKTREE_DIR/$report_file
上記を踏まえ、誤差の大きい/failure_stageが立っている画像を優先して直してください。"
    # worktree の変更を進捗として一旦コミット(人間が経緯を追えるように。mainには繋がらない)
    ( cd "$WORKTREE_DIR" && git add -A && git commit -m "loop: round ${i} 試行 ($verdict_line)" --allow-empty -q ) || true
  else
    echo "ERROR: check_exit.py が異常終了しました(rc=$rc)。report.jsonを確認してください。" >&2
    exit 2
  fi
done

if [[ "$pass" -ne 1 ]]; then
  echo "=== MAX_ITERS=$MAX_ITERS に到達し、目標未達で終了しました ==="
  echo "最後のreport: $WORKTREE_DIR/eval/report_loop_round${MAX_ITERS}.json"
  echo "ログ: $RUN_DIR"

  # 未達でも、最後の状態を目視確認できるようオーバーレイは生成しておく
  overlay_dir="eval/overlays_loop_round${MAX_ITERS}"
  ( cd "$WORKTREE_DIR" && "$PYTHON_EXE" tools_render_overlays.py "$GROUNDTRUTH" --no-vlm --scope "$EVAL_SCOPE" -o "$overlay_dir" ) \
    | tee "$RUN_DIR/overlays_round${MAX_ITERS}.log" || true
  echo "オーバーレイ(未達時点): $WORKTREE_DIR/$overlay_dir"
  exit 3
fi

exit 0
