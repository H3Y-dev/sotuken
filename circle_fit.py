import numpy as np


def fit_circle_kasa(points):
    """
    Kåsa法による円フィッティング(シンプルな代数的最小二乗法)。

    円周の一部(狭い円弧)しか点が無い場合、推定される円が実際より
    小さく・ズレた位置に偏る(バイアスがかかる)ことが知られている。
    比較用のベースラインとして用意している。

    points: shape (N, 2) の配列。各行が (x, y)
    戻り値: (xc, yc, r)
    """
    points = np.asarray(points, dtype=float)
    x = points[:, 0]
    y = points[:, 1]
    n = len(x)

    x_m = x.mean()
    y_m = y.mean()
    u = x - x_m
    v = y - y_m

    Suu = np.sum(u * u)
    Svv = np.sum(v * v)
    Suv = np.sum(u * v)
    Suuu = np.sum(u ** 3)
    Svvv = np.sum(v ** 3)
    Suvv = np.sum(u * v * v)
    Svuu = np.sum(v * u * u)

    A = np.array([[Suu, Suv], [Suv, Svv]])
    b = np.array([Suuu + Suvv, Svvv + Svuu]) / 2.0
    uc, vc = np.linalg.solve(A, b)

    xc = x_m + uc
    yc = y_m + vc
    r = np.sqrt(uc ** 2 + vc ** 2 + (Suu + Svv) / n)

    return xc, yc, r


def fit_circle_taubin(points):
    """
    Taubin法による円フィッティング。

    Kåsa法と同じ「代数的に円の式を最小二乗で解く」枠組みだが、
    各点の勾配の大きさで正規化することで、円弧が狭い(点が円周の
    一部にしか無い)場合の偏りを大きく抑えられる。
    角形PSK-100のように円弧状の覗き窓しか見えないケースに向いている。

    points: shape (N, 2) の配列。各行が (x, y)
    戻り値: (xc, yc, r)
    """
    points = np.asarray(points, dtype=float)
    x = points[:, 0]
    y = points[:, 1]
    n = len(x)

    x_m = x.mean()
    y_m = y.mean()
    u = x - x_m
    v = y - y_m
    z = u ** 2 + v ** 2

    Mxx = np.mean(u * u)
    Myy = np.mean(v * v)
    Mxy = np.mean(u * v)
    Mxz = np.mean(u * z)
    Myz = np.mean(v * z)
    Mzz = np.mean(z * z)
    Mz = Mxx + Myy  # mean(z) と一致

    Cov_xy = Mxx * Myy - Mxy * Mxy
    A2 = 4 * Cov_xy - 3 * Mz * Mz - Mzz
    A1 = Mzz * Mz + 4 * Cov_xy * Mz - Mxz * Mxz - Myz * Myz - Mz ** 3
    A0 = (Mxz * Mxz * Myy + Myz * Myz * Mxx - Mzz * Cov_xy
          - 2 * Mxz * Myz * Mxy + Mz * Mz * Cov_xy)
    A22 = A2 + A2

    # ニュートン法で三次方程式の根を探す(Taubin法の標準的な解き方)
    xnew = 0.0
    ynew = 1e20
    epsilon = 1e-12
    iter_max = 20
    for _ in range(iter_max):
        yold = ynew
        ynew = A0 + xnew * (A1 + xnew * (A2 + 4.0 * xnew * xnew))
        if abs(ynew) > abs(yold):
            # 収束しない場合はKåsa法相当(xnew=0)にフォールバック
            xnew = 0.0
            break
        Dy = A1 + xnew * (A22 + 16.0 * xnew * xnew)
        xold = xnew
        xnew = xold - ynew / Dy
        if abs((xnew - xold) / xnew) < epsilon:
            break

    det = xnew * xnew - xnew * Mz + Cov_xy
    xc_local = (Mxz * (Myy - xnew) - Myz * Mxy) / det / 2.0
    yc_local = (Myz * (Mxx - xnew) - Mxz * Mxy) / det / 2.0

    xc = xc_local + x_m
    yc = yc_local + y_m
    r = np.sqrt(xc_local ** 2 + yc_local ** 2 + Mz)

    return xc, yc, r


