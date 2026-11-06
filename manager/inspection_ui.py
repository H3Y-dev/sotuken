"""点検結果の画面用ロジック。app.py はここを呼ぶだけにする。"""

from datetime import datetime

from manager import export
from manager.devices import list_devices
from manager.inspection import create_inspection, export_inspection

PREVIEW_COLUMNS = ['機器番号', '機器名', '測定値', '単位', '測定方法', '読取状態', '要確認理由', '撮影日時']


def default_inspection_id(now=None):
    return 'INS-' + (now or datetime.now()).strftime('%Y%m%d-%H%M')


def device_choices(storage):
    """devices表から {機器番号: 表示ラベル} を機器番号順で返す。"""
    return {row['device_id']: f"{row['device_id']}  {row.get('device_name') or ''}".strip()
            for row in sorted(list_devices(storage), key=lambda row: row['device_id'])}


def inspection_output_dir():
    # 簡易点検CSVと同じ出力先規約（export側の documents dir 配下）
    return export._documents_dir() / 'メーター点検'


def preview_inspection(storage, inspection_id, date_from, date_to, device_ids):
    """期間と対象を固定した点検結果と、画面用の表行を返す。"""
    result = create_inspection(storage, inspection_id, date_from, date_to, device_ids)
    table = [{column: row.get(column) for column in PREVIEW_COLUMNS} for row in result['rows']]
    return result, table


def missing_devices(result):
    """期間内に撮影が無かった対象機器。"""
    seen = {row['機器番号'] for row in result['rows']}
    return [device_id for device_id in result['manifest']['device_ids'] if device_id not in seen]


def save_inspection(result, output_dir=None):
    """点検結果CSV・履歴CSV・manifestを保存し、パスの辞書を返す。同名は上書きしない。"""
    return export_inspection(result, output_dir if output_dir is not None else inspection_output_dir())
