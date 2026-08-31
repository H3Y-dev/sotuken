"""OCR/VLM診断データをTkinterの表・ログ向けに整形する。"""


def _value(value):
    return '-' if value is None else '{:.4g}'.format(value)


def build_scale_debug_view(auto_scale, numbers, diagnostics=None):
    """OCR/VLM診断データを、GUIの表とログへそのまま渡せる形に整える。"""
    diagnostics = diagnostics or (auto_scale or {}).get('diagnostics') or {}
    ocr = diagnostics.get('ocr') or {}
    vlm = diagnostics.get('vlm') or {}
    decision = diagnostics.get('decision') or {}

    if ocr.get('available'):
        ocr_status = '安定' if ocr.get('stable') else '低信頼（試行間で不一致）'
    else:
        ocr_status = '未検出'

    relation_labels = {
        'agree': 'OCRと一致',
        'disagree': 'OCRと不一致',
        'ocr_unavailable': 'OCR未検出',
        'vlm_unavailable': '未検出',
        'disabled': '未実行（無効）',
        'no_result': '未検出',
    }
    if not vlm.get('enabled'):
        vlm_status = '未実行（無効）'
    elif not vlm.get('available'):
        vlm_status = '未検出'
    else:
        vlm_status = relation_labels.get(decision.get('relation'), '実行済み')

    source_labels = {'ocr': 'OCR', 'vlm': 'LLM', None: '-'}
    min_source = source_labels.get(decision.get('min_source'), decision.get('min_source', '-'))
    max_source = source_labels.get(decision.get('max_source'), decision.get('max_source', '-'))
    fallback = 'あり' if decision.get('fallback_used') else 'なし'
    summary = '採用元: 最小={} / 最大={}　フォールバック: {}'.format(
        min_source, max_source, fallback)

    final_status = '採用なし' if auto_scale is None else '最小={} / 最大={}'.format(
        min_source, max_source)
    decision_rows = [
        ('OCR', _value(ocr.get('min_value')),
         _value(ocr.get('max_value')), ocr_status),
        ('LLM', _value(vlm.get('min_value')),
         _value(vlm.get('max_value')), vlm_status),
        ('最終採用', _value((auto_scale or {}).get('min_value')),
         _value((auto_scale or {}).get('max_value')), final_status),
    ]
    ocr_rows = [
        (str(index), _value(number.get('value')),
         '{:.2f}'.format(number.get('score', 0.0)),
         '({}, {})'.format(int(round(number.get('x', 0.0))),
                           int(round(number.get('y', 0.0)))))
        for index, number in enumerate(numbers, 1)
    ]

    trace_lines = []
    if numbers:
        for index, number in enumerate(numbers, 1):
            trace_lines.append(
                'OCR検出[{}]: 値={} 信頼度={:.2f} 位置=({}, {})'.format(
                    index, _value(number.get('value')),
                    number.get('score', 0.0),
                    int(round(number.get('x', 0.0))),
                    int(round(number.get('y', 0.0)))))
    else:
        trace_lines.append('OCR検出数字: なし')
    for attempt in ocr.get('attempts', []):
        trace_lines.append(
            'OCR試行[{}]: 最小={} 最大={} 対応={}/{}点'.format(
                attempt.get('label', '?'), _value(attempt.get('min_value')),
                _value(attempt.get('max_value')), attempt.get('n_used', 0),
                attempt.get('n_total', 0)))
    trace_lines.append('OCR候補: 最小={} 最大={} ({})'.format(
        _value(ocr.get('min_value')), _value(ocr.get('max_value')), ocr_status))
    trace_lines.append('LLM候補: 最小={} 最大={} ({})'.format(
        _value(vlm.get('min_value')), _value(vlm.get('max_value')), vlm_status))
    if decision.get('relation') == 'agree':
        trace_lines.append('OCRとLLMの候補範囲は一致')
    elif decision.get('relation') == 'disagree':
        trace_lines.append('OCRとLLMの候補範囲は不一致')
    trace_lines.append(summary)
    if decision.get('reason'):
        trace_lines.append('採用理由: {}'.format(decision['reason']))
    return {
        'summary': summary,
        'decision_rows': decision_rows,
        'ocr_rows': ocr_rows,
        'trace_lines': trace_lines,
    }
