import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import streamlit as st
from image_cache import get_thumbnail_path
from manager.export import (export_to_csv, export_to_jsonl, filter_readings,
                            group_by_device, readings_to_series,
                            latest_per_device, export_inspection_csv, inspection_options, inspection_devices)
from manager.inspection_ui import (default_inspection_id, device_choices, missing_devices,
                                   preview_inspection, save_inspection)
from manager.manager import MeterManager

from manager.pipeline_caller import execute_pipeline
from manager.receiver import init_receiver_for_app, pairing_qr_png


def read_meter(image_path, use_vlm=False):
    """UIからの解析要求を、実際のパイプライン(meter_pipeline)へ渡す。

    以前はここが `from reader import read_meter` の失敗時に 42.5 を返す
    ダミー実装へ落ちる作りになっていた。reader.py はリポジトリに存在せず、
    UIは常にダミー値を表示していた（画面上はそれと分からない）。
    """
    return execute_pipeline(image_path, use_vlm=use_vlm)


# 画面に出す列の名前と並び。DBの列名をそのまま見せると、画面の他の文言と
# 言語が揃わず作りかけに見えるため、ここで日本語へ寄せる。
_COLUMN_LABELS = {
    "id": "記録番号",
    "timestamp": "取込日時",
    "device_name": "機器名",
    "inspection_name": "点検（巡回）",
    "stage": "判定",
    "value": "読み取り値",
    "pipeline_version": "版",
    "image_path": "画像",
}
_COLUMN_ORDER = ["記録番号", "取込日時", "機器名", "点検（巡回）", "判定", "読み取り値", "版", "画像"]


def _to_display_table(rows):
    """履歴の行を、画面に出す形へ整える。"""
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.rename(columns=_COLUMN_LABELS)
    if "画像" in df.columns:
        # フルパスは横幅を食うだけで、記録を見る用途では file 名で足りる
        df["画像"] = df["画像"].map(lambda v: os.path.basename(str(v)) if v else "")
    if "版" in df.columns:
        df["版"] = df["版"].fillna("")
    return df[[c for c in _COLUMN_ORDER if c in df.columns]]


@st.fragment
def _render_history_table(filtered_history_data):
    """記録の表と、選んだ行のオーバーレイ表示を局所再実行（fragment）する。"""
    selection_event = st.dataframe(
        _to_display_table(filtered_history_data),
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
    )
    selected_rows = selection_event.selection.rows if selection_event.selection else []
    if selected_rows:
        selected_row = filtered_history_data[selected_rows[0]]
        overlay_path = selected_row.get("overlay_path")
        thumb_path = get_thumbnail_path(overlay_path) if overlay_path else None
        if thumb_path and os.path.exists(thumb_path):
            st.image(thumb_path, caption="検出結果オーバーレイ", use_container_width=True)
            if overlay_path and os.path.exists(overlay_path):
                try:
                    with open(overlay_path, "rb") as f:
                        file_bytes = f.read()
                    mime_type = "image/png" if overlay_path.lower().endswith(".png") else "image/jpeg"
                    st.download_button(
                        label="原寸画像",
                        data=file_bytes,
                        file_name=os.path.basename(overlay_path),
                        mime=mime_type,
                        key=f"orig_img_{selected_row.get('id', 'selected')}",
                    )
                except Exception:
                    pass
        else:
            st.caption("この記録にはオーバーレイ画像がありません。")


st.set_page_config(
    page_title="メーター読み取り記録",
    layout="wide",
    initial_sidebar_state="collapsed",
)


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


try:
    _receiver_info = init_receiver_for_app()
except (ValueError, OSError) as exc:
    _receiver_info = {"running": False, "error": str(exc)}

with st.sidebar:
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

@st.cache_data
def _get_cached_history(db_path: str, mtime: float):
    """DBファイルの更新時刻（os.path.getmtime）をキーにして履歴取得をキャッシュする。"""
    mgr = MeterManager(db_path=db_path)
    return mgr.get_history(include_raw=False)


_db_path = "manager.db"
_db_mtime = os.path.getmtime(_db_path) if os.path.exists(_db_path) else 0.0
manager = MeterManager(db_path=_db_path)
history = _get_cached_history(_db_path, _db_mtime)
_record_count = len(history)

# 銘板。計器に貼られている銘板と同じ情報の並べ方にしてある。
st.markdown(
    f"""
    <div class="nameplate">
      <div class="nameplate-row">
        <h1>アナログメーター読み取り記録</h1>
        <div class="sub">記録 {_record_count} 件 ｜ 許容差 ±2.5 %FS ｜ JIS B 7505-1 2.5級相当</div>
      </div>
    </div>
    <div class="tickrule"></div>
    """,
    unsafe_allow_html=True,
)

tab1, tab2, tab3 = st.tabs(["読み取り", "記録", "点検結果"])

