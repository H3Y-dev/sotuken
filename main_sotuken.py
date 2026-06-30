"""
アナログメーター針角度検出・数値変換プログラム
使い方:
  1. プログラムを起動して画像ファイルを選択
  2. 針の中心点を自動検出（HoughCircles）または手動クリックで指定
  3. 0目盛り・フルスケール目盛りをVLMで自動検出または手動クリックで指定
  4. 針をOpenCVで自動検出して角度と数値を表示
"""

import cv2
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from PIL import Image, ImageTk
import math
import json
import re
import io
import base64
import ollama
import threading


class MeterAngleDetector:
    def __init__(self, root):
        self.root = root
        self.root.title("アナログメーター 角度検出・数値変換")
        self.root.configure(bg="#1e1e2e")

        self.image_original = None
        self.photo = None

        self.center_point = None
        self.zero_point = None
        self.fullscale_point = None
        self.val_min = 0.0
        self.val_max = 100.0
        # 0=中心待ち, 1=ゼロ点待ち, 2=フルスケール点待ち, 3=完了
        self.click_step = 0

        self.auto_center_candidate = None  # (x, y, radius) or None
        self.auto_scale_candidate = None   # dict or None
        self.vlm_values_set = False        # VLMで最小値・最大値を取得済みか
        self._vlm_request_id = 0          # リセット時に古いスレッド結果を破棄するためのID

        self.canvas_width = 800
        self.canvas_height = 600
        self.scale = 1.0
        self.offset_x = 0
        self.offset_y = 0

        self._build_ui()

    def _build_ui(self):
        # ── ヘッダー ──────────────────────────────────────────
        header = tk.Frame(self.root, bg="#313244", pady=8)
        header.pack(fill=tk.X)

        tk.Label(
            header, text="📐 アナログメーター 角度検出・数値変換",
            font=("Helvetica", 16, "bold"),
            fg="#cdd6f4", bg="#313244"
        ).pack(side=tk.LEFT, padx=16)

        tk.Button(
            header, text="📂 画像を開く",
            command=self.open_image,
            font=("Helvetica", 11),
            bg="#89b4fa", fg="#1e1e2e",
            relief=tk.FLAT, padx=12, pady=4, cursor="hand2"
        ).pack(side=tk.RIGHT, padx=16)

        tk.Button(
            header, text="🔄 リセット",
            command=self.reset,
            font=("Helvetica", 11),
            bg="#f38ba8", fg="#1e1e2e",
            relief=tk.FLAT, padx=12, pady=4, cursor="hand2"
        ).pack(side=tk.RIGHT, padx=4)

        # ── キャンバス ────────────────────────────────────────
        canvas_frame = tk.Frame(self.root, bg="#1e1e2e")
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)

        self.canvas = tk.Canvas(
            canvas_frame,
            width=self.canvas_width,
            height=self.canvas_height,
            bg="#181825", highlightthickness=1,
            highlightbackground="#585b70", cursor="crosshair"
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<Configure>", self.on_canvas_resize)

        # ── 中心点 自動検出確認フレーム ───────────────────────
        self.confirm_frame = tk.Frame(self.root, bg="#2a2a3e", pady=6)

        tk.Label(
            self.confirm_frame,
            text="🔍 針の中心点を自動検出しました",
            font=("Helvetica", 11, "bold"),
            fg="#a6e3a1", bg="#2a2a3e"
        ).pack(side=tk.LEFT, padx=16)

        tk.Button(
            self.confirm_frame, text="✅ この点を使用",
            command=self._confirm_auto_center,
            font=("Helvetica", 11),
            bg="#a6e3a1", fg="#1e1e2e",
            relief=tk.FLAT, padx=12, pady=3, cursor="hand2"
        ).pack(side=tk.LEFT, padx=8)

        tk.Button(
            self.confirm_frame, text="🖱️ 手動で選択",
            command=self._reject_auto_center,
            font=("Helvetica", 11),
            bg="#fab387", fg="#1e1e2e",
            relief=tk.FLAT, padx=12, pady=3, cursor="hand2"
        ).pack(side=tk.LEFT, padx=4)

        # ── 目盛り 自動検出確認フレーム ───────────────────────
        self.confirm_scale_frame = tk.Frame(self.root, bg="#2a2a3e", pady=6)

        self.scale_info_var = tk.StringVar(value="")
        tk.Label(
            self.confirm_scale_frame,
            textvariable=self.scale_info_var,
            font=("Helvetica", 10, "bold"),
            fg="#cba6f7", bg="#2a2a3e"
        ).pack(side=tk.LEFT, padx=16)

        tk.Button(
            self.confirm_scale_frame, text="✅ そのまま使用",
            command=self._confirm_scale_auto,
            font=("Helvetica", 11),
            bg="#a6e3a1", fg="#1e1e2e",
            relief=tk.FLAT, padx=12, pady=3, cursor="hand2"
        ).pack(side=tk.LEFT, padx=8)

        tk.Button(
            self.confirm_scale_frame, text="🔄 入れ替え",
            command=self._swap_scale_auto,
            font=("Helvetica", 11),
            bg="#89dceb", fg="#1e1e2e",
            relief=tk.FLAT, padx=12, pady=3, cursor="hand2"
        ).pack(side=tk.LEFT, padx=4)

        tk.Button(
            self.confirm_scale_frame, text="🖱️ 手動で選択",
            command=self._reject_scale_auto,
            font=("Helvetica", 11),
            bg="#fab387", fg="#1e1e2e",
            relief=tk.FLAT, padx=12, pady=3, cursor="hand2"
        ).pack(side=tk.LEFT, padx=4)

        # ── ステータスバー ────────────────────────────────────
        self.status_frame = tk.Frame(self.root, bg="#313244", pady=6)
        self.status_frame.pack(fill=tk.X)

        self.status_var = tk.StringVar(value="📂 まず画像を開いてください")
        tk.Label(
            self.status_frame,
            textvariable=self.status_var,
            font=("Helvetica", 11),
            fg="#a6e3a1", bg="#313244", anchor=tk.W
        ).pack(side=tk.LEFT, padx=16)

        self.angle_var = tk.StringVar(value="")
        tk.Label(
            self.status_frame,
            textvariable=self.angle_var,
            font=("Helvetica", 13, "bold"),
            fg="#fab387", bg="#313244"
        ).pack(side=tk.RIGHT, padx=16)

    # ── 画像読み込み ──────────────────────────────────────────
    def open_image(self):
        path = filedialog.askopenfilename(
            filetypes=[("画像ファイル", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff")]
        )
        if not path:
            return
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            messagebox.showerror("エラー", "画像を読み込めませんでした")
            return
        self.image_original = img
        self.reset()

    def reset(self):
        self.center_point = None
        self.zero_point = None
        self.fullscale_point = None
        self.val_min = 0.0
        self.val_max = 100.0
        self.click_step = 0
        self.auto_center_candidate = None
        self.auto_scale_candidate = None
        self.vlm_values_set = False
        self._vlm_request_id += 1  # 実行中スレッドの結果を無効化
        self.angle_var.set("")
        self._hide_confirm_frame()
        self._hide_confirm_scale_frame()

        if self.image_original is None:
            self.status_var.set("📂 まず画像を開いてください")
            return

        self._render()

        candidate = self._auto_detect_center()
        if candidate is not None:
            self.auto_center_candidate = candidate
            self._show_auto_candidate()
        else:
            self.status_var.set("🎯 Step 1: 針の中心点をクリックしてください")

    # ── Step1: Hough円検出で中心点候補を取得 ─────────────────
    def _auto_detect_center(self):
        gray = cv2.cvtColor(self.image_original, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (9, 9), 2)

        h, w = self.image_original.shape[:2]
        short = min(h, w)
        min_r = max(4, int(short * 0.008))
        max_r = max(25, int(short * 0.06))

        circles = cv2.HoughCircles(
            blurred,
            cv2.HOUGH_GRADIENT,
            dp=1,
            minDist=short * 0.04,
            param1=80,
            param2=28,
            minRadius=min_r,
            maxRadius=max_r
        )

        if circles is None:
            return None

        circles = np.round(circles[0, :]).astype(int)
        img_cx, img_cy = w // 2, h // 2
        best = min(circles, key=lambda c: math.hypot(c[0] - img_cx, c[1] - img_cy))
        return (int(best[0]), int(best[1]), int(best[2]))

    def _show_auto_candidate(self):
        cx, cy, r = self.auto_center_candidate
        overlay = self.image_original.copy()
        cv2.circle(overlay, (cx, cy), r, (0, 230, 255), 2)
        cv2.circle(overlay, (cx, cy), 6, (0, 230, 255), -1)
        cv2.drawMarker(overlay, (cx, cy), (0, 230, 255), cv2.MARKER_CROSS, 28, 2)
        self._render(overlay)
        self.confirm_frame.pack(fill=tk.X, before=self.status_frame)
        self.status_var.set(
            f"🔍 中心点の候補を検出しました ({cx}, {cy}) — 確定するか手動で選択してください")

    def _hide_confirm_frame(self):
        self.confirm_frame.pack_forget()

    def _confirm_auto_center(self):
        if self.auto_center_candidate is None:
            return
        cx, cy, _ = self.auto_center_candidate
        self.center_point = (cx, cy)
        self.auto_center_candidate = None
        self._hide_confirm_frame()
        self._on_center_confirmed()

    def _reject_auto_center(self):
        self.auto_center_candidate = None
        self._hide_confirm_frame()
        self._render()
        self.status_var.set("🎯 Step 1: 針の中心点をクリックしてください")

    # ── 中心点確定後の共通処理 ────────────────────────────────
    def _on_center_confirmed(self):
        self.click_step = 1
        self._draw_markers()
        self.status_var.set("🤖 VLMで目盛りを解析中... しばらくお待ちください")

        request_id = self._vlm_request_id

        def worker():
            result = self._query_vlm_for_scale()
            # メインスレッドへ結果を渡す（リセット済みなら無視）
            self.root.after(0, lambda: self._on_vlm_result(result, request_id))

        threading.Thread(target=worker, daemon=True).start()

    def _on_vlm_result(self, result, request_id):
        """VLMスレッドの結果をメインスレッドで受け取る"""
        if request_id != self._vlm_request_id:
            return  # リセット・新規画像で無効化済み

        if result is not None:
            self.val_min = result['min_value']
            self.val_max = result['max_value']
            self.vlm_values_set = True
            zero_pt = self._clock_to_point(result['zero_clock'])
            full_pt = self._clock_to_point(result['full_clock'])
            self.auto_scale_candidate = {
                'zero_pt':    zero_pt,
                'full_pt':    full_pt,
                'min_value':  result['min_value'],
                'max_value':  result['max_value'],
                'zero_clock': result['zero_clock'],
                'full_clock': result['full_clock'],
            }
            self._show_scale_candidates()
        else:
            self.vlm_values_set = False
            self.status_var.set("📍 Step 2: 0（最小値）の目盛り方向をクリックしてください")

    # ── Step2: VLMで目盛り情報を取得 ─────────────────────────
    def _query_vlm_for_scale(self):
        """Qwen2.5-VLにメーター画像を送り目盛り情報をJSONで取得する。失敗時はNone。"""
        try:
            # VLMに送る画像は長辺512pxに縮小してビジュアルトークン数を削減
            rgb = cv2.cvtColor(self.image_original, cv2.COLOR_BGR2RGB)
            h, w = rgb.shape[:2]
            max_side = 512
            if max(h, w) > max_side:
                scale = max_side / max(h, w)
                rgb = cv2.resize(rgb, (int(w * scale), int(h * scale)))

            buf = io.BytesIO()
            Image.fromarray(rgb).save(buf, format='JPEG', quality=85)
            img_b64 = base64.b64encode(buf.getvalue()).decode()

            prompt = (
                "Look at this analog meter image. "
                "Respond with JSON only, no explanation:\n"
                "{\n"
                '  "min_value": <minimum scale number>,\n'
                '  "max_value": <maximum scale number>,\n'
                '  "zero_clock": <clock position of minimum mark as decimal, e.g. 7.5>,\n'
                '  "full_clock": <clock position of maximum mark as decimal, e.g. 4.5>\n'
                "}\n"
                "Clock positions: 12=top, 3=right, 6=bottom, 9=left."
            )

            res = ollama.chat(
                model='qwen2.5vl:7b',
                messages=[{
                    'role': 'user',
                    'content': prompt,
                    'images': [img_b64]
                }],
                options={'num_predict': 80}
            )

            # マークダウンのコードブロックにも対応してJSONを抽出
            json_match = re.search(r'\{.*?\}', res.message.content, re.DOTALL)
            if not json_match:
                return None

            data = json.loads(json_match.group())

            if not all(k in data for k in ('min_value', 'max_value', 'zero_clock', 'full_clock')):
                return None

            zero_clock = float(data['zero_clock'])
            full_clock = float(data['full_clock'])
            if not (1 <= zero_clock <= 12 and 1 <= full_clock <= 12):
                return None

            return {
                'min_value':  float(data['min_value']),
                'max_value':  float(data['max_value']),
                'zero_clock': zero_clock,
                'full_clock': full_clock,
            }

        except Exception:
            return None

    # ── 時計位置 → 画像座標 ───────────────────────────────────
    def _clock_to_point(self, clock_pos: float) -> tuple:
        """
        時計の位置（12=上, 3=右, 6=下, 9=左）を
        中心点からr離れたピクセル座標に変換する。
        """
        cx, cy = self.center_point
        h, w = self.image_original.shape[:2]
        r = min(w, h) * 0.35

        theta_rad = math.radians((clock_pos - 3) * 30)
        x = int(cx + r * math.cos(theta_rad))
        y = int(cy + r * math.sin(theta_rad))

        x = max(0, min(w - 1, x))
        y = max(0, min(h - 1, y))
        return (x, y)

    # ── 目盛り候補をオーバーレイ表示 ─────────────────────────
    def _show_scale_candidates(self):
        c = self.auto_scale_candidate
        zero_pt = c['zero_pt']
        full_pt = c['full_pt']
        cx, cy = self.center_point

        overlay = self.image_original.copy()
        font = cv2.FONT_HERSHEY_SIMPLEX

        # 中心点（緑）
        cv2.drawMarker(overlay, (cx, cy), (0, 255, 100), cv2.MARKER_CROSS, 30, 2)
        cv2.circle(overlay, (cx, cy), 8, (0, 255, 100), -1)

        # ゼロ点候補（シアン）
        cv2.line(overlay, (cx, cy), zero_pt, (100, 220, 255), 1)
        cv2.circle(overlay, zero_pt, 10, (100, 220, 255), 2)
        cv2.circle(overlay, zero_pt, 5, (100, 220, 255), -1)
        cv2.putText(overlay, f"Zero({c['min_value']:.4g})",
                    (zero_pt[0] + 8, zero_pt[1] - 8), font, 0.5, (100, 220, 255), 1)

        # フルスケール候補（紫）
        cv2.line(overlay, (cx, cy), full_pt, (180, 100, 255), 1)
        cv2.circle(overlay, full_pt, 10, (180, 100, 255), 2)
        cv2.circle(overlay, full_pt, 5, (180, 100, 255), -1)
        cv2.putText(overlay, f"Full({c['max_value']:.4g})",
                    (full_pt[0] + 8, full_pt[1] - 8), font, 0.5, (180, 100, 255), 1)

        self._render(overlay)
        self.scale_info_var.set(
            f"🤖  0目盛り: {c['zero_clock']}時方向  "
            f"最大目盛り: {c['full_clock']}時方向  "
            f"範囲: {c['min_value']:.4g} ～ {c['max_value']:.4g}"
        )
        self.confirm_scale_frame.pack(fill=tk.X, before=self.status_frame)
        self.status_var.set("VLMが目盛りを検出しました — 確定・入れ替え・手動選択のいずれかを選んでください")

    def _hide_confirm_scale_frame(self):
        self.confirm_scale_frame.pack_forget()

    def _confirm_scale_auto(self):
        if self.auto_scale_candidate is None:
            return
        c = self.auto_scale_candidate
        self.zero_point = c['zero_pt']
        self.fullscale_point = c['full_pt']
        self.auto_scale_candidate = None
        self.click_step = 3
        self._hide_confirm_scale_frame()
        self.status_var.set("🔍 針を検出中...")
        self.root.update()
        self._detect_and_show()

    def _swap_scale_auto(self):
        """ゼロ点とフルスケール点を入れ替えて再表示する"""
        c = self.auto_scale_candidate
        self.auto_scale_candidate = {
            'zero_pt':    c['full_pt'],
            'full_pt':    c['zero_pt'],
            'min_value':  c['min_value'],
            'max_value':  c['max_value'],
            'zero_clock': c['full_clock'],
            'full_clock': c['zero_clock'],
        }
        self._show_scale_candidates()

    def _reject_scale_auto(self):
        """VLMの結果を破棄して手動クリックに切り替える"""
        self.auto_scale_candidate = None
        self.vlm_values_set = False
        self._hide_confirm_scale_frame()
        self._draw_markers()
        self.status_var.set("📍 Step 2: 0（最小値）の目盛り方向をクリックしてください")

    # ── キャンバスへの描画 ────────────────────────────────────
    def _render(self, overlay=None):
        src = overlay if overlay is not None else self.image_original.copy()

        cw = self.canvas.winfo_width() or self.canvas_width
        ch = self.canvas.winfo_height() or self.canvas_height
        ih, iw = src.shape[:2]
        scale = min(cw / iw, ch / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        self.scale = scale
        self.offset_x = (cw - nw) // 2
        self.offset_y = (ch - nh) // 2

        resized = cv2.resize(src, (nw, nh))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)

        canvas_img = Image.new("RGB", (cw, ch), (24, 24, 37))
        canvas_img.paste(pil_img, (self.offset_x, self.offset_y))

        self.photo = ImageTk.PhotoImage(canvas_img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)

    def on_canvas_resize(self, event):
        if self.image_original is not None:
            self._render()

    # ── マウスクリック処理 ────────────────────────────────────
    def on_canvas_click(self, event):
        if self.image_original is None:
            return

        ix = (event.x - self.offset_x) / self.scale
        iy = (event.y - self.offset_y) / self.scale
        ih, iw = self.image_original.shape[:2]
        if not (0 <= ix < iw and 0 <= iy < ih):
            return
        ix, iy = int(ix), int(iy)

        if self.click_step == 0:
            # 自動検出候補が表示中でもクリックで手動上書き
            self.auto_center_candidate = None
            self._hide_confirm_frame()
            self.center_point = (ix, iy)
            self._on_center_confirmed()

        elif self.click_step == 1:
            # 手動でゼロ点を指定（VLM候補・取得済み値をリセット）
            self.auto_scale_candidate = None
            self.vlm_values_set = False
            self._hide_confirm_scale_frame()
            self.zero_point = (ix, iy)
            self.click_step = 2
            self.status_var.set("📍 Step 3: フルスケール（最大値）の目盛り方向をクリックしてください")
            self._draw_markers()

        elif self.click_step == 2:
            self.fullscale_point = (ix, iy)
            # VLMで値を取得済みならダイアログをスキップ
            if self.vlm_values_set:
                self.click_step = 3
                self.status_var.set("🔍 針を検出中...")
                self.root.update()
                self._detect_and_show()
            else:
                val_min = simpledialog.askfloat(
                    "最小値入力", "メーターの最小値を入力してください:",
                    initialvalue=0.0, parent=self.root)
                if val_min is None:
                    return
                val_max = simpledialog.askfloat(
                    "最大値入力", "メーターの最大値を入力してください:",
                    initialvalue=100.0, parent=self.root)
                if val_max is None:
                    return
                self.val_min = val_min
                self.val_max = val_max
                self.click_step = 3
                self.status_var.set("🔍 針を検出中...")
                self.root.update()
                self._detect_and_show()

    # ── マーカーだけ描いて表示 ────────────────────────────────
    def _draw_markers(self):
        overlay = self.image_original.copy()
        if self.center_point:
            cv2.drawMarker(overlay, self.center_point, (0, 255, 100),
                           cv2.MARKER_CROSS, 30, 2)
            cv2.circle(overlay, self.center_point, 8, (0, 255, 100), -1)
        if self.zero_point:
            cv2.drawMarker(overlay, self.zero_point, (100, 220, 255),
                           cv2.MARKER_CROSS, 20, 2)
            cv2.circle(overlay, self.zero_point, 8, (100, 220, 255), -1)
        if self.fullscale_point:
            cv2.drawMarker(overlay, self.fullscale_point, (180, 100, 255),
                           cv2.MARKER_CROSS, 20, 2)
            cv2.circle(overlay, self.fullscale_point, 8, (180, 100, 255), -1)
        self._render(overlay)

    # ── 針検出 & 角度・数値表示 ───────────────────────────────
    def _detect_and_show(self):
        cx, cy = self.center_point
        zx, zy = self.zero_point
        fsx, fsy = self.fullscale_point
        img = self.image_original.copy()
        h, w = img.shape[:2]

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150)

        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=40,
            minLineLength=30,
            maxLineGap=15
        )

        needle_line = None
        best_score = -1
        center_pass_thresh = min(h, w) * 0.03

        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]
                dx, dy = x2 - x1, y2 - y1
                line_len = math.hypot(dx, dy)
                if line_len == 0:
                    continue
                dist_to_center = abs(dy * cx - dx * cy + x2 * y1 - y2 * x1) / line_len
                if dist_to_center > center_pass_thresh:
                    continue
                if line_len > best_score:
                    best_score = line_len
                    needle_line = line[0]

        if needle_line is not None:
            x1, y1, x2, y2 = needle_line
            d1 = math.hypot(x1 - cx, y1 - cy)
            d2 = math.hypot(x2 - cx, y2 - cy)

            ndx, ndy = float(x2 - x1), float(y2 - y1)
            far_x, far_y = (x1, y1) if d1 > d2 else (x2, y2)
            if (far_x - cx) * ndx + (far_y - cy) * ndy < 0:
                ndx, ndy = -ndx, -ndy
            n_len = math.hypot(ndx, ndy)
            ndx, ndy = ndx / n_len, ndy / n_len

            gap_thresh = max(8, int(min(h, w) * 0.025))
            max_scan = int(min(h, w) * 0.60)
            tip_x, tip_y = far_x, far_y
            consecutive_empty = 0
            for r in range(3, max_scan):
                px = int(cx + ndx * r + 0.5)
                py = int(cy + ndy * r + 0.5)
                if not (0 <= px < w and 0 <= py < h):
                    break
                if edges[py, px] > 0:
                    tip_x, tip_y = px, py
                    consecutive_empty = 0
                else:
                    consecutive_empty += 1
                    if consecutive_empty > gap_thresh:
                        break

            zero_vec = np.array([zx - cx, zy - cy], dtype=float)
            cos_a = np.dot([ndx, ndy], zero_vec) / (np.linalg.norm(zero_vec) + 1e-9)
            abs_angle = math.degrees(math.acos(np.clip(cos_a, -1.0, 1.0)))

            theta_zero   = math.atan2(zy  - cy, zx  - cx)
            theta_full   = math.atan2(fsy - cy, fsx - cx)
            theta_needle = math.atan2(ndy, ndx)
            two_pi = 2 * math.pi

            def _arc_ratio(th_pt, th_from, th_to, cw):
                if cw:
                    span   = (th_to   - th_from) % two_pi
                    offset = (th_pt   - th_from) % two_pi
                else:
                    span   = (th_from - th_to)   % two_pi
                    offset = (th_from - th_pt)   % two_pi
                return (offset / span) if span > 1e-6 else None

            r_cw  = _arc_ratio(theta_needle, theta_zero, theta_full, cw=True)
            r_ccw = _arc_ratio(theta_needle, theta_zero, theta_full, cw=False)
            ok_cw  = r_cw  is not None and 0.0 <= r_cw  <= 1.0
            ok_ccw = r_ccw is not None and 0.0 <= r_ccw <= 1.0

            if ok_cw and not ok_ccw:
                ratio = r_cw
            elif ok_ccw and not ok_cw:
                ratio = r_ccw
            elif ok_cw and ok_ccw:
                span_cw  = (theta_full - theta_zero) % two_pi
                span_ccw = (theta_zero - theta_full) % two_pi
                ratio = r_cw if span_cw >= span_ccw else r_ccw
            else:
                ratio = max(0.0, min(1.0, r_cw if r_cw is not None else 0.0))

            value = self.val_min + ratio * (self.val_max - self.val_min)

            # ── 結果を画像に描画 ──────────────────────────
            cv2.line(img, (x1, y1), (x2, y2), (255, 180, 0), 2)
            cv2.line(img, (cx, cy), (zx, zy), (100, 220, 255), 2)
            cv2.line(img, (cx, cy), (fsx, fsy), (180, 100, 255), 2)
            cv2.circle(img, (cx, cy), 8, (0, 255, 100), -1)
            cv2.drawMarker(img, (cx, cy), (0, 255, 100), cv2.MARKER_CROSS, 30, 2)
            cv2.circle(img, (zx, zy), 8, (100, 220, 255), -1)
            cv2.drawMarker(img, (zx, zy), (100, 220, 255), cv2.MARKER_CROSS, 20, 2)
            cv2.circle(img, (fsx, fsy), 8, (180, 100, 255), -1)
            cv2.drawMarker(img, (fsx, fsy), (180, 100, 255), cv2.MARKER_CROSS, 20, 2)
            cv2.circle(img, (tip_x, tip_y), 6, (255, 80, 80), -1)

            result_text = f"Angle: {abs_angle:.1f}deg  Value: {value:.2f}"
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = max(0.8, min(w, h) / 600)
            thickness = 2
            (tw, th), baseline = cv2.getTextSize(result_text, font, font_scale, thickness)
            tx = min(cx + 10, w - tw - 10)
            ty = max(cy - 20, th + 10)

            cv2.rectangle(img, (tx - 6, ty - th - 6), (tx + tw + 6, ty + baseline + 4),
                          (30, 30, 30), cv2.FILLED)
            cv2.rectangle(img, (tx - 6, ty - th - 6), (tx + tw + 6, ty + baseline + 4),
                          (255, 180, 0), 2)
            cv2.putText(img, result_text, (tx, ty), font, font_scale, (255, 220, 80), thickness)

            cv2.putText(img, "Center", (cx + 10, cy - 12), font, 0.5, (0, 255, 100), 1)
            cv2.putText(img, f"Zero ({self.val_min})", (zx + 8, zy - 8),
                        font, 0.5, (100, 220, 255), 1)
            cv2.putText(img, f"Full ({self.val_max})", (fsx + 8, fsy - 8),
                        font, 0.5, (180, 100, 255), 1)

            self._render(img)
            self.status_var.set(
                f"✅ 検出完了！  角度: {abs_angle:.1f}°  値: {value:.2f}  "
                f"（{self.val_min} ～ {self.val_max}）")
            self.angle_var.set(f"📊 {value:.2f}  ({abs_angle:.1f}°)")

        else:
            self._draw_markers()
            messagebox.showwarning(
                "検出失敗",
                "針の直線を自動検出できませんでした。\n"
                "画像のコントラストや解像度を確認してください。"
            )
            self.click_step = 1
            self.zero_point = None
            self.fullscale_point = None
            self.status_var.set(
                "⚠️ 検出失敗。Step 2: 再度 0の目盛りをクリックしてください")


# ── エントリポイント ──────────────────────────────────────────
def main():
    root = tk.Tk()
    root.geometry("900x700")
    app = MeterAngleDetector(root)
    root.mainloop()


if __name__ == "__main__":
    main()
