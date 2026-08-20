"""
アナログメーター針角度検出・数値変換プログラム
使い方:
  1. プログラムを起動して画像ファイルを選択
  2. 針の中心点を自動検出（HoughCircles）または手動クリックで指定
  3. 目盛り線をPCAで自動検出し、中心点を再推定
     OCR（RapidOCR）で盤面の数字を読み取り目盛り線と対応付けて
     0目盛り・フルスケール目盛りを自動決定。対応付けの信頼度が低い場合は
     VLM（Ollama+Qwen2.5-VL）にmin_value/max_valueだけを問い合わせて補う
     （どちらも失敗した場合は手動クリックにフォールバック）
  4. 針をOpenCVで自動検出して角度と数値を表示
"""
import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

import cv2
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from PIL import Image, ImageTk
import math
import threading

import tick_detect
import scale_value_detect
import vlm_scale_value
import detection_logger


class MeterAngleDetector:
    def __init__(self, root):
        self.root = root
        self.root.title("アナログメーター 角度検出・数値変換")
        self.root.configure(bg="#1e1e2e")

        self.image_raw = None      # ファイルから読み込んだそのままの画像
        self.image_original = None  # 以降の処理に使う画像（VLMでクロップ後の場合あり）
        self.image_path = None     # 開いた画像ファイルのパス（ログ記録用）
        self.photo = None

        self.center_point = None
        self.zero_point = None
        self.fullscale_point = None
        self.val_min = 0.0
        self.val_max = 100.0
        # 0=中心待ち, 1=ゼロ点待ち, 2=フルスケール点待ち, 3=完了
        self.click_step = 0
        self._last_overlay = None  # 直前に表示したオーバーレイ画像（リサイズ再描画用）
        # 針が0の目盛りに重なっており、0点が目視確認できていないケースかどうか
        self.zero_needle_overlap = False

        self.auto_center_candidate = None  # (x, y, radius) or None
        self.detected_ticks = []           # PCAで検出した目盛り線のリスト
        self.auto_scale_candidate = None   # OCR自動検出した0/フルスケール候補
        self._scale_request_id = 0        # リセット時に古いスレッド結果を破棄するためのID

        self.canvas_width = 800
        self.canvas_height = 600
        self.scale = 1.0
        self.offset_x = 0
        self.offset_y = 0

        self._build_ui()
        self._warmup_models()

    def _warmup_models(self):
        """
        RapidOCRのモデルを起動直後にバックグラウンドで読み込んでおく。
        遅延ロードのままだと、最初の画像処理時にモデルの初期化待ちで
        GUIが応答しなくなる（フリーズして見える）ことがあるため、
        画像を開く前の“暇な時間”に済ませておく。
        """
        def worker():
            try:
                scale_value_detect.read_scale_numbers(np.zeros((32, 32, 3), dtype=np.uint8))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

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

        # ── 目盛り数値 自動検出確認フレーム ───────────────────
        self.confirm_scale_frame = tk.Frame(self.root, bg="#2a2a3e", pady=6)

        self.scale_info_var = tk.StringVar(value="")
        self.scale_info_label = tk.Label(
            self.confirm_scale_frame,
            textvariable=self.scale_info_var,
            font=("Helvetica", 10, "bold"),
            fg="#cba6f7", bg="#2a2a3e"
        )
        self.scale_info_label.pack(side=tk.LEFT, padx=16)

        tk.Button(
            self.confirm_scale_frame, text="✅ この値を使用",
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
        self.image_raw = img
        self.image_path = path
        self.reset()

    def reset(self):
        self.center_point = None
        self.zero_point = None
        self.fullscale_point = None
        self.val_min = 0.0
        self.val_max = 100.0
        self.click_step = 0
        self.zero_needle_overlap = False
        self.auto_center_candidate = None
        self.detected_ticks = []
        self.auto_scale_candidate = None
        self._scale_request_id += 1  # 実行中スレッドの結果を無効化
        self.angle_var.set("")
        self._hide_confirm_frame()
        self._hide_confirm_scale_frame()

        if self.image_raw is None:
            self.image_original = None
            self.status_var.set("📂 まず画像を開いてください")
            return

        # クロップ待ちの間も元画像を表示しておく（クロップに失敗すればこのまま使う）
        self.image_original = self.image_raw
        self._render()
        self.status_var.set("🔍 メーター領域を検出中...")
        self._try_meter_crop()

    def _try_meter_crop(self):
        """
        VLMでメーター盤面のおおまかな矩形領域を検出し、背景を除いた画像に
        差し替える。背景の模様・文字等が中心検出や目盛り検出を誤らせる
        ことがあるため、以降の処理は全てこのクロップ画像に対して行う。
        取得・クロップに失敗した場合は元画像のまま処理を続行する
        （精度は落ちるが、これまで通り検出自体は動く）。
        """
        request_id = self._scale_request_id
        img = self.image_raw

        def worker():
            cropped = None
            try:
                bbox = vlm_scale_value.detect_meter_bbox(img)
                if bbox is not None:
                    cropped = tick_detect.crop_with_margin(img, bbox)
            except Exception:
                cropped = None
            self.root.after(0, lambda: self._on_meter_crop_result(cropped, request_id))

        threading.Thread(target=worker, daemon=True).start()

    def _on_meter_crop_result(self, cropped, request_id):
        if request_id != self._scale_request_id:
            return  # リセット・新規画像で無効化済み

        if cropped is not None:
            self.image_original = cropped
            self._render()

        self._start_center_detection()

    def _start_center_detection(self):
        self.status_var.set("🔍 中心点を検出中...")
        hough_candidate = self._auto_detect_center()
        self._refine_center_candidate(hough_candidate)

    # ── Step1: Hough円検出で中心点候補を取得 ─────────────────
    def _auto_detect_center(self):
        return tick_detect.auto_detect_center(self.image_original)

    def _refine_center_candidate(self, hough_candidate):
        """
        Hough円検出の結果を、目盛り線の交点による推定と突き合わせて補正する。
        目盛り線は幾何学的に必ず中心を向くため、Houghが反射やリベット等の
        別の丸い模様を誤検出した場合でも、こちらで実際の中心に近づけられる。
        Hough自体が失敗した場合は、画像中心を起点に目盛り線から推定する
        （従来のフォールバックと同等）。目盛り検出は重い処理なので
        バックグラウンドスレッドで行う。
        """
        request_id = self._scale_request_id
        img = self.image_original
        h, w = img.shape[:2]
        seed = (hough_candidate[0], hough_candidate[1]) if hough_candidate is not None \
            else (w // 2, h // 2)

        def worker():
            try:
                refined, _ticks = tick_detect.refine_center_iterative(img, seed)
            except Exception:
                refined = None
            self.root.after(
                0, lambda: self._on_center_candidate_ready(hough_candidate, refined, request_id))

        threading.Thread(target=worker, daemon=True).start()

    def _on_center_candidate_ready(self, hough_candidate, refined, request_id):
        if request_id != self._scale_request_id:
            return  # リセット・新規画像で無効化済み

        h, w = self.image_original.shape[:2]
        default_r = int(min(h, w) * 0.05)

        if hough_candidate is not None and refined is not None:
            hx, hy, r = hough_candidate
            shift = math.hypot(refined[0] - hx, refined[1] - hy)
            if shift > min(h, w) * 0.03:
                # 目盛り線の交点がHoughの結果と大きくズレている
                # → Houghの誤検出とみなし、目盛り線側を採用する
                self.auto_center_candidate = (refined[0], refined[1], r)
                self._show_auto_candidate(source='corrected')
            else:
                self.auto_center_candidate = (hx, hy, r)
                self._show_auto_candidate(source='hough')
        elif hough_candidate is not None:
            hx, hy, r = hough_candidate
            self.auto_center_candidate = (hx, hy, r)
            self._show_auto_candidate(source='hough')
        elif refined is not None:
            self.auto_center_candidate = (refined[0], refined[1], default_r)
            self._show_auto_candidate(source='ticks')
        else:
            self.status_var.set(
                "🎯 Step 1: 針の中心点をクリックしてください（自動検出できませんでした）")

    def _show_auto_candidate(self, source='hough'):
        cx, cy, r = self.auto_center_candidate
        overlay = self.image_original.copy()
        cv2.circle(overlay, (cx, cy), r, (0, 230, 255), 2)
        cv2.circle(overlay, (cx, cy), 6, (0, 230, 255), -1)
        cv2.drawMarker(overlay, (cx, cy), (0, 230, 255), cv2.MARKER_CROSS, 28, 2)
        self._render(overlay)
        self.confirm_frame.pack(fill=tk.X, before=self.status_frame)
        if source == 'ticks':
            self.status_var.set(
                f"🔍 目盛り線から中心点を推定しました ({cx}, {cy})"
                " — 円検出が失敗したための簡易推定です。確定するか手動で選択してください")
        elif source == 'corrected':
            self.status_var.set(
                f"🔧 円検出の位置を目盛り線の交点で補正しました ({cx}, {cy})"
                " — 確定するか手動で選択してください")
        else:
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
        self.detected_ticks = []
        self._draw_markers()
        self.status_var.set("🔍 目盛り線を検出中...")

        request_id = self._scale_request_id

        def worker():
            # ワーカー全体を保護する。RapidOCR/Ollamaの呼び出し失敗など
            # ここで例外を捕らずに落ちると、root.after が一度も呼ばれず
            # メイン画面が「検出中...」のまま無言で固まって見えてしまうため、
            # 何が起きても必ずメインスレッドへ結果（またはエラー）を返す。
            ticks, center, auto_scale, error = [], self.center_point, None, None
            vlm_reason = ""
            try:
                # CLAHEでコントラストを強調してから目盛り線を検出する。
                # 反射・グレアや低コントラストな盤面では元画像のままだと
                # 目盛りが疎らにしか検出できず、中心点の再推定（最小二乗法）が
                # 少数の偏った目盛りに引っ張られて大きくズレることがある
                # （実測: 元画像13本→中心が25px ズレ／CLAHE適用後36本→ズレ6px）。
                enhanced = tick_detect.apply_clahe(self.image_original, clip_limit=2.0)
                ticks = tick_detect.detect_scale_ticks(enhanced, self.center_point)

                # 中心点をtick_detectの目盛り線交点で再推定してからOCR対応付けに使う
                # （中心が不正確なほど角度がズレ、数字とのbindingが失敗しやすくなるため）
                center = self.center_point
                if len(ticks) >= 3:
                    refined = tick_detect.refine_center_from_ticks(
                        ticks, center, self.image_original.shape)
                    if refined is not None:
                        center = refined

                # OCR（RapidOCR）で数字を読み取り目盛り線と対応付けて0/フルスケールを推定
                # （信頼度が低い場合はscale_value_detect内部でVLMにも問い合わせる）
                try:
                    auto_scale = scale_value_detect.detect_scale_values(
                        self.image_original, ticks, center)
                except Exception:
                    auto_scale = None

                if auto_scale is None:
                    # 自動検出が全滅した場合のみ、VLM（Ollama）が使える状態か診断する。
                    # read_min_max等は失敗理由を問わず一律Noneを返す設計なので、
                    # ここで原因（未起動・モデル未取得等）を切り分けてユーザーに示す。
                    try:
                        available, reason = vlm_scale_value.check_availability()
                        if not available:
                            vlm_reason = reason
                    except Exception:
                        pass
            except Exception as e:
                error = str(e)

            # メインスレッドへ結果を渡す（リセット済みなら無視）
            self.root.after(
                0, lambda: self._on_ticks_detected(
                    ticks, center, auto_scale, error, vlm_reason, request_id))

        threading.Thread(target=worker, daemon=True).start()

    def _on_ticks_detected(self, ticks, center, auto_scale, error, vlm_reason, request_id):
        """目盛り線・目盛り数値検出スレッドの結果をメインスレッドで受け取る"""
        if request_id != self._scale_request_id:
            return  # リセット・新規画像で無効化済み

        self.detected_ticks = ticks
        self.center_point = center
        self._draw_markers()

        if error is not None:
            self.status_var.set(
                f"⚠️ 目盛り検出中にエラーが発生しました（{error}）。"
                "📍 Step 2: 0（最小値）の目盛り方向をクリックしてください")
            return

        if auto_scale is not None:
            self.auto_scale_candidate = auto_scale
            self._show_scale_candidate()
            return

        # 自動でのmin/max判定に失敗している。VLMが原因で使えなかった場合は
        # その理由を表示する（Ollama未起動・モデル未取得等、環境依存の問題を
        # 自己診断できるように）。
        vlm_note = f"　⚠️ VLM補完も利用できません: {vlm_reason}" if vlm_reason else ""
        if ticks:
            self.status_var.set(
                f"📍 Step 2: 0（最小値）の目盛り方向をクリックしてください "
                f"（目盛り線を{len(ticks)}本検出、クリック位置は自動でスナップします）{vlm_note}")
        else:
            self.status_var.set(
                "📍 Step 2: 0（最小値）の目盛り方向をクリックしてください "
                f"（目盛り線を検出できなかったためクリック位置をそのまま使用します）{vlm_note}")

    # ── 目盛り数値の自動検出候補をオーバーレイ表示 ─────────────
    def _show_scale_candidate(self):
        c = self.auto_scale_candidate
        overlay = self.image_original.copy()
        for t in self.detected_ticks:
            color = (0, 200, 255) if t['is_major'] else (110, 110, 110)
            radius = 4 if t['is_major'] else 2
            pt = (int(round(t['centroid'][0])), int(round(t['centroid'][1])))
            cv2.circle(overlay, pt, radius, color, -1)

        cx, cy = self.center_point
        cv2.drawMarker(overlay, (cx, cy), (0, 255, 100), cv2.MARKER_CROSS, 30, 2)
        cv2.circle(overlay, (cx, cy), 8, (0, 255, 100), -1)

        zero_pt, full_pt = c['zero_pt'], c['full_pt']
        font = cv2.FONT_HERSHEY_SIMPLEX

        cv2.line(overlay, (cx, cy), zero_pt, (100, 220, 255), 2)
        cv2.circle(overlay, zero_pt, 10, (100, 220, 255), 2)
        cv2.putText(overlay, f"Zero({c['min_value']:.4g})",
                    (zero_pt[0] + 8, zero_pt[1] - 8), font, 0.5, (100, 220, 255), 1)

        cv2.line(overlay, (cx, cy), full_pt, (180, 100, 255), 2)
        cv2.circle(overlay, full_pt, 10, (180, 100, 255), 2)
        cv2.putText(overlay, f"Full({c['max_value']:.4g})",
                    (full_pt[0] + 8, full_pt[1] - 8), font, 0.5, (180, 100, 255), 1)

        self._render(overlay)
        self.confirm_scale_frame.pack(fill=tk.X, before=self.status_frame)

        is_confident = c.get('is_confident', True)
        source = c.get('source', 'ocr_tick')
        if c.get('needle_overlap_zero'):
            # 針が0の目盛りに重なっているとVLMで確認できたケース。
            # is_confidentの値に関わらず、0の位置は実際には目視確認できて
            # いない（等間隔性からの推定または座標合成）ことを必ず警告する。
            self.scale_info_label.configure(fg="#f9e2af")
            self.scale_info_var.set(
                f"⚠️ 針が0の目盛りに重なっており0の位置を直接確認できませんでした"
                f"（目盛り間隔から推定）: 最小値={c['min_value']:.4g}  最大値={c['max_value']:.4g}"
            )
            self.status_var.set(
                "⚠️ 針が0付近を指しているため、0の位置は自動検出で目視確認できていません。"
                "ズレていないか必ず確認してから選んでください")
        elif is_confident and source == 'vlm':
            self.scale_info_label.configure(fg="#cba6f7")
            self.scale_info_var.set(
                f"🤖 OCRの対応付けが不十分だったためVLMで補完: "
                f"最小値={c['min_value']:.4g}  最大値={c['max_value']:.4g}"
            )
            self.status_var.set(
                "VLMの助けを借りて目盛りの数値を検出しました — "
                "確定・入れ替え・手動選択のいずれかを選んでください")
        elif is_confident:
            self.scale_info_label.configure(fg="#cba6f7")
            self.scale_info_var.set(
                f"🔎 OCRで自動検出: 最小値={c['min_value']:.4g}  最大値={c['max_value']:.4g}  "
                f"（数字と目盛りの対応 {c['n_used']}/{c['n_total']} 件を採用）"
            )
            self.status_var.set(
                "目盛りの数値を自動検出しました — 確定・入れ替え・手動選択のいずれかを選んでください")
        else:
            self.scale_info_label.configure(fg="#f38ba8")
            self.scale_info_var.set(
                f"⚠️ 精度が低い可能性があります: 最小値={c['min_value']:.4g}  最大値={c['max_value']:.4g}  "
                f"（数字と目盛りの対応がわずか {c['n_used']}/{c['n_total']} 件）"
            )
            self.status_var.set(
                "⚠️ 対応付けできた数字が少なく誤りの可能性があります。"
                "目盛り線と数値をよく確認してから選んでください")

    def _hide_confirm_scale_frame(self):
        self.confirm_scale_frame.pack_forget()

    def _confirm_scale_auto(self):
        if self.auto_scale_candidate is None:
            return
        c = self.auto_scale_candidate
        self.zero_point = c['zero_pt']
        self.fullscale_point = c['full_pt']
        self.val_min = c['min_value']
        self.val_max = c['max_value']
        self.zero_needle_overlap = c.get('needle_overlap_zero', False)
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
            'zero_pt': c['full_pt'],
            'full_pt': c['zero_pt'],
            'min_value': c['max_value'],
            'max_value': c['min_value'],
            'n_used': c['n_used'],
            'n_total': c['n_total'],
            'is_confident': c.get('is_confident', True),
            'source': c.get('source', 'ocr_tick'),
            # 「針が0の目盛りに重なっている」という判定は、入れ替え前のzero_ptに
            # 対して行ったものなので、入れ替え後の新しいzero_pt（＝元のfull_pt）
            # には当てはまらない。そのまま引き継ぐと、実際には目視確認できている
            # 点に警告が出る一方、本当に不確かな点の警告が消えてしまう。
            'needle_overlap_zero': False,
        }
        self._show_scale_candidate()

    def _reject_scale_auto(self):
        """OCRの自動検出結果を破棄して手動クリックに切り替える"""
        self.auto_scale_candidate = None
        self._hide_confirm_scale_frame()
        self.click_step = 1
        self._draw_markers()
        self.status_var.set("📍 Step 2: 0（最小値）の目盛り方向をクリックしてください")

    # ── キャンバスへの描画 ────────────────────────────────────
    def _render(self, overlay=None):
        self._last_overlay = overlay
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
        # リサイズ時は直前に表示していたオーバーレイ（目盛り線・中心/ゼロ/フルスケールの
        # マーカーや検出結果の描画）をそのまま使って再描画する。ここで overlay 無しの
        # _render() を呼ぶと、表示中のマーカーや針の直線が消えて素の画像に戻ってしまい、
        # 「ウィンドウをリサイズすると検出位置の表示が不安定になる」ように見えていた。
        if self.image_original is not None:
            self._render(self._last_overlay)

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
            # クリック位置に最も近い検出済み目盛り線があればスナップする
            self.zero_point = tick_detect.snap_to_tick(
                (ix, iy), self.center_point, self.detected_ticks)
            self.click_step = 2
            self.status_var.set("📍 Step 3: フルスケール（最大値）の目盛り方向をクリックしてください")
            self._draw_markers()

        elif self.click_step == 2:
            self.fullscale_point = tick_detect.snap_to_tick(
                (ix, iy), self.center_point, self.detected_ticks)
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
        for t in self.detected_ticks:
            color = (0, 200, 255) if t['is_major'] else (110, 110, 110)
            radius = 4 if t['is_major'] else 2
            pt = (int(round(t['centroid'][0])), int(round(t['centroid'][1])))
            cv2.circle(overlay, pt, radius, color, -1)
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
            zero_warning = (
                "　⚠️ 0の位置は目視確認できていません（針の重なりから推定）"
                if self.zero_needle_overlap else "")
            self.status_var.set(
                f"✅ 検出完了！  角度: {abs_angle:.1f}°  値: {value:.2f}  "
                f"（{self.val_min} ～ {self.val_max}）{zero_warning}")
            self.angle_var.set(f"📊 {value:.2f}  ({abs_angle:.1f}°)")

            try:
                detection_logger.save_detection_log(
                    self.image_original,
                    {
                        "center": [cx, cy],
                        "zero_point": [zx, zy],
                        "fullscale_point": [fsx, fsy],
                        "val_min": self.val_min,
                        "val_max": self.val_max,
                        "angle_deg": round(abs_angle, 2),
                        "value": round(value, 4),
                        "needle_line": [int(x1), int(y1), int(x2), int(y2)],
                        "needle_tip": [int(tip_x), int(tip_y)],
                        "zero_needle_overlap": self.zero_needle_overlap,
                    },
                    source_path=self.image_path,
                )
            except Exception:
                pass  # ログ保存の失敗で検出結果表示自体を止めない

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
