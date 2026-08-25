"""
評価用の正解データ（eval/groundtruth.json）を作るための補助GUIツール。

真値（true_value）を目分量で入力すると誤差が入りやすい。このツールでは
「中心・ゼロ点・フルスケール点・針先」の4点をクリックするだけで、
既存の meter_reader.arc_ratio / ratio_to_value（GUIも評価基盤も使うのと
同じ関数）を通して真値を計算する。読み取りロジックが本番と同一なので、
人が数値を手で決めるよりばらつきが小さく、根拠も明確になる。

  実行:
      venv\\Scripts\\python.exe label_tool.py

使い方:
  1. 「画像を開く」で対象の写真を選ぶ
  2. 画面の案内に従って4点を順にクリックする
     （中心 → ゼロ点の目盛り → フルスケールの目盛り → 針の先端）
  3. 最小値・最大値を入力する（銘板に書かれている値。例: 0 と 150）
  4. 計算された真値を確認し、問題なければ「groundtruth.jsonに追記」を押す

注意:
  - 針は「細く長い側」が指示側。太く短い側（尾）ではない
  - 自信が持てない画像は追記せず、true_value を null のまま残すこと
    （誤ったラベルは、ラベルが無いことより有害）
"""
import json
import math
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

import meter_reader

GROUNDTRUTH_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'eval', 'groundtruth.json')

# クリックで指定する4点。順番どおりに案内する
STEPS = [
    ('center', '中心（針の回転軸）をクリックしてください'),
    ('zero', 'ゼロ点（最小値）の目盛りをクリックしてください'),
    ('full', 'フルスケール（最大値）の目盛りをクリックしてください'),
    ('needle', '針の先端をクリックしてください（細く長い側。太い尾ではない）'),
]

POINT_COLORS = {
    'center': (0, 230, 255),
    'zero': (0, 255, 0),
    'full': (255, 0, 255),
    'needle': (0, 0, 255),
}

MAX_CANVAS_W = 1000
MAX_CANVAS_H = 700


def imread_ja(path):
    """全角パス対応の画像読み込み。"""
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