def fit_circle_to_ticks(ticks, method="taubin"):
    """
    tick_detect.py の detect_scale_ticks が返す ticks
    (各要素が dict で "centroid" キーを持つ想定)から、
    centroid の点群に円をフィッティングする。

    method: "taubin"(既定, 円弧が狭い場合にも強い) または "kasa"
    戻り値: {"center": (xc, yc), "radius": r, "method": method}
    """
    points = np.array([t["centroid"] for t in ticks], dtype=float)

    if method == "kasa":
        xc, yc, r = fit_circle_kasa(points)
    elif method == "taubin":
        xc, yc, r = fit_circle_taubin(points)
    else:
        raise ValueError(f"unknown method: {method}")

    return {"center": (float(xc), float(yc)), "radius": float(r), "method": method}


# ------------------------------------------------------------------
# 動作確認: 合成データ(正解の中心・半径が既知)でKåsa法とTaubin法を比較
# ------------------------------------------------------------------
def _make_synthetic_ticks(true_center, true_radius, arc_deg_span, n_points, noise_std, seed):
    """
    円周上(円弧の一部)にランダムなノイズ付きの点を生成し、
    tick_detect.py の出力形式(centroidを持つdict)に似せて返す。
    """
    rng = np.random.default_rng(seed)
    xc, yc = true_center
    start_deg = rng.uniform(0, 360)
    angles_deg = start_deg + rng.uniform(0, arc_deg_span, size=n_points)
    angles = np.radians(angles_deg)

    xs = xc + true_radius * np.cos(angles) + rng.normal(0, noise_std, n_points)
    ys = yc + true_radius * np.sin(angles) + rng.normal(0, noise_std, n_points)

    return [{"centroid": (x, y)} for x, y in zip(xs, ys)]


def _run_comparison(label, true_center, true_radius, arc_deg_span, n_points=24, noise_std=1.5, seed=0):
    ticks = _make_synthetic_ticks(true_center, true_radius, arc_deg_span, n_points, noise_std, seed)

    kasa = fit_circle_to_ticks(ticks, method="kasa")
    taubin = fit_circle_to_ticks(ticks, method="taubin")

    def err(result):
        cx, cy = result["center"]
        r = result["radius"]
        center_err = np.hypot(cx - true_center[0], cy - true_center[1])
        radius_err = abs(r - true_radius)
        return center_err, radius_err

    kasa_center_err, kasa_radius_err = err(kasa)
    taubin_center_err, taubin_radius_err = err(taubin)

    print(f"=== {label} (円弧の範囲: {arc_deg_span}度, 点数: {n_points}) ===")
    print(f"正解:   中心={true_center}, 半径={true_radius}")
    print(f"Kåsa法:  中心={tuple(round(v, 1) for v in kasa['center'])}, "
          f"半径={kasa['radius']:.1f}  "
          f"(中心誤差={kasa_center_err:.1f}px, 半径誤差={kasa_radius_err:.1f}px)")
    print(f"Taubin法: 中心={tuple(round(v, 1) for v in taubin['center'])}, "
          f"半径={taubin['radius']:.1f}  "
          f"(中心誤差={taubin_center_err:.1f}px, 半径誤差={taubin_radius_err:.1f}px)")
    print()


if __name__ == "__main__":
    true_center = (490.0, 497.0)  # meter1.jpgで実際に検出できた中心座標を正解として使用
    true_radius = 400.0

    # ケース1: 目盛りが円周をほぼ一周(270度)している場合(円形メーター相当)
    _run_comparison("円弧270度(速度計・圧力計相当)", true_center, true_radius, arc_deg_span=270)

    # ケース2: 目盛りが円周の一部(90度)にしか無い場合(角形PSK-100相当)
    _run_comparison("円弧90度(角形PSK-100相当)", true_center, true_radius, arc_deg_span=90)

    # ケース3: さらに狭い円弧(60度)の場合
    _run_comparison("円弧60度(より厳しい条件)", true_center, true_radius, arc_deg_span=60)
