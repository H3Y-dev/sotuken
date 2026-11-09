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
    # --usb-pull はこのスクリプト専用のオプション。Streamlit には渡さない。
    streamlit_args = sys.argv[1:]
    usb_pull_enabled = "--usb-pull" in streamlit_args
    if usb_pull_enabled:
        streamlit_args = [arg for arg in streamlit_args if arg != "--usb-pull"]

    # 1. 起動時に受信口をバックグラウンドで起動（ブラウザを開かなくても待受開始）
    receiver_info = init_receiver_for_app()
    if receiver_info.get("running"):
        if receiver_info.get("external_process"):
            print(f"[受信口] 別プロセスで起動済みです: {receiver_info.get('url')}")
        else:
            print(f"[受信口] 待ち受け開始: {receiver_info.get('url')}")
    else:
        print(f"[受信口] 警告: 受信口の起動に失敗しました: {receiver_info.get('error')}")

    # USB吸い出しは --usb-pull が指定されたときだけ起動する。
    if usb_pull_enabled:
        from manager.usb_pull_service import init_usb_pull_for_app
        init_usb_pull_for_app()
        print("[USB吸い出し] 動作中 (--usb-pull)")

    # 2. 続けて同じプロセスでStreamlitを起動 (streamlit run app.py 相当)
    app_path = os.path.join(REPO_ROOT, "app.py")
    sys.argv = ["streamlit", "run", app_path] + streamlit_args
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