with tab1:
    st.header("画像から読み取る")

    col_input1, col_input2, col_input3 = st.columns(3)
    with col_input1:
        device_name = st.text_input("機器名", value="Gauge_01")
    with col_input2:
        th_min = st.number_input("下限閾値 (Min)", value=0.0, step=1.0)
    with col_input3:
        th_max = st.number_input("上限閾値 (Max)", value=40.0, step=1.0)

    uploaded_file = st.file_uploader(
        "画像を選ぶ", type=["jpg", "jpeg", "png"]
    )

    if uploaded_file is not None:
        temp_path = os.path.join("temp_" + uploaded_file.name)
        with open(temp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        st.image(
            uploaded_file, caption="読み取る画像", use_container_width=True
        )

        res = None
        if st.button("読み取る", type="primary"):
            try:
                # 原画像は images/ へ複製してから読む。temp は後で消すため、記録は複製を指す
                res = manager.process_image(
                    image_path=temp_path,
                    device_name=device_name,
                    reader_func=read_meter,
                    threshold_max=th_max,
                    threshold_min=th_min,
                    overlays_dir="overlays",
                    images_dir="images",
                )
            except Exception as exc:
                # 記録は作られていない。原画像を失わないよう temp は残す
                st.error(f"記録できませんでした（{exc}）。元の画像は {temp_path} に残しています。")

        if res is not None:
            st.success("読み取りました。")

            # メトリクス表示
            col1, col2 = st.columns(2)
            col1.metric("判定", res["stage"])
            col2.metric(
                "読み取り値", f"{res['val']:.2f}" if res["val"] is not None else "—"
            )

            # 警告アラート表示
            if res["is_alert"]:
                st.error(f"設定した範囲を外れています: {res['alert_message']}")
            else:
                st.info("測定値は設定した範囲内です。")

            # どこを中心・目盛り・針として検出したかを、その場で確かめられるようにする
            if res["overlay_path"] and os.path.exists(res["overlay_path"]):
                st.image(res["overlay_path"], caption="検出結果オーバーレイ", use_container_width=True)
            else:
                st.caption("検出結果のオーバーレイ画像は作れませんでした（中心を検出できなかったため）。")

            if os.path.exists(temp_path):
                os.remove(temp_path)

with tab2:
    st.header("読み取りの記録")
    device_options = ["すべて"] + sorted({reading.device_name for reading in history})
    history_dates = [datetime.fromisoformat(reading.captured_at or reading.received_at or reading.timestamp).date()
                     for reading in history]
    default_date_from = min(history_dates) if history_dates else date.today()
    default_date_to = max(history_dates) if history_dates else date.today()

    filter_device, filter_date_from, filter_date_to = st.columns(3)
    with filter_device:
        selected_history_device = st.selectbox("機器名", options=device_options)
    with filter_date_from:
        selected_date_from = st.date_input("開始日", value=default_date_from)
    with filter_date_to:
        selected_date_to = st.date_input("終了日", value=default_date_to)

    inspections = inspection_options(history)
    inspection_labels = {None: "すべて", "": "点検なし(旧データ)"}
    inspection_labels.update({key: f"{name}（{count}件）" for key, name, count in inspections})
    selected_inspection = st.selectbox("点検（巡回）", options=list(inspection_labels),
                                     format_func=inspection_labels.get)

    filtered_history = filter_readings(
        history,
        device_name=selected_history_device,
        date_from=selected_date_from,
        date_to=selected_date_to,
        inspection_id=selected_inspection,
    )
    st.caption(f"絞り込み結果 {len(filtered_history)}件 / 全{len(history)}件")
    if selected_inspection:
        inspection_rows = filter_readings(history, inspection_id=selected_inspection)
        devices_table = inspection_devices(inspection_rows)
        st.subheader("この点検のメーター一覧")
        st.caption("選択した点検全体の一覧（機器名・日付の絞り込み前）")
        st.dataframe(pd.DataFrame(devices_table), use_container_width=True, hide_index=True)
        missing_id_count = sum(row["写真の枚数"] for row in devices_table if row["機器ID"] == "機器IDなし")
        st.caption(f"機器IDなしの写真: {missing_id_count}枚")
    latest_rows = latest_per_device(filtered_history)
    st.header("各メーターの最新の読み取り")
    if latest_rows:
        latest_table = pd.DataFrame([
            {"メーター名": row["display_name"],
             "読み取り値": "-" if row["value"] is None else str(row["value"]),
             "時刻": datetime.fromisoformat(row["timestamp"]).strftime("%Y-%m-%d %H:%M"),
             "状態": row["status_label"]}
            for row in latest_rows[:50]
        ])
        status_colors = {"正常": "color: #24643B", "要確認": "color: #805500",
                         "失敗": "color: #B42318"}
        st.dataframe(latest_table.style.applymap(status_colors.get, subset=["状態"]),
                     use_container_width=True, hide_index=True)
        if len(latest_rows) > 50:
            st.caption(f"ほか{len(latest_rows) - 50}件は全履歴で確認できます")
    else:
        st.info("表示できる記録がありません。")

    review_count = sum(row["status_label"] == "要確認" for row in latest_rows)
    failed_count = sum(row["status_label"] == "失敗" for row in latest_rows)
    unnamed_count = sum(row["display_name"] == "名前なし" for row in latest_rows)
    st.caption(f"要確認 {review_count}件・失敗 {failed_count}件・名前なし {unnamed_count}件")
    if st.button("点検の結果を書き出す"):
        try:
            st.session_state["inspection_csv_path"] = export_inspection_csv(latest_rows)
        except Exception as exc:
            st.session_state.pop("inspection_csv_path", None)
            st.error(f"点検の結果を書き出せませんでした: {exc}")
    inspection_path = st.session_state.get("inspection_csv_path")
    if inspection_path:
        st.success(f"保存しました: {inspection_path}")
        if os.name == "nt" and st.button("フォルダを開く"):
            try:
                os.startfile(os.path.dirname(inspection_path))
            except OSError:
                pass

    if history:
        filtered_ids = {reading.id for reading in filtered_history}
        history_data = manager.format_history_for_ui(history)
        filtered_history_data = [row for row in history_data if row["id"] in filtered_ids]

        with st.expander("全履歴", expanded=False):
            st.caption(f"{len(filtered_history_data)}件 / 全{len(history_data)}件")
            _render_history_table(filtered_history_data)

        if st.button("CSVを書き出す"):
            csv_path = "readings_export.csv"
            export_to_csv(filtered_history, csv_path)
            with open(csv_path, "rb") as f:
                st.download_button(
                    label="CSVを保存",
                    data=f,
                    file_name="readings_export.csv",
                    mime="text/csv",
                )

        if st.button("JSONLを書き出す"):
            jsonl_path = "readings_export.jsonl"
            export_to_jsonl(filtered_history, jsonl_path)
            with open(jsonl_path, "rb") as f:
                st.download_button(
                    label="JSONLを保存",
                    data=f,
                    file_name="readings_export.jsonl",
                    mime="application/x-ndjson",
                )
    else:
        with st.expander("全履歴", expanded=False):
            st.caption("0件 / 全0件")
            st.info("履歴データが存在しません。")

    st.header("機器別の推移")
    grouped_readings = group_by_device(history)

    if not grouped_readings:
        st.info("表示できる記録がありません。")
    else:
        selected_device = st.selectbox(
            "機器", options=list(grouped_readings.keys())
        )
        series_data = readings_to_series(grouped_readings[selected_device])

        if not series_data:
            st.info("表示できる記録がありません。")
        else:
            chart_df = pd.DataFrame(
                list(series_data.items()), columns=["captured_at", "value"]
            )
            chart_df["captured_at"] = pd.to_datetime(chart_df["captured_at"])
            st.line_chart(
                chart_df.sort_values("captured_at").set_index("captured_at"),
                # 記録計の青ペン。画面の他の数値表示と同じ色で揃える。
                color="#2B4A6F",
                height=280,
            )

with tab3:
    st.header("点検結果")
    _choices = device_choices(manager.storage)
    if not _choices:
        st.info("機器が登録されていません。")
    else:
        _today = date.today()
        _insp_id = st.text_input("点検ID", value=default_inspection_id(), key="insp_id")
        _col_from, _col_to = st.columns(2)
        _insp_from = _col_from.date_input("開始日", value=_today, key="insp_from")
        _insp_to = _col_to.date_input("終了日", value=_today, key="insp_to")
        _insp_devices = st.multiselect("対象機器", list(_choices), default=list(_choices),
                                       format_func=_choices.get, key="insp_devices")
        _insp_result = None
        try:
            _insp_result, _insp_table = preview_inspection(
                manager.storage, _insp_id, _insp_from, _insp_to, _insp_devices)
        except ValueError as exc:
            st.error(f"点検結果を作れません: {exc}")
        if _insp_result is not None:
            if _insp_table:
                st.dataframe(pd.DataFrame(_insp_table), use_container_width=True, hide_index=True)
            else:
                st.info("期間内に対象機器の記録がありません。")
            _missing = missing_devices(_insp_result)
            if _missing:
                st.warning("期間内に撮影が無い機器: " + "、".join(_missing))
            if st.button("書き出す", type="primary", key="insp_export"):
                try:
                    st.session_state["insp_paths"] = save_inspection(_insp_result)
                except Exception as exc:
                    st.session_state.pop("insp_paths", None)
                    st.error(f"点検結果を書き出せませんでした: {exc}")
            _paths = st.session_state.get("insp_paths")
            if _paths:
                st.success("保存しました:\n\n" + "\n\n".join(_paths.values()))

