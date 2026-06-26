"""
アナログメーター針角度検出・数値変換プログラム
使い方:
  1. プログラムを起動して画像ファイルを選択
  2. 針の中心点をクリック
  3. 0（最小値）の目盛り方向をクリック
  4. フルスケール（最大値）の目盛り方向をクリック
  5. 最小値・最大値をダイアログで入力
  6. 針をOpenCVで自動検出して角度と数値を表示
"""

import cv2
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from PIL import Image, ImageTk
import math


class MeterAngleDetector:
    def __init__(self, root):
        self.root = root
        self.root.title("アナログメーター 角度検出・数値変換")
        self.root.configure(bg="#1e1e2e")

        self.image_original = None   # OpenCV用 (BGR)
        self.image_display = None    # 表示用 (PIL)
        self.photo = None

        self.center_point = None      # 針の中心点
        self.zero_point = None        # 0（最小値）の目盛り点
        self.fullscale_point = None   # フルスケール（最大値）の目盛り点
        self.val_min = 0.0            # メーター最小値
        self.val_max = 100.0          # メーター最大値
        # 0=中心待ち, 1=ゼロ点待ち, 2=フルスケール点待ち, 3=完了
        self.click_step = 0

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

        # ── ステータスバー ────────────────────────────────────
        status_frame = tk.Frame(self.root, bg="#313244", pady=6)
        status_frame.pack(fill=tk.X)

        self.status_var = tk.StringVar(value="📂 まず画像を開いてください")
        self.status_label = tk.Label(
            status_frame,
            textvariable=self.status_var,
            font=("Helvetica", 11),
            fg="#a6e3a1", bg="#313244", anchor=tk.W
        )
        self.status_label.pack(side=tk.LEFT, padx=16)

        self.angle_var = tk.StringVar(value="")
        tk.Label(
            status_frame,
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
        self.angle_var.set("")
        if self.image_original is not None:
            self.status_var.set("🎯 Step 1: 針の中心点をクリックしてください")
            self._render()
        else:
            self.status_var.set("📂 まず画像を開いてください")

    # ── キャンバスへの描画 ────────────────────────────────────
    def _render(self, overlay=None):
        """overlay が None なら元画像, そうでなければ overlay を表示"""
        src = overlay if overlay is not None else self.image_original.copy()

        # キャンバスサイズに合わせてスケーリング
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

        # 黒帯を付けてキャンバスサイズに
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

        # キャンバス座標 → 画像座標
        ix = (event.x - self.offset_x) / self.scale
        iy = (event.y - self.offset_y) / self.scale
        ih, iw = self.image_original.shape[:2]
        if not (0 <= ix < iw and 0 <= iy < ih):
            return
        ix, iy = int(ix), int(iy)

        if self.click_step == 0:
            self.center_point = (ix, iy)
            self.click_step = 1
            self.status_var.set("📍 Step 2: 0（最小値）の目盛り方向をクリックしてください")
            self._draw_markers()

        elif self.click_step == 1:
            self.zero_point = (ix, iy)
            self.click_step = 2
            self.status_var.set("📍 Step 3: フルスケール（最大値）の目盛り方向をクリックしてください")
            self._draw_markers()

        elif self.click_step == 2:
            self.fullscale_point = (ix, iy)
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

        # --- グレースケール → Canny → Hough直線 ---
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

        # 中心点から直線までの距離の許容閾値（画像短辺の3%）
        center_pass_thresh = min(h, w) * 0.03

        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]

                # --- C案: 中心点を「通過」する直線のみを候補にする ---
                # 点(cx,cy)から直線(x1,y1)-(x2,y2)への垂直距離
                dx, dy = x2 - x1, y2 - y1
                line_len = math.hypot(dx, dy)
                if line_len == 0:
                    continue
                dist_to_center = abs(dy * cx - dx * cy + x2 * y1 - y2 * x1) / line_len
                if dist_to_center > center_pass_thresh:
                    continue  # 中心を通らない直線は除外

                # 直線の長さでスコア（中心を通る前提なので長いほど針らしい）
                length = line_len
                if length > best_score:
                    best_score = length
                    needle_line = line[0]

        # --- 針の先端方向を決める ---
        if needle_line is not None:
            x1, y1, x2, y2 = needle_line
            d1 = math.hypot(x1 - cx, y1 - cy)
            d2 = math.hypot(x2 - cx, y2 - cy)

            # --- 線分の「向き」から針方向を確定（端点位置に依存しない）---
            # 線分方向ベクトル（中心→遠端側に合わせる）
            ndx, ndy = float(x2 - x1), float(y2 - y1)
            far_x, far_y = (x1, y1) if d1 > d2 else (x2, y2)
            if (far_x - cx) * ndx + (far_y - cy) * ndy < 0:
                ndx, ndy = -ndx, -ndy  # 先端側へ向きを反転
            n_len = math.hypot(ndx, ndy)
            ndx, ndy = ndx / n_len, ndy / n_len  # 単位ベクトル

            # エッジ画像を中心から針方向にスキャンして実際の先端を探す
            # 一定ピクセル以上エッジが途切れたら先端を過ぎたと判断して停止
            gap_thresh = max(8, int(min(h, w) * 0.025))
            max_scan   = int(min(h, w) * 0.60)
            tip_x, tip_y = far_x, far_y  # デフォルト（旧来の端点）
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
                        break  # 針の先端を過ぎた

            # 表示用: 針とゼロ基準の間の角度（dot積、0〜180°）
            zero_vec = np.array([zx - cx, zy - cy], dtype=float)
            cos_a = np.dot([ndx, ndy], zero_vec) / (np.linalg.norm(zero_vec) + 1e-9)
            abs_angle = math.degrees(math.acos(np.clip(cos_a, -1.0, 1.0)))

            # --- 2点キャリブレーション: atan2 + 方向自動選択 ---
            # 各点の絶対角度（atan2はimage座標そのまま使用）
            theta_zero   = math.atan2(zy  - cy, zx  - cx)
            theta_full   = math.atan2(fsy - cy, fsx - cx)
            theta_needle = math.atan2(ndy, ndx)  # 線分の向きから直接計算
            two_pi = 2 * math.pi

            def _arc_ratio(th_pt, th_from, th_to, cw):
                """th_from→th_toをcw方向で進んだとき、th_ptが何割の位置か。"""
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
                # 両方有効: スパンが大きい方（弧が長い＝より合理的）を優先
                span_cw  = (theta_full - theta_zero) % two_pi
                span_ccw = (theta_zero - theta_full) % two_pi
                ratio = r_cw if span_cw >= span_ccw else r_ccw
            else:
                ratio = max(0.0, min(1.0, r_cw if r_cw is not None else 0.0))

            value = self.val_min + ratio * (self.val_max - self.val_min)
            value_valid = True

            # ── 結果を画像に描画 ──────────────────────────
            # 検出直線
            cv2.line(img, (x1, y1), (x2, y2), (255, 180, 0), 2)

            # 基準線 (中心 → 0目盛り)
            cv2.line(img, (cx, cy), (zx, zy), (100, 220, 255), 2)

            # フルスケール基準線 (中心 → フルスケール目盛り)
            cv2.line(img, (cx, cy), (fsx, fsy), (180, 100, 255), 2)

            # 中心点
            cv2.circle(img, (cx, cy), 8, (0, 255, 100), -1)
            cv2.drawMarker(img, (cx, cy), (0, 255, 100),
                           cv2.MARKER_CROSS, 30, 2)

            # 0目盛り点
            cv2.circle(img, (zx, zy), 8, (100, 220, 255), -1)
            cv2.drawMarker(img, (zx, zy), (100, 220, 255),
                           cv2.MARKER_CROSS, 20, 2)

            # フルスケール目盛り点
            cv2.circle(img, (fsx, fsy), 8, (180, 100, 255), -1)
            cv2.drawMarker(img, (fsx, fsy), (180, 100, 255),
                           cv2.MARKER_CROSS, 20, 2)

            # 先端点
            cv2.circle(img, (tip_x, tip_y), 6, (255, 80, 80), -1)

            # 結果テキスト (背景付き)
            if value_valid:
                result_text = f"Angle: {abs_angle:.1f}deg  Value: {value:.2f}"
            else:
                result_text = f"Angle: {abs_angle:.1f}deg"

            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = max(0.8, min(w, h) / 600)
            thickness = 2
            (tw, th), baseline = cv2.getTextSize(
                result_text, font, font_scale, thickness)

            tx = min(cx + 10, w - tw - 10)
            ty = max(cy - 20, th + 10)

            # 半透明風の背景矩形
            cv2.rectangle(img,
                          (tx - 6, ty - th - 6),
                          (tx + tw + 6, ty + baseline + 4),
                          (30, 30, 30), cv2.FILLED)
            cv2.rectangle(img,
                          (tx - 6, ty - th - 6),
                          (tx + tw + 6, ty + baseline + 4),
                          (255, 180, 0), 2)
            cv2.putText(img, result_text, (tx, ty),
                        font, font_scale, (255, 220, 80), thickness)

            # ラベル
            cv2.putText(img, "Center", (cx + 10, cy - 12),
                        font, 0.5, (0, 255, 100), 1)
            cv2.putText(img, f"Zero ({self.val_min})", (zx + 8, zy - 8),
                        font, 0.5, (100, 220, 255), 1)
            cv2.putText(img, f"Full ({self.val_max})", (fsx + 8, fsy - 8),
                        font, 0.5, (180, 100, 255), 1)

            self._render(img)

            if value_valid:
                self.status_var.set(
                    f"✅ 検出完了！  角度: {abs_angle:.1f}°  値: {value:.2f}  "
                    f"（{self.val_min} ～ {self.val_max}）")
                self.angle_var.set(f"📊 {value:.2f}  ({abs_angle:.1f}°)")
            else:
                self.status_var.set("✅ 検出完了！リセットして再計測できます")
                self.angle_var.set(f"🎯 {abs_angle:.1f}°")

        else:
            # 直線が見つからなかった場合
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
