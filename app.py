import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamlit as st
from manager.manager import MeterManager
from manager.receiver import init_receiver_for_app, pairing_qr_png
from manager.web_data_ui import render_home

st.set_page_config(page_title="メーター読み取り記録", layout="wide", initial_sidebar_state="expanded")

def _load_style():
    """画面のスタイルを読み込む。無ければ既定の見た目のまま動かす。"""
    css_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_style.css")
    if not os.path.exists(css_path):
        return
    with open(css_path, encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


_load_style()


@st.fragment(run_every="1s")
def _show_pairing(server):
    current_url = init_receiver_for_app()["url"]
    if st.button("スマホを登録"):
        server.start_pairing(current_url)
    if st.button("登録を中止"):
        server.cancel_pairing()
    status = server.pairing_status()
    if status is None:
        st.caption("登録済み・期限切れ・中止後は、QRを作り直してください。")
        return
    if status["payload"]["url"] != current_url:
        server.cancel_pairing()
        st.warning("PCのURLが変わりました。QRを作り直してください。")
        return
    payload = server.pairing_payload()
    if payload is not None:
        st.image(pairing_qr_png(payload), caption="スマホの送信先QR読取で登録してください")
        st.caption(f"残り {status['remaining']} 秒")
        st.text(status["payload"]["url"])
        st.caption("交換に失敗した場合や応答が届かない場合は、QRを作り直してください。")


@st.fragment(run_every="2s")
def _show_usb_pull():
    """run_pc.py --usb-pull で起動したUSB吸い出しサービスの状態を表示する。"""
    from manager.usb_pull_service import get_usb_pull_status
    status = get_usb_pull_status()
    if not status or not status.get("running"):
        return
    st.divider()
    st.markdown("**USB吸い出し: 動作中**")
    st.caption(f"端末 {len(status.get('devices') or [])}台")
    st.caption(f"吸い出した累計: {status.get('pulled_total', 0)}組")
    if status.get("last_error"):
        st.warning(status["last_error"])


try:
    _receiver_info = init_receiver_for_app()
except (ValueError, OSError) as exc:
    _receiver_info = {"running": False, "error": str(exc)}

def render_settings():
    st.header("スマホの送信先")
    if _receiver_info.get("running"):
        if _receiver_info.get("external_process"):
            st.info("別プロセスで起動済みです")
        st.caption("同じWi-Fiに接続したスマホアプリの送信先設定に入力してください。")
        st.markdown(f"**送信先URL**:\n`{_receiver_info['url']}`")
        with st.expander("手入力用の合言葉を表示"):
            st.code(_receiver_info['token'])
        if _receiver_info.get("server") is not None:
            _show_pairing(_receiver_info["server"])
        else:
            st.caption("QR登録は受信口を起動した画面で行ってください。別プロセスを停止してこの画面を再読み込みすると利用できます。")
    else:
        st.error(f"受信口が起動していません: {_receiver_info.get('error')}")
        if _receiver_info.get("url"):
            st.markdown(f"**設定予定URL**:\n`{_receiver_info['url']}`")
    _show_usb_pull()


with st.sidebar:
    st.caption("受信口: 待ち受け中" if _receiver_info.get("running") else "受信口: 停止中")
    page = st.radio("画面", ["ホーム", "点検", "機器", "ルート", "接続・設定", "手動読み取り(開発用)"], key="page")

manager = MeterManager(db_path="manager.db")
# 銘板。計器に貼られている銘板と同じ情報の並べ方にしてある。
st.markdown(
    f"""
    <div class="nameplate">
      <div class="nameplate-row">
        <h1>アナログメーター読み取り記録</h1>
        <div class="sub">点検・機器・写真の管理 ｜ 許容差 ±2.5 %FS ｜ JIS B 7505-1 2.5級相当</div>
      </div>
    </div>
    <div class="tickrule"></div>
    """,
    unsafe_allow_html=True,
)


if page == "ホーム":
    render_home(manager, _receiver_info)
elif page in ("点検", "機器"):
    from manager.web_pages_ui import render_records
    render_records(manager, _receiver_info, device_page=page == "機器")
elif page == "ルート":
    from manager.routes_ui import render_routes
    render_routes(manager.storage)
elif page == "接続・設定":
    render_settings()
else:
    from manager.web_pages_ui import render_manual
    render_manual(manager)
