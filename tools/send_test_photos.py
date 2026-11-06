# 点検テスト用: 点検ID付きの写真を4枚、PCの受信口へ送る(確認専用。ファイルは書き換えない)
# 使い方: venv\Scripts\python.exe send_test_photos.py [ポート] [合言葉]  (省略すると manager\pc_config.json から読む)
import base64, hashlib, json, os, sys, urllib.request, urllib.error
root = os.path.dirname(os.path.abspath(__file__))
while not os.path.exists(os.path.join(root, "manager", "receiver.py")):
    root = os.path.dirname(root)
cfg = json.load(open(os.path.join(root, "manager", "pc_config.json"), encoding="utf-8")) if os.path.exists(os.path.join(root, "manager", "pc_config.json")) else {}
port = int(sys.argv[1]) if len(sys.argv) > 1 else int(cfg.get("port", 8765))
token = sys.argv[2] if len(sys.argv) > 2 else cfg.get("token", "")
img = open(os.path.join(root, "eval", "images", "meter1.png"), "rb").read()
photos = [  # (点検ID, 点検名, 機器ID, 機器名)
    ("T-20261106-A", "朝の点検(テスト)", "A-101", "点検テスト ボイラー"),
    ("T-20261106-A", "朝の点検(テスト)", "A-101", "点検テスト ボイラー"),
    ("T-20261106-A", "朝の点検(テスト)", "A-102", "点検テスト 冷却水"),
    ("T-20261106-B", "夕方の点検(テスト)", "A-101", "点検テスト ボイラー"),
]
for i, (iid, iname, did, dname) in enumerate(photos, 1):
    body = img + bytes([i])  # 内容を変えて、別の写真にする
    side = {"local_id": 9000 + i, "captured_at": f"2026-11-06T1{i}:00:00+09:00", "device_name": dname, "device_id": did,
            "device_id_source": "qr", "inspection_id": iid, "inspection_name": iname}
    name = f"20261106T0{i}0000_{9000 + i}.jpg"
    h = {"X-Sotuken-Token": token, "X-File-Name": name, "Content-Length": str(len(body)),
         "X-Sidecar-Json": base64.urlsafe_b64encode(json.dumps(side, ensure_ascii=False).encode()).decode().rstrip("="),
         "X-Image-Sha256": hashlib.sha256(body).hexdigest()}
    r = urllib.request.Request(f"http://127.0.0.1:{port}/upload", data=body, headers=h, method="POST")
    try:
        with urllib.request.urlopen(r) as x: print(i, x.status, x.read().decode()[:80])
    except urllib.error.HTTPError as e: print(i, e.code, e.read().decode()[:80])
