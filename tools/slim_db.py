#!/usr/bin/env python3
"""肥大化した SQLite 記録DB (meter_readings) から不要なキーを除去して縮小するツール。

meter_readings テーブルの raw_data_json 列から、肥大化の原因となる
processed_img キー（画素3段配列等）を除去し、DBサイズを切り詰めます。
"""

import argparse
from datetime import datetime
import json
import os
import shutil
import sqlite3
import sys
from typing import Any, Dict, Optional

# プロジェクトルートを sys.path に追加して manager.storage をインポート可能にする
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from manager.storage import _RAW_DATA_EXCLUDE_KEYS


def format_size(bytes_count: int) -> str:
    """バイト数を人間が読みやすい単位（B, KB, MB, GB）に整形する。"""
    if bytes_count < 1024:
        return f"{bytes_count} B"
    elif bytes_count < 1024 * 1024:
        return f"{bytes_count / 1024:.2f} KB"
    elif bytes_count < 1024 * 1024 * 1024:
        return f"{bytes_count / (1024 * 1024):.2f} MB"
    else:
        return f"{bytes_count / (1024 * 1024 * 1024):.2f} GB"


def slim_db(
    db_path: str,
    dry_run: bool = False,
    no_backup: bool = False,
) -> Dict[str, Any]:
    """SQLite DB内の meter_readings.raw_data_json から除外キーを削除してサイズを削減する。

    Args:
        db_path: 対象の SQLite DB ファイルパス。
        dry_run: True の場合、DBを変更せず削減見込みを表示する。
        no_backup: True の場合、実行前のバックアップ作成をスキップする。

    Returns:
        実行結果の要約辞書。
    """
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"指定されたデータベースファイルが存在しません: {db_path}")

    abs_db_path = os.path.abspath(db_path)
    db_dir = os.path.dirname(abs_db_path)
    base_name = os.path.basename(abs_db_path)
    before_size = os.path.getsize(abs_db_path)

    backup_path: Optional[str] = None

    # 1. バックアップの作成（既定、dry-run時は作成しない）
    if not dry_run and not no_backup:
        try:
            total, used, free = shutil.disk_usage(db_dir)
        except Exception as e:
            raise RuntimeError(f"ディスク空き容量の確認に失敗しました: {e}")

        # バックアップ作成に必要な空き容量の確認
        if free < before_size:
            raise RuntimeError(
                f"ディスクの空き容量が不足しています。"
                f"（必要: {format_size(before_size)}, 空き: {format_size(free)}）"
                f"バックアップを作成できないため処理を中止します。"
            )

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(db_dir, f"{base_name}.bak_{timestamp_str}")
        print(f"バックアップを作成中: {backup_path} ...")
        try:
            shutil.copy2(abs_db_path, backup_path)
        except Exception as e:
            raise RuntimeError(f"バックアップ作成中にエラーが発生しました: {e}")
        print(f"バックアップ完了: {backup_path} ({format_size(os.path.getsize(backup_path))})")

    # 2. DB接続と排他チェック
    try:
        conn = sqlite3.connect(abs_db_path, timeout=5.0)
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            raise sqlite3.OperationalError(
                f"データベースが他のプロセス（watch_inbox等）で使用中です: {e}"
            )
        raise

    try:
        cur = conn.cursor()
        # テーブル存在確認
        try:
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='meter_readings'"
            )
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                raise sqlite3.OperationalError(
                    f"データベースが他のプロセス（watch_inbox等）で使用中です: {e}"
                )
            raise

        if not cur.fetchone():
            raise ValueError("データベース内に 'meter_readings' テーブルが見つかりません。")

        # 行ID一覧の取得（全行の生JSONを一度にメモリへ載せないためIDのみ取得）
        try:
            cur.execute("SELECT id FROM meter_readings ORDER BY id ASC")
            row_ids = [row[0] for row in cur.fetchall()]
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                raise sqlite3.OperationalError(
                    f"データベースが他のプロセス（watch_inbox等）で使用中です: {e}"
                )
            raise

        processed_count = 0
        skipped_count = 0
        total_estimated_reduction = 0

        # トランザクション開始（dry-runでない場合）
        if not dry_run:
            conn.execute("BEGIN TRANSACTION")

        read_cur = conn.cursor()
        write_cur = conn.cursor()

        for row_id in row_ids:
            try:
                read_cur.execute(
                    "SELECT raw_data_json FROM meter_readings WHERE id = ?",
                    (row_id,),
                )
                row = read_cur.fetchone()
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower():
                    raise sqlite3.OperationalError(
                        f"データベースが他のプロセス（watch_inbox等）で使用中です: {e}"
                    )
                raise

            if not row:
                skipped_count += 1
                continue

            raw_json_str = row[0]

            # NULL または 空文字列の行は触らない
            if raw_json_str is None or (isinstance(raw_json_str, str) and raw_json_str.strip() == ""):
                skipped_count += 1
                continue

            if not isinstance(raw_json_str, str):
                skipped_count += 1
                continue

            # JSONでない文字列の行は触らない
            try:
                data = json.loads(raw_json_str)
            except Exception:
                skipped_count += 1
                continue

            # 辞書型でない場合は触らない
            if not isinstance(data, dict):
                skipped_count += 1
                continue

            # 除外対象キーが含まれているか確認
            keys_to_remove = [k for k in _RAW_DATA_EXCLUDE_KEYS if k in data]
            if not keys_to_remove:
                # 除外キーがない行は触らない
                skipped_count += 1
                continue

            # キーを除外
            for k in keys_to_remove:
                del data[k]

            new_json_str = json.dumps(data, ensure_ascii=False)

            # 書き換え前に変換後のJSONが読めることを確認
            try:
                json.loads(new_json_str)
            except Exception as e:
                print(
                    f"警告: 行 ID={row_id} の変換後JSON検証(json.loads)に失敗したためスキップします: {e}",
                    file=sys.stderr,
                )
                skipped_count += 1
                continue

            old_bytes = len(raw_json_str.encode("utf-8"))
            new_bytes = len(new_json_str.encode("utf-8"))
            diff_bytes = max(0, old_bytes - new_bytes)
            total_estimated_reduction += diff_bytes

            if dry_run:
                print(
                    f"  [削減見込み] 行 ID={row_id}: "
                    f"{format_size(old_bytes)} -> {format_size(new_bytes)} "
                    f"(削減: {format_size(diff_bytes)}, 除外キー: {', '.join(keys_to_remove)})"
                )
                processed_count += 1
            else:
                try:
                    write_cur.execute(
                        "UPDATE meter_readings SET raw_data_json = ? WHERE id = ?",
                        (new_json_str, row_id),
                    )
                    processed_count += 1
                except sqlite3.OperationalError as e:
                    if "locked" in str(e).lower():
                        raise sqlite3.OperationalError(
                            f"データベースが他のプロセス（watch_inbox等）で使用中です: {e}"
                        )
                    raise

        # トランザクション完了と VACUUM
        if not dry_run:
            conn.commit()
            print("全行の更新をコミットしました。VACUUM を実行中...")
            try:
                conn.execute("VACUUM")
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower():
                    raise sqlite3.OperationalError(
                        f"データベースが他のプロセス（watch_inbox等）で使用中です: {e}"
                    )
                raise
            print("VACUUM が完了しました。")

        conn.close()

    except Exception:
        if not dry_run:
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
        raise

    after_size = os.path.getsize(abs_db_path) if not dry_run else before_size

    # 結果表示
    print("\n=== 実行結果 ===")
    if dry_run:
        print("【DRY-RUN モード】DBへの書き込みは行われていません。")
        print(f"処理対象行数: {processed_count} 行")
        print(f"スキップ行数: {skipped_count} 行")
        print(f"削減見込み合計: {format_size(total_estimated_reduction)}")
    else:
        print(f"処理した行数: {processed_count} 行")
        print(f"スキップした行数: {skipped_count} 行")
        print(f"実行前ファイルサイズ: {format_size(before_size)} ({before_size:,} bytes)")
        print(f"実行後ファイルサイズ: {format_size(after_size)} ({after_size:,} bytes)")
        reduction_bytes = max(0, before_size - after_size)
        percent = (reduction_bytes / before_size * 100) if before_size > 0 else 0
        print(f"削減量: {format_size(reduction_bytes)} ({reduction_bytes:,} bytes, {percent:.1f}% 削減)")
        if backup_path:
            print(f"作成されたバックアップ: {backup_path}")

    return {
        "processed_count": processed_count,
        "skipped_count": skipped_count,
        "before_size": before_size,
        "after_size": after_size,
        "backup_path": backup_path,
        "estimated_reduction": total_estimated_reduction,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="肥大化した SQLite 記録DB (meter_readings) から不要なキーを除去して縮小するツール"
    )
    parser.add_argument("db_path", help="対象 SQLite データベースファイルのパス")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DBを書き換えずに削減見込みサイズと行数を表示する",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="実行前の自動バックアップ作成をスキップする",
    )

    args = parser.parse_args()

    try:
        slim_db(
            db_path=args.db_path,
            dry_run=args.dry_run,
            no_backup=args.no_backup,
        )
        return 0
    except sqlite3.OperationalError as e:
        print(f"\nエラー: {e}", file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"\nエラー: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"\n予期しないエラーが発生しました: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
