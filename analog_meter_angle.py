"""
アナログメーター針角度検出プログラム
使い方:
  1. プログラムを起動して画像ファイルを選択
  2. 針の中心点をクリック
  3. 基準となる0の目盛り方向をクリック
  4. 針をOpenCVで自動検出して角度を表示
"""
#kippeikukndayo
import cv2
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import math


class MeterAngleDetector:
    def __init__(self, root):
        self.root = root
        self.root.title("アナログメーター 角度検出")
        self.root.configure(bg="#1e1e2e")

        self.image_original = None   # OpenCV用 (BGR)
        self.image_display = None    # 表示用 (PIL)
        self.photo = None

        self.center_point = None     # 針の中心点
        self.zero_point = None       # 0の目盛り点
        self.click_step = 0          # 0=中心待ち, 1=0目盛り待ち, 2=完了

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
            header, text="📐 アナログメーター 角度検出",
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
        img = cv2.imread(path)
        if img is None:
            messagebox.showerror("エラー", "画像を読み込めませんでした")
            return
        self.image_original = img
        self.reset()

    def reset(self):
        self.center_point = None
        self.zero_point = None
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
            self.status_var.set("📍 Step 2: 0の目盛り方向をクリックしてください")
            self._draw_markers()

        elif self.click_step == 1:
            self.zero_point = (ix, iy)
            self.click_step = 2
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
        self._render(overlay)

    # ── 針検出 & 角度表示 ────────────────────────────────────
    def _detect_and_show(self):
        cx, cy = self.center_point
        zx, zy = self.zero_point
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

        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]

                # 中心点に近い端点を持つ直線を優先
                d1 = math.hypot(x1 - cx, y1 - cy)
                d2 = math.hypot(x2 - cx, y2 - cy)
                min_d = min(d1, d2)

                # 直線の長さ
                length = math.hypot(x2 - x1, y2 - y1)

                # スコア: 中心に近いほど・長いほど優先
                score = length / (min_d + 1)
                if score > best_score:
                    best_score = score
                    needle_line = line[0]

        # --- 針の先端方向を決める ---
        if needle_line is not None:
            x1, y1, x2, y2 = needle_line
            d1 = math.hypot(x1 - cx, y1 - cy)
            d2 = math.hypot(x2 - cx, y2 - cy)
            # 中心から遠い方が先端
            if d1 > d2:
                tip_x, tip_y = x1, y1
            else:
                tip_x, tip_y = x2, y2

            # 針ベクトル (中心→先端)
            needle_vec = np.array([tip_x - cx, tip_y - cy], dtype=float)
            # 基準ベクトル (中心→0目盛り)
            zero_vec = np.array([zx - cx, zy - cy], dtype=float)

            # 内角 (0〜180°)
            cos_a = np.dot(needle_vec, zero_vec) / (
                np.linalg.norm(needle_vec) * np.linalg.norm(zero_vec) + 1e-9
            )
            cos_a = np.clip(cos_a, -1.0, 1.0)
            angle_deg = math.degrees(math.acos(cos_a))

            # 符号付き角度 (外積のZ成分で方向判定)
            cross_z = needle_vec[0] * zero_vec[1] - needle_vec[1] * zero_vec[0]
            signed_angle = angle_deg if cross_z >= 0 else -angle_deg

            # ── 結果を画像に描画 ──────────────────────────
            # 検出直線
            cv2.line(img, (x1, y1), (x2, y2), (255, 180, 0), 2)

            # 基準線 (中心 → 0目盛り)
            cv2.line(img, (cx, cy), (zx, zy), (100, 220, 255), 2)

            # 中心点
            cv2.circle(img, (cx, cy), 8, (0, 255, 100), -1)
            cv2.drawMarker(img, (cx, cy), (0, 255, 100),
                           cv2.MARKER_CROSS, 30, 2)

            # 0目盛り点
            cv2.circle(img, (zx, zy), 8, (100, 220, 255), -1)
            cv2.drawMarker(img, (zx, zy), (100, 220, 255),
                           cv2.MARKER_CROSS, 20, 2)

            # 先端点
            cv2.circle(img, (tip_x, tip_y), 6, (255, 80, 80), -1)

            # 角度テキスト (背景付き)
            angle_text = f"Angle: {abs(signed_angle):.1f} deg"
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = max(0.8, min(w, h) / 600)
            thickness = 2
            (tw, th), baseline = cv2.getTextSize(
                angle_text, font, font_scale, thickness)

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
            cv2.putText(img, angle_text, (tx, ty),
                        font, font_scale, (255, 220, 80), thickness)

            # ラベル
            cv2.putText(img, "Center", (cx + 10, cy - 12),
                        font, 0.5, (0, 255, 100), 1)
            cv2.putText(img, "Zero", (zx + 8, zy - 8),
                        font, 0.5, (100, 220, 255), 1)

            self._render(img)
            self.status_var.set(
                "✅ 検出完了！リセットして再計測できます")
            self.angle_var.set(f"🎯 {abs(signed_angle):.1f}°")

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
