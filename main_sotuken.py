"""
アナログメーター針角度検出プログラム
使い方:
  1. プログラムを起動して画像ファイルを選択
  2. 針の中心点をクリック
  3. 基準となる0の目盛り方向をクリック
  4. 針をOpenCVで自動検出して角度を表示
"""

import cv2
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import math
import os
import re
import shutil


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
        self.max_point = None        # 最大目盛り点
        # 0=中心待ち, 1=0目盛り待ち, 2=最大目盛り待ち, 3=完了
        self.click_step = 0
        self.cw_override = None       # None=自動, True=時計回り, False=反時計回り
        self._last_tip = None         # 直近の針先端 (方向再計算用)

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

        tk.Button(
            header, text="🤖 自動検出",
            command=self._auto_detect,
            font=("Helvetica", 11),
            bg="#a6e3a1", fg="#1e1e2e",
            relief=tk.FLAT, padx=12, pady=4, cursor="hand2"
        ).pack(side=tk.RIGHT, padx=4)

        # ── 目盛り設定 ────────────────────────────────────────
        settings = tk.Frame(self.root, bg="#1e1e2e", pady=4)
        settings.pack(fill=tk.X, padx=16)

        tk.Label(settings, text="目盛り設定:", font=("Helvetica", 10, "bold"),
                 fg="#cdd6f4", bg="#1e1e2e").pack(side=tk.LEFT, padx=(0, 8))

        tk.Label(settings, text="0目盛りの値", font=("Helvetica", 10),
                 fg="#bac2de", bg="#1e1e2e").pack(side=tk.LEFT)
        self.min_value_var = tk.StringVar(value="0")
        tk.Entry(settings, textvariable=self.min_value_var, width=8,
                 font=("Helvetica", 10), justify=tk.CENTER
                 ).pack(side=tk.LEFT, padx=(2, 12))

        tk.Label(settings, text="最大目盛りの値", font=("Helvetica", 10),
                 fg="#bac2de", bg="#1e1e2e").pack(side=tk.LEFT)
        self.max_value_var = tk.StringVar(value="100")
        tk.Entry(settings, textvariable=self.max_value_var, width=8,
                 font=("Helvetica", 10), justify=tk.CENTER
                 ).pack(side=tk.LEFT, padx=(2, 12))

        self.dir_var = tk.StringVar(value="方向: 自動")
        tk.Button(settings, textvariable=self.dir_var,
                  command=self._cycle_direction,
                  font=("Helvetica", 10), bg="#cba6f7", fg="#1e1e2e",
                  relief=tk.FLAT, padx=10, pady=2, cursor="hand2"
                  ).pack(side=tk.LEFT, padx=4)

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
        self.max_point = None
        self.click_step = 0
        self._last_tip = None
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
            self.status_var.set("📈 Step 3: 最大目盛りの方向をクリックしてください")
            self._draw_markers()

        elif self.click_step == 2:
            self.max_point = (ix, iy)
            self.click_step = 3
            self.status_var.set("🔍 針を検出中...")
            self.root.update()
            self._detect_and_show()

    # ── 自動検出 ──────────────────────────────────────────────
    def _auto_detect(self):
        if self.image_original is None:
            messagebox.showinfo("情報", "先に画像を開いてください")
            return

        self.center_point = None
        self.zero_point = None
        self.max_point = None
        self.click_step = 0
        self._last_tip = None
        self.angle_var.set("")
        self.status_var.set("🤖 自動検出中...")
        self.root.update()

        img = self.image_original
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w = img.shape[:2]

        # ── 中心点: HoughCircles ──
        blurred = cv2.GaussianBlur(gray, (9, 9), 2)
        circles = cv2.HoughCircles(
            blurred,
            cv2.HOUGH_GRADIENT,
            dp=1,
            minDist=min(h, w) // 2,
            param1=100,
            param2=30,
            minRadius=min(h, w) // 5,
            maxRadius=min(h, w) // 2,
        )

        if circles is None:
            self.status_var.set("⚠️ 円検出失敗。手動で中心点をクリックしてください")
            messagebox.showwarning(
                "自動検出失敗",
                "メーターの円を自動検出できませんでした。\n手動で中心点をクリックしてください。"
            )
            return

        circles = np.round(circles[0]).astype(int)
        # 最も半径の大きい円を使用
        cx, cy, _ = max(circles, key=lambda c: c[2])
        self.center_point = (int(cx), int(cy))
        self.click_step = 1
        self._draw_markers()

        # ── 0目盛り: OCR ──
        try:
            import pytesseract

            # Tesseract 実行ファイルを自動検索
            tess_cmd = shutil.which("tesseract")
            if tess_cmd is None:
                for candidate in [
                    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                ]:
                    if os.path.exists(candidate):
                        tess_cmd = candidate
                        break
            if tess_cmd:
                pytesseract.pytesseract.tesseract_cmd = tess_cmd

            # 前処理: 2倍拡大 → 暗背景なら反転 → Otsu 2値化
            scale = 2
            gray_ocr = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            enlarged = cv2.resize(gray_ocr, None, fx=scale, fy=scale,
                                  interpolation=cv2.INTER_CUBIC)
            is_dark_bg = float(np.mean(gray_ocr)) < 128
            prep = cv2.bitwise_not(enlarged) if is_dark_bg else enlarged
            blurred = cv2.GaussianBlur(prep, (5, 5), 0)
            _, thresh = cv2.threshold(blurred, 0, 255,
                                      cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            pil_img = Image.fromarray(thresh)

            data = pytesseract.image_to_data(
                pil_img,
                output_type=pytesseract.Output.DICT,
                lang="eng",
                config="--psm 11",
            )

            zero_direct = []
            best_hits = {}  # val → (conf, bx, by)  同一値は高信頼度のみ残す

            for i, text in enumerate(data["text"]):
                t = text.strip()
                if not t:
                    continue
                conf = int(data["conf"][i])
                bx = (data["left"][i] + data["width"][i] // 2) // scale
                by = (data["top"][i] + data["height"][i] // 2) // scale

                if t == "0":
                    zero_direct.append((bx, by))

                nums = re.findall(r"\d+", t)
                if nums and conf > 40:
                    val = int(nums[0])
                    if 1 <= val <= 9999:
                        if val not in best_hits or conf > best_hits[val][0]:
                            best_hits[val] = (conf, bx, by)

            numeric_hits = [(val, bx, by)
                            for val, (_, bx, by) in best_hits.items()]

            # OCRで読めた最大の数値を「最大目盛り」として採用
            if numeric_hits:
                mval, mbx, mby = max(numeric_hits, key=lambda x: x[0])
                self.max_point = (int(mbx), int(mby))
                self.max_value_var.set(str(mval))
                self.min_value_var.set("0")

            # ── パス1: "0" が直接検出された場合 ──
            if zero_direct:
                zx, zy = max(zero_direct,
                             key=lambda p: math.hypot(p[0] - cx, p[1] - cy))
                self.zero_point = (int(zx), int(zy))
                self.click_step = 3
                self.status_var.set("🔍 自動検出完了（直接）、針を検出中...")
                self.root.update()
                self._detect_and_show()
                return

            # ── パス2: 他の数値から線形外挿 ──
            if len(numeric_hits) < 3:
                self.status_var.set("⚠️ OCRで「0」を検出できず。手動でクリックしてください")
                messagebox.showwarning(
                    "OCR失敗",
                    "「0」の目盛りを自動検出できませんでした。\n手動でクリックしてください。"
                )
                return

            # 各数値の中心からの角度を計算してソート
            av_list = sorted(
                [(val, math.atan2(by - cy, bx - cx), bx, by)
                 for val, bx, by in numeric_hits],
                key=lambda x: x[0],
            )

            # 角度アンラップ（0/2π境界をまたぐ場合に対応）
            unwrapped = [av_list[0][1]]
            for i in range(1, len(av_list)):
                diff = av_list[i][1] - unwrapped[-1]
                while diff > math.pi:
                    diff -= 2 * math.pi
                while diff < -math.pi:
                    diff += 2 * math.pi
                unwrapped.append(unwrapped[-1] + diff)

            values = [av[0] for av in av_list]
            angles = unwrapped

            # 線形回帰: angle = a*value + b
            n = len(values)
            mean_v = sum(values) / n
            mean_a = sum(angles) / n
            cov = sum((values[i] - mean_v) * (angles[i] - mean_a) for i in range(n))
            var = sum((values[i] - mean_v) ** 2 for i in range(n))
            if var < 1e-10:
                self.status_var.set("⚠️ 線形回帰失敗。手動でクリックしてください")
                messagebox.showwarning("検出失敗",
                    "0目盛りの位置を計算できませんでした。\n手動でクリックしてください。")
                return

            # RANSAC: 全ペアを試して最多インライアモデルで再フィット
            ransac_thresh = math.radians(20)
            best_inliers = []
            for ii in range(n):
                for jj in range(ii + 1, n):
                    dv = values[jj] - values[ii]
                    if abs(dv) < 1e-10:
                        continue
                    a_t = (angles[jj] - angles[ii]) / dv
                    b_t = angles[ii] - a_t * values[ii]
                    inl = [k for k in range(n)
                           if abs(angles[k] - (a_t * values[k] + b_t)) <= ransac_thresh]
                    if len(inl) > len(best_inliers):
                        best_inliers = inl

            fit_v = [values[k] for k in best_inliers]
            fit_a = [angles[k] for k in best_inliers]
            nf = len(fit_v)
            mvf, maf = sum(fit_v) / nf, sum(fit_a) / nf
            covf = sum((fit_v[i] - mvf) * (fit_a[i] - maf) for i in range(nf))
            varf = sum((fit_v[i] - mvf) ** 2 for i in range(nf))
            a_coef = covf / varf if varf >= 1e-10 else cov / var
            b_coef = (maf - a_coef * mvf) if varf >= 1e-10 else (mean_a - (cov / var) * mean_v)
            zero_angle = b_coef

            inlier_set = set(fit_v)
            use_hits = [(v, bx, by) for v, bx, by in numeric_hits
                        if v in inlier_set] or numeric_hits
            avg_r = sum(math.hypot(bx - cx, by - cy)
                        for _, bx, by in use_hits) / len(use_hits)
            zx = int(cx + avg_r * math.cos(zero_angle))
            zy = int(cy + avg_r * math.sin(zero_angle))

            self.zero_point = (zx, zy)
            self.click_step = 3
            self.status_var.set("🔍 自動検出完了（線形外挿）、針を検出中...")
            self.root.update()
            self._detect_and_show()

        except ImportError:
            self.status_var.set("⚠️ pytesseract未インストール。手動でクリックしてください")
            messagebox.showerror(
                "エラー",
                "pytesseractがインストールされていません。\n"
                "pip install pytesseract を実行してください。"
            )
        except Exception as e:
            self.status_var.set("⚠️ OCRエラー。手動でクリックしてください")
            messagebox.showerror("自動検出エラー", f"エラーが発生しました:\n{e}")

    # ── マーカーだけ描いて表示 ────────────────────────────────
    def _draw_markers(self):
        overlay = self.image_original.copy()
        if self.center_point:
            cv2.drawMarker(overlay, self.center_point, (0, 255, 100),
                           cv2.MARKER_CROSS, 30, 2)
            cv2.circle(overlay, self.center_point, 8, (0, 255, 100), -1)
        if self.zero_point:
            if self.center_point:
                cv2.line(overlay, self.center_point, self.zero_point,
                         (100, 220, 255), 1)
            cv2.circle(overlay, self.zero_point, 7, (100, 220, 255), -1)
        if self.max_point:
            if self.center_point:
                cv2.line(overlay, self.center_point, self.max_point,
                         (255, 120, 200), 1)
            cv2.circle(overlay, self.max_point, 7, (255, 120, 200), -1)
        self._render(overlay)

    # ── 方向切替 (自動 → 時計回り → 反時計回り → …) ──────────
    def _cycle_direction(self):
        if self.cw_override is None:
            self.cw_override = True
            self.dir_var.set("方向: 時計回り")
        elif self.cw_override is True:
            self.cw_override = False
            self.dir_var.set("方向: 反時計回り")
        else:
            self.cw_override = None
            self.dir_var.set("方向: 自動")
        # 既に検出済みなら数値を再計算して表示し直す
        if (self.click_step >= 3 and self.image_original is not None
                and self.max_point is not None):
            self._detect_and_show()

    # ── 角度 → 数値 変換 ──────────────────────────────────────
    def _compute_value(self, tip_x, tip_y):
        """中心・0目盛り・最大目盛りと針先端から数値を線形換算する。
        戻り値 (value, cw)。max_point 未設定/入力不正なら (None, None)。"""
        if self.max_point is None:
            return None, None
        cx, cy = self.center_point
        zx, zy = self.zero_point
        mx, my = self.max_point
        try:
            min_val = float(self.min_value_var.get())
            max_val = float(self.max_value_var.get())
        except ValueError:
            return None, None

        # 画像座標 (y下向き) では atan2 の増加 = 画面上の時計回り
        th_zero = math.atan2(zy - cy, zx - cx)
        th_max = math.atan2(my - cy, mx - cx)
        th_needle = math.atan2(tip_y - cy, tip_x - cx)

        two_pi = 2 * math.pi
        full_cw = (th_max - th_zero) % two_pi
        full_ccw = (th_zero - th_max) % two_pi
        needle_cw = (th_needle - th_zero) % two_pi
        needle_ccw = (th_zero - th_needle) % two_pi

        if self.cw_override is True:
            cw = True
        elif self.cw_override is False:
            cw = False
        else:
            # 自動: 針が 0→最大 の掃引範囲内に収まる向きを優先
            cw_ok = needle_cw <= full_cw + 1e-6
            ccw_ok = needle_ccw <= full_ccw + 1e-6
            if cw_ok and not ccw_ok:
                cw = True
            elif ccw_ok and not cw_ok:
                cw = False
            else:
                cw = full_cw <= full_ccw

        full = full_cw if cw else full_ccw
        needle_prog = needle_cw if cw else needle_ccw
        if full < 1e-6:
            return None, cw
        value = min_val + (needle_prog / full) * (max_val - min_val)
        return value, cw

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

            # ── 角度 → 数値 変換 ──────────────────────────
            self._last_tip = (tip_x, tip_y)
            value, cw = self._compute_value(tip_x, tip_y)

            # ── 結果を画像に描画 ──────────────────────────
            # 検出直線
            cv2.line(img, (x1, y1), (x2, y2), (255, 180, 0), 2)

            # 基準線 (中心 → 0目盛り)
            cv2.line(img, (cx, cy), (zx, zy), (100, 220, 255), 2)

            # 最大目盛り線 (中心 → 最大目盛り)
            if self.max_point is not None:
                mx, my = self.max_point
                cv2.line(img, (cx, cy), (mx, my), (255, 120, 200), 2)
                cv2.circle(img, (mx, my), 8, (255, 120, 200), -1)
                cv2.putText(img, "Max", (mx + 8, my - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 120, 200), 1)

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

            # 角度テキスト (背景付き)。数値が計算できた場合は数値を主表示
            if value is not None:
                angle_text = f"{value:.2f}  ({abs(signed_angle):.1f} deg)"
            else:
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
            if value is not None:
                dir_name = ("時計回り" if cw else "反時計回り")
                self.status_var.set(
                    f"✅ 検出完了！(掃引方向: {dir_name}) "
                    "リセットして再計測できます")
                self.angle_var.set(
                    f"🎯 {value:.2f}　(角度 {abs(signed_angle):.1f}°)")
            else:
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
            self.click_step = 2
            self.max_point = None
            self.status_var.set(
                "⚠️ 検出失敗。Step 3: 再度 最大目盛りをクリックしてください")


# ── エントリポイント ──────────────────────────────────────────
def main():
    root = tk.Tk()
    root.geometry("900x700")
    app = MeterAngleDetector(root)
    root.mainloop()


if __name__ == "__main__":
    main()