class LabelTool:

    def __init__(self, root):
        self.root = root
        self.root.title('正解データ作成ツール（groundtruth ラベリング）')

        self.image_path = None
        self.image = None          # 元解像度のBGR画像
        self.scale = 1.0           # 表示倍率（元画像→キャンバス）
        self.points = {}           # {'center': (x, y), ...} 元画像座標
        self.step_index = 0
        self.photo = None

        self._build_ui()

    # ── UI 構築 ──────────────────────────────────────────────
    def _build_ui(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill=tk.X)

        ttk.Button(top, text='画像を開く', command=self.open_image).pack(side=tk.LEFT)
        ttk.Button(top, text='やり直す', command=self.reset_points).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(top, text='1点戻る', command=self.undo_point).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Label(top, text='最小値:').pack(side=tk.LEFT, padx=(18, 2))
        self.min_var = tk.StringVar(value='0')
        ttk.Entry(top, textvariable=self.min_var, width=8).pack(side=tk.LEFT)

        ttk.Label(top, text='最大値:').pack(side=tk.LEFT, padx=(10, 2))
        self.max_var = tk.StringVar(value='')
        ttk.Entry(top, textvariable=self.max_var, width=8).pack(side=tk.LEFT)

        ttk.Button(top, text='真値を計算', command=self.compute).pack(side=tk.LEFT, padx=(14, 0))

        self.canvas = tk.Canvas(self.root, bg='#222', width=MAX_CANVAS_W, height=MAX_CANVAS_H)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind('<Button-1>', self.on_click)

        bottom = ttk.Frame(self.root, padding=8)
        bottom.pack(fill=tk.X)

        self.status_var = tk.StringVar(value='「画像を開く」から対象の写真を選んでください')
        ttk.Label(bottom, textvariable=self.status_var).pack(side=tk.LEFT)

        self.result_var = tk.StringVar(value='')
        ttk.Label(bottom, textvariable=self.result_var,
                  font=('', 10, 'bold')).pack(side=tk.LEFT, padx=(18, 0))

        ttk.Button(bottom, text='groundtruth.jsonに追記',
                   command=self.append_to_groundtruth).pack(side=tk.RIGHT)

        ttk.Label(self.root, padding=(8, 0, 8, 8),
                  text=('メモ: 針は細く長い側が指示側。自信が持てない画像は追記せず、'
                        'true_value を null のまま残してください'),
                  foreground='#666').pack(fill=tk.X)

    # ── 画像の読み込み・表示 ──────────────────────────────────
    def open_image(self):
        path = filedialog.askopenfilename(
            title='メーター画像を選択',
            filetypes=[('画像', '*.jpg *.jpeg *.png *.JPG *.JPEG *.PNG'), ('すべて', '*.*')])
        if not path:
            return

        img = imread_ja(path)
        if img is None:
            messagebox.showerror('読み込み失敗', '画像を読み込めませんでした:\n%s' % path)
            return

        self.image_path = path
        self.image = img
        self.points = {}
        self.step_index = 0
        self.result_var.set('')

        h, w = img.shape[:2]
        self.scale = min(MAX_CANVAS_W / float(w), MAX_CANVAS_H / float(h), 1.0)
        self.canvas.config(width=int(w * self.scale), height=int(h * self.scale))

        self._render()
        self._update_status()

    def _render(self):
        if self.image is None:
            return

        overlay = self.image.copy()
        cx = self.points.get('center')

        for name, pt in self.points.items():
            color = POINT_COLORS[name]
            cv2.circle(overlay, pt, 7, color, -1)
            cv2.drawMarker(overlay, pt, color, cv2.MARKER_CROSS, 26, 2)
            # 中心から各点へ線を引くと、角度の関係が目で確認できる
            if cx is not None and name != 'center':
                cv2.line(overlay, cx, pt, color, 2)

        h, w = overlay.shape[:2]
        disp = cv2.resize(overlay, (int(w * self.scale), int(h * self.scale)),
                          interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
        self.photo = ImageTk.PhotoImage(Image.fromarray(rgb))
        self.canvas.delete('all')
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)

    def _update_status(self):
        if self.step_index < len(STEPS):
            _, message = STEPS[self.step_index]
            self.status_var.set('[%d/%d] %s' % (self.step_index + 1, len(STEPS), message))
        else:
            self.status_var.set('4点すべて指定済み。最小値・最大値を入れて「真値を計算」を押してください')

    # ── クリック処理 ─────────────────────────────────────────
    def on_click(self, event):
        if self.image is None or self.step_index >= len(STEPS):
            return

        x = int(event.x / self.scale)
        y = int(event.y / self.scale)
        name, _ = STEPS[self.step_index]
        self.points[name] = (x, y)
        self.step_index += 1

        self._render()
        self._update_status()

        if self.step_index == len(STEPS):
            self.compute()

    def reset_points(self):
        self.points = {}
        self.step_index = 0
        self.result_var.set('')
        self._render()
        self._update_status()

    def undo_point(self):
        if self.step_index == 0:
            return
        self.step_index -= 1
        name, _ = STEPS[self.step_index]
        self.points.pop(name, None)
        self.result_var.set('')
        self._render()
        self._update_status()

    # ── 真値の計算 ───────────────────────────────────────────
    def _read_range(self):
        try:
            val_min = float(self.min_var.get())
            val_max = float(self.max_var.get())
        except ValueError:
            messagebox.showwarning('入力エラー', '最小値・最大値には数値を入れてください')
            return None
        if val_max == val_min:
            messagebox.showwarning('入力エラー', '最小値と最大値が同じです')
            return None
        return val_min, val_max

    def compute(self):
        if len(self.points) < len(STEPS):
            messagebox.showinfo('未完了', '4点すべてをクリックしてください')
            return None

        rng = self._read_range()
        if rng is None:
            return None
        val_min, val_max = rng

        cx, cy = self.points['center']

        def angle_of(name):
            px, py = self.points[name]
            return math.atan2(py - cy, px - cx)

        # 本番と同じ meter_reader の関数を通す。ここで独自計算をしてしまうと
        # 評価基盤の値とラベルの根拠がずれてしまうため
        ratio = meter_reader.arc_ratio(
            angle_of('needle'), angle_of('zero'), angle_of('full'))
        value = meter_reader.ratio_to_value(ratio, val_min, val_max)

        self.computed = {
            'value': value,
            'ratio': ratio,
            'val_min': val_min,
            'val_max': val_max,
        }
        self.result_var.set('真値 = %.2f （スケール上の位置 %.1f%%）' % (value, ratio * 100.0))
        return self.computed

    # ── groundtruth.json への追記 ────────────────────────────
    def append_to_groundtruth(self):
        computed = self.compute()
        if computed is None:
            return

        entry_image = self.image_path.replace('\\', '/')

        try:
            with open(GROUNDTRUTH_PATH, encoding='utf-8') as f:
                data = json.load(f)
        except (IOError, ValueError) as exc:
            messagebox.showerror('読み込み失敗',
                                 'groundtruth.json を読めませんでした:\n%s' % exc)
            return

        existing = None
        for entry in data:
            if entry.get('image', '').replace('\\', '/') == entry_image:
                existing = entry
                break

        value = round(computed['value'], 2)

        if existing is not None:
            old = existing.get('true_value')
            if not messagebox.askyesno(
                    '上書き確認',
                    ('この画像は既に登録されています。\n\n'
                     '現在の true_value: %s\n新しい true_value: %s\n\n上書きしますか？')
                    % (old, value)):
                return
            existing['true_value'] = value
            existing['min_value'] = computed['val_min']
            existing['max_value'] = computed['val_max']
        else:
            data.append({
                'image': entry_image,
                'true_value': value,
                'min_value': computed['val_min'],
                'max_value': computed['val_max'],
                'note': 'label_tool.py で4点クリックから算出',
            })

        try:
            with open(GROUNDTRUTH_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write('\n')
        except IOError as exc:
            messagebox.showerror('保存失敗', 'groundtruth.json を保存できませんでした:\n%s' % exc)
            return

        self.status_var.set('groundtruth.json に保存しました: true_value = %.2f' % value)
        messagebox.showinfo('保存しました',
                            'true_value = %.2f として保存しました。\n\n%s'
                            % (value, GROUNDTRUTH_PATH))


def main():
    root = tk.Tk()
    LabelTool(root)
    root.mainloop()


if __name__ == '__main__':
    main()
