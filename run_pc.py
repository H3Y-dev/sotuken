"""
PC用起動スクリプト (run_pc.py)。
1. 起動時に受信口 (manager/receiver.py) をバックグラウンドスレッドで起動。
2. 続けて同じプロセスで Streamlit (app.py) を起動。
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from manager.receiver import init_receiver_for_app
from streamlit.web import cli as stcli


def main() -> None:
    # 1. 起動時に受信口をバックグラウンドで起動（ブラウザを開かなくても待受開始）
    receiver_info = init_receiver_for_app()
    if receiver_info.get("running"):
        if receiver_info.get("external_process"):
            print(f"[受信口] 別プロセスで起動済みです: {receiver_info.get('url')}")
        else:
            print(f"[受信口] 待ち受け開始: {receiver_info.get('url')}")
            print(f"[受信口] 合言葉 (Token): {receiver_info.get('token')}")
    else:
        print(f"[受信口] 警告: 受信口の起動に失敗しました: {receiver_info.get('error')}")

    # 2. 続けて同じプロセスでStreamlitを起動 (streamlit run app.py 相当)
    app_path = os.path.join(REPO_ROOT, "app.py")
    sys.argv = ["streamlit", "run", app_path] + sys.argv[1:]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
