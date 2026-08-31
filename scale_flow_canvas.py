"""OCR/VLMの分岐モデルをTkinter Canvasへ描画する。"""
import tkinter as tk


def _node_size(kind):
    """内部フローノードの半幅・半高を返す。"""
    return (74, 31) if kind == 'decision' else (62, 27)


def draw_scale_flow(canvas, model):
    """条件分岐全体と、今回実際に通った経路をCanvasへ描く。"""
    canvas.delete('all')
    width = max(canvas.winfo_width(), 760)
    graph_height = 205
    positions = {}
    kinds = {}
    for node in model['nodes']:
        positions[node['id']] = (
            16 + node['x'] * (width - 32),
            27 + node['y'] * (graph_height - 34))
        kinds[node['id']] = node['kind']

    canvas.create_text(
        12, 10, anchor=tk.W,
        text='目盛り範囲の判定フロー（青い矢印＝今回通った経路）',
        fill='#cdd6f4', font=('Helvetica', 9, 'bold'))

    for edge in model['edges']:
        source_x, source_y = positions[edge['source']]
        target_x, target_y = positions[edge['target']]
        source_half_w, source_half_h = _node_size(kinds[edge['source']])
        target_half_w, target_half_h = _node_size(kinds[edge['target']])
        if abs(target_x - source_x) >= abs(target_y - source_y):
            direction = 1 if target_x >= source_x else -1
            start = (source_x + direction * source_half_w, source_y)
            end = (target_x - direction * target_half_w, target_y)
        else:
            direction = 1 if target_y >= source_y else -1
            start = (source_x, source_y + direction * source_half_h)
            end = (target_x, target_y - direction * target_half_h)

        route_offset = {'upper': -18, 'lower': 18}.get(edge['route'], 0)
        if route_offset:
            middle_x = (start[0] + end[0]) / 2
            points = (
                start[0], start[1], middle_x, start[1] + route_offset,
                middle_x, end[1] + route_offset, end[0], end[1])
            label_x = middle_x
            label_y = (start[1] + end[1]) / 2 + route_offset
        else:
            points = (start[0], start[1], end[0], end[1])
            label_x = (start[0] + end[0]) / 2
            label_y = (start[1] + end[1]) / 2 - 7

        active = edge['active']
        canvas.create_line(
            *points, smooth=bool(route_offset), arrow=tk.LAST,
            fill='#89b4fa' if active else '#45475a',
            width=3 if active else 1)
        if active:
            text_id = canvas.create_text(
                label_x, label_y, text=edge['label'], fill='#f9e2af',
                font=('Helvetica', 8, 'bold'))
            bbox = canvas.bbox(text_id)
            if bbox:
                background = canvas.create_rectangle(
                    bbox[0] - 2, bbox[1] - 1, bbox[2] + 2, bbox[3] + 1,
                    fill='#11111b', outline='')
                canvas.tag_lower(background, text_id)

    node_colors = {
        'idle': ('#45475a', '#cdd6f4'),
        'running': ('#89b4fa', '#1e1e2e'),
        'ok': ('#a6e3a1', '#1e1e2e'),
        'warn': ('#fab387', '#1e1e2e'),
        'fail': ('#f38ba8', '#1e1e2e'),
        'active': ('#cba6f7', '#1e1e2e'),
        'skipped': ('#585b70', '#cdd6f4'),
    }
    for node in model['nodes']:
        x, y = positions[node['id']]
        half_w, half_h = _node_size(node['kind'])
        fill, text_color = node_colors[node['state']]
        outline = '#f9e2af' if node['state'] == 'active' else '#7f849c'
        if node['kind'] == 'decision':
            canvas.create_polygon(
                x, y - half_h, x + half_w, y,
                x, y + half_h, x - half_w, y,
                fill=fill, outline=outline, width=2)
        else:
            canvas.create_rectangle(
                x - half_w, y - half_h, x + half_w, y + half_h,
                fill=fill, outline=outline, width=2)
        canvas.create_text(
            x, y, text='{}\n{}'.format(node['label'], node['status']),
            fill=text_color, font=('Helvetica', 8, 'bold'),
            justify=tk.CENTER)

    canvas.create_line(12, 218, width - 12, 218, fill='#45475a', width=1)
    for index, note in enumerate(model.get('condition_notes', [])):
        canvas.create_text(
            18, 232 + index * 20, anchor=tk.W, text=note,
            fill='#bac2de', font=('Helvetica', 8))
