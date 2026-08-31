"""OCR/VLM診断データをTkinterの表・ログ向けに整形する。"""


def _value(value):
    return '-' if value is None else '{:.4g}'.format(value)


_FLOW_NODES = (
    ('ocr_detect', 'OCR数字検出', 'process', 0.07, 0.50),
    ('ocr_check', '前処理4条件\n一致判定', 'decision', 0.25, 0.50),
    ('vlm_detect', 'VLM検出', 'process', 0.45, 0.50),
    ('compare', 'OCR/VLM候補\n一致?', 'decision', 0.64, 0.27),
    ('verify', 'VLM候補位置\n確認?', 'decision', 0.64, 0.73),
    ('adopt_ocr', 'OCR候補を採用', 'outcome', 0.87, 0.18),
    ('adopt_vlm', 'VLM候補を採用', 'outcome', 0.87, 0.50),
    ('manual', '手動選択へ', 'outcome', 0.87, 0.82),
)

_FLOW_EDGES = (
    ('ocr_to_check', 'ocr_detect', 'ocr_check', '数字候補', 'straight'),
    ('check_stable_to_vlm', 'ocr_check', 'vlm_detect', '安定', 'upper'),
    ('check_unstable_to_vlm', 'ocr_check', 'vlm_detect',
     '不安定/未検出', 'lower'),
    ('vlm_stable_to_compare', 'vlm_detect', 'compare',
     '照合', 'straight'),
    ('vlm_fallback_to_verify', 'vlm_detect', 'verify',
     'fallback', 'straight'),
    ('vlm_unavailable_to_ocr', 'vlm_detect', 'adopt_ocr',
     '未取得＋OCR候補あり', 'upper'),
    ('vlm_unavailable_to_manual', 'vlm_detect', 'manual',
     '両方未検出', 'lower'),
    ('compare_agree_to_ocr', 'compare', 'adopt_ocr', '一致', 'straight'),
    ('compare_disagree_to_verify', 'compare', 'verify', '不一致', 'straight'),
    ('verify_ok_to_vlm', 'verify', 'adopt_vlm', '位置確認OK', 'straight'),
    ('verify_ng_to_ocr', 'verify', 'adopt_ocr',
     '確認NG＋OCR候補あり', 'upper'),
    ('verify_ng_to_manual', 'verify', 'manual',
     '確認NG＋OCR候補なし', 'lower'),
)


def build_scale_flow_model(auto_scale, diagnostics=None, running=False):
    """診断結果から、分岐図のノード状態と今回通った矢印を作る。"""
    diagnostics = diagnostics or (auto_scale or {}).get('diagnostics') or {}
    ocr = diagnostics.get('ocr') or {}
    vlm = diagnostics.get('vlm') or {}
    decision = diagnostics.get('decision') or {}
    has_diagnostics = bool(diagnostics)

    ocr_available = bool(ocr.get('available'))
    ocr_stable = bool(ocr.get('stable'))
    vlm_enabled = bool(vlm.get('enabled'))
    vlm_available = bool(vlm.get('available'))
    relation = decision.get('relation')
    adopted_vlm = 'vlm' in (
        decision.get('min_source'), decision.get('max_source'))
    source = (auto_scale or {}).get('source')

    active_edges = set()
    if has_diagnostics:
        active_edges.add('ocr_to_check')
        active_edges.add(
            'check_stable_to_vlm' if ocr_stable else 'check_unstable_to_vlm')
        if not vlm_available:
            active_edges.add(
                'vlm_unavailable_to_ocr' if ocr_available
                else 'vlm_unavailable_to_manual')
        elif ocr_stable:
            active_edges.add('vlm_stable_to_compare')
            if relation == 'agree':
                active_edges.add('compare_agree_to_ocr')
            else:
                active_edges.add('compare_disagree_to_verify')
                active_edges.add(
                    'verify_ok_to_vlm' if adopted_vlm
                    else ('verify_ng_to_ocr' if ocr_available
                          else 'verify_ng_to_manual'))
        else:
            active_edges.add('vlm_fallback_to_verify')
            active_edges.add(
                'verify_ok_to_vlm' if adopted_vlm
                else ('verify_ng_to_ocr' if ocr_available
                      else 'verify_ng_to_manual'))

    number_count = len(ocr.get('numbers') or [])
    node_status = {
        'ocr_detect': (
            ('実行中', 'running') if running and not has_diagnostics else
            ('成功: {}件'.format(number_count), 'ok') if ocr_available else
            ('未検出', 'fail') if has_diagnostics else ('未実行', 'idle')),
        'ocr_check': (
            ('一致', 'ok') if ocr_stable else
            ('不一致', 'warn') if ocr_available else
            ('判定不可', 'fail') if has_diagnostics else ('未実行', 'idle')),
        'vlm_detect': (
            ('無効', 'skipped') if has_diagnostics and not vlm_enabled else
            ('成功', 'ok') if vlm_available else
            ('未取得', 'fail') if has_diagnostics else ('未実行', 'idle')),
        'compare': (
            ('一致', 'ok') if relation == 'agree' else
            ('不一致', 'warn') if relation == 'disagree' else
            ('対象外', 'skipped') if has_diagnostics else ('未実行', 'idle')),
        'verify': (
            ('確認OK', 'ok') if 'verify_ok_to_vlm' in active_edges else
            ('確認NG', 'warn') if any(
                edge in active_edges for edge in
                ('verify_ng_to_ocr', 'verify_ng_to_manual')) else
            ('対象外', 'skipped') if has_diagnostics else ('未実行', 'idle')),
        'adopt_ocr': (
            ('一部採用', 'active') if source == 'hybrid' else
            ('今回の採用先', 'active') if source == 'ocr_tick' else
            ('未採用', 'idle')),
        'adopt_vlm': (
            ('一部採用', 'active') if source == 'hybrid' else
            ('今回の採用先', 'active') if source == 'vlm' else
            ('未採用', 'idle')),
        'manual': (
            ('今回の移行先', 'active') if has_diagnostics and auto_scale is None else
            ('未移行', 'idle')),
    }

    nodes = [
        {'id': node_id, 'label': label, 'kind': kind, 'x': x, 'y': y,
         'status': node_status[node_id][0], 'state': node_status[node_id][1]}
        for node_id, label, kind, x, y in _FLOW_NODES
    ]
    edges = [
        {'id': edge_id, 'source': source_id, 'target': target_id,
         'label': label, 'route': route, 'active': edge_id in active_edges}
        for edge_id, source_id, target_id, label, route in _FLOW_EDGES
    ]
    return {
        'nodes': nodes,
        'edges': edges,
        'condition_notes': [
            '1. OCR安定 → VLMで照合 ／ 不安定・未検出 → VLMフォールバック判定',
            '2. VLM未取得 → OCR候補ありならOCR採用 ／ 両方なしなら手動選択',
            '3. 候補不一致 → VLM候補の位置確認 ／ OKならVLM補完、NGならOCRまたは手動',
        ],
    }


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
