"""
評価用の正解データ（eval/groundtruth.json および eval/labels/<担当者名>.json）を作るための補助GUIツール。
"""
from datetime import datetime
import json
import math
import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

import meter_reader

GROUNDTRUTH_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'eval', 'groundtruth.json')
LABELS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'eval', 'labels')

STEPS = [
    ('center', '① 中心（針の回転軸）をクリックしてください'),
    ('zero', '② 0点（最小値）の目盛りをクリックしてください'),
    ('full', '③ 満尺点（最大値）の目盛りをクリックしてください'),
    ('needle', '④ 針の先端をクリックしてください（細く長い側。太い尾ではない）'),
    ('numbered_ticks', '⑤ 数字が書いてある目盛りの線を順にクリックし、その数字を入力してください。\n終わったら『数字の入力を終える』を押してください'),
]

POINT_COLORS = {
    'center': (0, 230, 255),
    'zero': (0, 255, 0),
    'full': (255, 0, 255),
    'needle': (0, 0, 255),
    'tick': (255, 255, 0),
}

MAX_CANVAS_W = 900
MAX_CANVAS_H = 650
MAG_SIZE = 60
MAG_SCALE = 4
MAG_CANVAS_SIZE = MAG_SIZE * MAG_SCALE


def imread_ja(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def build_label_record(image_path, image_size, points, numbered_ticks, form, computed):
    labeler = form.get("labeler", "").strip()
    if not labeler:
        return None

    unlabelable = bool(form.get("unlabelable", False))

    def parse_opt_float(val):
        if val is None or val == "":
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def parse_opt_num(val):
        if val is None or val == "":
            return None
        try:
            f = float(val)
            return int(f) if f.is_integer() else f
        except (ValueError, TypeError):
            return None

    if unlabelable:
        true_val = None
        pts_data = None
    else:
        true_val = computed.get("true_value")
        pts_data = {
            "center": list(points["center"]) if points.get("center") else None,
            "zero_pt": list(points["zero"]) if points.get("zero") else None,
            "full_pt": list(points["full"]) if points.get("full") else None,
            "needle_tip": list(points["needle"]) if points.get("needle") else None,
            "numbered_ticks": numbered_ticks or []
        }

    norm_path = os.path.normpath(image_path).replace("\\", "/")

    record = {
        "image": norm_path,
        "image_size": [int(image_size[0]), int(image_size[1])],
        "coord_system": "raw_imdecode",
        "labeler": labeler,
        "labeled_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "meter_id": str(form.get("meter_id", "")).strip(),
        "condition": str(form.get("condition", "正面")),
        "scope": str(form.get("scope", "round")),
        "unit": str(form.get("unit", "")).strip(),
        "major_step": parse_opt_num(form.get("major_step")),
        "min_value": parse_opt_float(form.get("min_value")),
        "max_value": parse_opt_float(form.get("max_value")),
        "true_value": true_val,
        "eye_value": parse_opt_float(form.get("eye_value")),
        "unlabelable": unlabelable,
        "points": pts_data
    }
    return record


class LabelTool:

    def __init__(self, root):
        self.root = root
        self.root.title('正解データ作成ツール（詳細ラベリング対応版）')

        self.image_path = None
        self.image = None
        self.scale = 1.0
        self.points = {}
        self.numbered_ticks = []
        self.step_index = 0
        self.photo = None
        self.mag_photo = None

        self._build_ui()

    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding=6)
        main_frame.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right_frame = ttk.Frame(main_frame, width=320, padding=8)
        right_frame.pack(side=tk.RIGHT, fill=tk.Y)

        top = ttk.Frame(left_frame, padding=4)
        top.pack(fill=tk.X)

        ttk.Button(top, text='画像を開く', command=self.load_image).pack(side=tk.LEFT, padx=4)
        self.lbl_info = ttk.Label(top, text='「画像を開く」を押してください', font=('Yu Gothic UI', 10, 'bold'))
        self.lbl_info.pack(side=tk.LEFT, padx=8)

        ttk.Button(top, text='1つ戻す', command=self.undo_point).pack(side=tk.RIGHT, padx=4)

        self.canvas = tk.Canvas(left_frame, bg='#333333', cursor='crosshair')
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind('<Button-1>', self.on_click)
        self.canvas.bind('<Motion>', self.on_mouse_move)

        lbl_mag_title = ttk.Label(right_frame, text='【拡大表示（4倍）】', font=('Yu Gothic UI', 9, 'bold'))
        lbl_mag_title.pack(anchor=tk.W, pady=(0, 2))
        
        self.mag_canvas = tk.Canvas(right_frame, width=MAG_CANVAS_SIZE, height=MAG_CANVAS_SIZE, bg='black', highlightthickness=1, highlightbackground='gray')
        self.mag_canvas.pack(anchor=tk.W, pady=(0, 10))

        form_frame = ttk.LabelFrame(right_frame, text=' メタデータ入力 ', padding=8)
        form_frame.pack(fill=tk.X, anchor=tk.N)

        ttk.Label(form_frame, text='担当者名 (*必須):').grid(row=0, column=0, sticky=tk.W, pady=2)
        self.ent_labeler = ttk.Entry(form_frame, width=16)
        self.ent_labeler.grid(row=0, column=1, sticky=tk.W, pady=2)

        ttk.Label(form_frame, text='機器番号 (例: A-101):').grid(row=1, column=0, sticky=tk.W, pady=2)
        self.ent_meter_id = ttk.Entry(form_frame, width=16)
        self.ent_meter_id.grid(row=1, column=1, sticky=tk.W, pady=2)

        ttk.Label(form_frame, text='撮影条件:').grid(row=2, column=0, sticky=tk.W, pady=2)
        self.cmb_condition = ttk.Combobox(form_frame, values=['正面', 'ブレ', '斜め30', '斜め45', '反射'], width=13, state='readonly')
        self.cmb_condition.set('正面')
        self.cmb_condition.grid(row=2, column=1, sticky=tk.W, pady=2)

        ttk.Label(form_frame, text='メーター形状:').grid(row=3, column=0, sticky=tk.W, pady=2)
        self.cmb_scope = ttk.Combobox(form_frame, values=['round', 'square', 'fan'], width=13, state='readonly')
        self.cmb_scope.set('round')
        self.cmb_scope.grid(row=3, column=1, sticky=tk.W, pady=2)

        ttk.Label(form_frame, text='単位 (例: MPa):').grid(row=4, column=0, sticky=tk.W, pady=2)
        self.ent_unit = ttk.Entry(form_frame, width=16)
        self.ent_unit.grid(row=4, column=1, sticky=tk.W, pady=2)

        ttk.Label(form_frame, text='主目盛刻み (例: 50):').grid(row=5, column=0, sticky=tk.W, pady=2)
        self.ent_major_step = ttk.Entry(form_frame, width=16)
        self.ent_major_step.grid(row=5, column=1, sticky=tk.W, pady=2)

        ttk.Label(form_frame, text='目視値 (任意):').grid(row=6, column=0, sticky=tk.W, pady=2)
        self.ent_eye_value = ttk.Entry(form_frame, width=16)
        self.ent_eye_value.grid(row=6, column=1, sticky=tk.W, pady=2)

        ttk.Separator(form_frame, orient=tk.HORIZONTAL).grid(row=7, column=0, columnspan=2, sticky=tk.EW, pady=6)

        ttk.Label(form_frame, text='最小値 (min):').grid(row=8, column=0, sticky=tk.W, pady=2)
        self.ent_min = ttk.Entry(form_frame, width=16)
        self.ent_min.insert(0, '0')
        self.ent_min.grid(row=8, column=1, sticky=tk.W, pady=2)

        ttk.Label(form_frame, text='最大値 (max):').grid(row=9, column=0, sticky=tk.W, pady=2)
        self.ent_max = ttk.Entry(form_frame, width=16)
        self.ent_max.insert(0, '150')
        self.ent_max.grid(row=9, column=1, sticky=tk.W, pady=2)

        ttk.Label(form_frame, text='計算真値:').grid(row=10, column=0, sticky=tk.W, pady=2)
        self.lbl_calc_val = ttk.Label(form_frame, text='未計算', font=('Yu Gothic UI', 10, 'bold'), foreground='blue')
        self.lbl_calc_val.grid(row=10, column=1, sticky=tk.W, pady=2)

        self.var_unlabelable = tk.BooleanVar(value=False)
        self.chk_unlabelable = ttk.Checkbutton(form_frame, text='付けられない (ブレ/反射等)', variable=self.var_unlabelable, command=self._on_unlabelable_change)
        self.chk_unlabelable.grid(row=11, column=0, columnspan=2, sticky=tk.W, pady=6)

        ttk.Button(right_frame, text='数字の入力を終える', command=self.finish_numbered_ticks).pack(fill=tk.X, pady=(10, 2))
        ttk.Button(right_frame, text='ラベルを保存 (担当者別JSON)', command=self.save_person_label).pack(fill=tk.X, pady=2)
        ttk.Button(right_frame, text='groundtruth.jsonに追記', command=self.append_groundtruth).pack(fill=tk.X, pady=2)

    def _on_unlabelable_change(self):
        if self.var_unlabelable.get():
            self.lbl_calc_val.config(text='null (付けられない)', foreground='gray')
        else:
            self._update_calc_value()

    def load_image(self):
        path = filedialog.askopenfilename(
            title='メーター画像を選択',
            filetypes=[('画像ファイル', '*.jpg *.jpeg *.png *.bmp'), ('全ファイル', '*.*')]
        )
        if not path:
            return

        img = imread_ja(path)
        if img is None:
            messagebox.showerror('エラー', f'画像を開けませんでした:\n{path}')
            return

        self.image_path = path
        self.image = img
        self.points = {}
        self.numbered_ticks = []
        self.step_index = 0

        h, w = img.shape[:2]
        sw = MAX_CANVAS_W / float(w)
        sh = MAX_CANVAS_H / float(h)
        self.scale = min(sw, sh, 1.0)

        dw, dh = int(w * self.scale), int(h * self.scale)
        self.canvas.config(width=dw, height=dh)

        self._redraw()
        self._update_step_info()

    def _update_step_info(self):
        if self.image is None:
            self.lbl_info.config(text='「画像を開く」を押してください')
            return
        if self.step_index < len(STEPS):
            _, guide = STEPS[self.step_index]
            self.lbl_info.config(text=guide)
        else:
            self.lbl_info.config(text='すべての選択が完了しました。「ラベルを保存」を押してください。')

    def on_click(self, event):
        if self.image is None:
            return

        px = int(round(event.x / self.scale))
        py = int(round(event.y / self.scale))
        h, w = self.image.shape[:2]
        px = max(0, min(w - 1, px))
        py = max(0, min(h - 1, py))

        if self.step_index < 4:
            step_key, _ = STEPS[self.step_index]
            self.points[step_key] = (px, py)
            self.step_index += 1
            if self.step_index == 4:
                self._update_calc_value()
        elif self.step_index == 4:
            val = simpledialog.askfloat(
                "数字付き目盛り入力",
                f"クリックした位置 ({px}, {py}) の目盛り数値を入力してください:\n(例: 0, 50, 100)",
                parent=self.root
            )
            if val is not None:
                num_val = int(val) if val.is_integer() else val
                self.numbered_ticks.append({"value": num_val, "x": px, "y": py})

        self._redraw()
        self._update_step_info()

    def finish_numbered_ticks(self):
        if self.step_index == 4:
            self.step_index = 5
            self._update_step_info()

    def undo_point(self):
        if self.image is None:
            return
        if self.step_index == 5:
            self.step_index = 4
        elif self.step_index == 4 and self.numbered_ticks:
            self.numbered_ticks.pop()
        elif self.step_index > 0:
            self.step_index -= 1
            step_key, _ = STEPS[self.step_index]
            self.points.pop(step_key, None)
            self.lbl_calc_val.config(text='未計算')
        self._redraw()
        self._update_step_info()

    def on_mouse_move(self, event):
        if self.image is None:
            return

        rx = int(round(event.x / self.scale))
        ry = int(round(event.y / self.scale))
        h, w = self.image.shape[:2]

        if 0 <= rx < w and 0 <= ry < h:
            half = MAG_SIZE // 2
            x1 = max(0, rx - half)
            y1 = max(0, ry - half)
            x2 = min(w, rx + half)
            y2 = min(h, ry + half)

            crop = self.image[y1:y2, x1:x2]
            if crop.size == 0:
                return

            mag_img = cv2.resize(crop, (MAG_CANVAS_SIZE, MAG_CANVAS_SIZE), interpolation=cv2.INTER_NEAREST)
            ch = MAG_CANVAS_SIZE // 2
            cv2.line(mag_img, (ch, 0), (ch, MAG_CANVAS_SIZE), (0, 0, 255), 1)
            cv2.line(mag_img, (0, ch), (MAG_CANVAS_SIZE, ch), (0, 0, 255), 1)

            rgb = cv2.cvtColor(mag_img, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)
            self.mag_photo = ImageTk.PhotoImage(pil_img)
            self.mag_canvas.create_image(0, 0, anchor=tk.NW, image=self.mag_photo)

    def _update_calc_value(self):
        if len(self.points) < 4:
            return
        try:
            min_val = float(self.ent_min.get())
            max_val = float(self.ent_max.get())
            center = self.points['center']
            zero = self.points['zero']
            full = self.points['full']
            needle = self.points['needle']

            cx, cy = center
            theta_zero = math.atan2(zero[1] - cy, zero[0] - cx)
            theta_full = math.atan2(full[1] - cy, full[0] - cx)
            theta_needle = math.atan2(needle[1] - cy, needle[0] - cx)

            ratio = meter_reader.arc_ratio(theta_needle, theta_zero, theta_full)
            val = meter_reader.ratio_to_value(ratio, min_val, max_val)
            self.lbl_calc_val.config(text=f'{val:.2f}', foreground='blue')
            return val
        except ValueError:
            self.lbl_calc_val.config(text='入力エラー', foreground='red')
            return None

    def _redraw(self):
        if self.image is None:
            return

        vis = self.image.copy()

        for key, color in POINT_COLORS.items():
            if key in self.points:
                pt = self.points[key]
                cv2.circle(vis, pt, 6, color, -1)
                cv2.circle(vis, pt, 8, (0, 0, 0), 2)
                cv2.putText(vis, key, (pt[0] + 10, pt[1] - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)

        for tick in self.numbered_ticks:
            pt = (tick["x"], tick["y"])
            val = tick["value"]
            cv2.circle(vis, pt, 5, POINT_COLORS['tick'], -1)
            cv2.circle(vis, pt, 7, (0, 0, 0), 1)
            cv2.putText(vis, f"[{val}]", (pt[0] + 8, pt[1] + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, POINT_COLORS['tick'], 2, cv2.LINE_AA)

        if 'center' in self.points:
            c = self.points['center']
            for k in ('zero', 'full', 'needle'):
                if k in self.points:
                    cv2.line(vis, c, self.points[k], POINT_COLORS[k], 2, cv2.LINE_AA)

        h, w = vis.shape[:2]
        dw, dh = int(w * self.scale), int(h * self.scale)
        resized = cv2.resize(vis, (dw, dh), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)

        self.photo = ImageTk.PhotoImage(pil_img)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)

    def _get_form_dict(self):
        return {
            "labeler": self.ent_labeler.get(),
            "meter_id": self.ent_meter_id.get(),
            "condition": self.cmb_condition.get(),
            "scope": self.cmb_scope.get(),
            "unit": self.ent_unit.get(),
            "major_step": self.ent_major_step.get(),
            "eye_value": self.ent_eye_value.get(),
            "min_value": self.ent_min.get(),
            "max_value": self.ent_max.get(),
            "unlabelable": self.var_unlabelable.get(),
        }

    def save_person_label(self):
        if self.image is None:
            messagebox.showwarning('警告', '画像が開かれていません。')
            return

        form = self._get_form_dict()
        labeler = form["labeler"].strip()
        if not labeler:
            messagebox.showwarning('エラー', '担当者名 (*必須) を入力してください。')
            return

        if not form["unlabelable"] and len(self.points) < 4:
            messagebox.showwarning('警告', '4点（中心・0点・満尺点・針先）がまだ入力されていません。')
            return

        calc_val = None
        if not form["unlabelable"]:
            calc_val = self._update_calc_value()

        computed = {"true_value": calc_val}
        h, w = self.image.shape[:2]

        try:
            record = build_label_record(
                image_path=self.image_path,
                image_size=(w, h),
                points=self.points,
                numbered_ticks=self.numbered_ticks,
                form=form,
                computed=computed
            )
        except Exception as e:
            messagebox.showerror('エラー', f'データの構築に失敗しました:\n{e}')
            return

        os.makedirs(LABELS_DIR, exist_ok=True)
        save_path = os.path.join(LABELS_DIR, f"{labeler}.json")

        records = []
        if os.path.exists(save_path):
            try:
                with open(save_path, 'r', encoding='utf-8') as f:
                    records = json.load(f)
            except Exception:
                records = []

        target_img = record["image"]
        existing_idx = -1
        for idx, r in enumerate(records):
            if r.get("image") == target_img:
                existing_idx = idx
                break

        if existing_idx >= 0:
            if not messagebox.askyesno('上書き確認', f'画像 "{os.path.basename(target_img)}" の正解データは既に存在します。上書きしますか？'):
                return
            records[existing_idx] = record
        else:
            records.append(record)

        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

        messagebox.showinfo('保存完了', f'正解データを保存しました:\n{save_path}')

    def append_groundtruth(self):
        if self.image is None:
            messagebox.showwarning('警告', '画像が開かれていません。')
            return

        if self.var_unlabelable.get():
            true_val = None
        else:
            if len(self.points) < 4:
                messagebox.showwarning('警告', '4点が揃っていません。')
                return
            true_val = self._update_calc_value()

        min_val = float(self.ent_min.get()) if self.ent_min.get() else 0.0
        max_val = float(self.ent_max.get()) if self.ent_max.get() else 150.0

        os.makedirs(os.path.dirname(GROUNDTRUTH_PATH), exist_ok=True)
        data = []
        if os.path.exists(GROUNDTRUTH_PATH):
            with open(GROUNDTRUTH_PATH, 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                except Exception:
                    data = []

        target_img = os.path.normpath(self.image_path).replace("\\", "/")
        found = False
        for item in data:
            if os.path.normpath(item.get("image", "")).replace("\\", "/") == target_img:
                item["true_value"] = true_val
                item["min_value"] = min_val
                item["max_value"] = max_val
                found = True
                break

        if not found:
            data.append({
                "image": target_img,
                "min_value": min_val,
                "max_value": max_val,
                "true_value": true_val
            })

        with open(GROUNDTRUTH_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        messagebox.showinfo('保存完了', f'groundtruth.json に追記/更新しました:\n{GROUNDTRUTH_PATH}')


def main():
    root = tk.Tk()
    app = LabelTool(root)
    root.mainloop()


if __name__ == '__main__':
    main()
