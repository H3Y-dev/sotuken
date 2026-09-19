import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import streamlit as st
from manager.export import export_to_csv, export_to_jsonl, filter_readings, group_by_device, readings_to_series
from manager.manager import MeterManager

from manager.pipeline_caller import execute_pipeline


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
    "stage": "判定",
    "value": "読み取り値",
    "pipeline_version": "版",
    "image_path": "画像",
}
_COLUMN_ORDER = ["記録番号", "取込日時", "機器名", "判定", "読み取り値", "版", "画像"]


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

manager = MeterManager(db_path="manager.db")
_record_count = len(manager.get_history())

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

tab1, tab2 = st.tabs(["読み取り", "記録"])

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

        if st.button("読み取る", type="primary"):
            res = manager.process_image(
                image_path=temp_path,
                device_name=device_name,
                reader_func=read_meter,
                threshold_max=th_max,
                threshold_min=th_min,
            )

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

            if os.path.exists(temp_path):
                os.remove(temp_path)

with tab2:
    st.header("読み取りの記録")
    history = manager.get_history()
    device_options = ["すべて"] + sorted({reading.device_name for reading in history})
    history_dates = [datetime.fromisoformat(reading.timestamp).date() for reading in history]
    default_date_from = min(history_dates) if history_dates else date.today()
    default_date_to = max(history_dates) if history_dates else date.today()

    filter_device, filter_date_from, filter_date_to = st.columns(3)
    with filter_device:
        selected_history_device = st.selectbox("機器名", options=device_options)
    with filter_date_from:
        selected_date_from = st.date_input("開始日", value=default_date_from)
    with filter_date_to:
        selected_date_to = st.date_input("終了日", value=default_date_to)

    if history:
        filtered_history = filter_readings(
            history,
            device_name=selected_history_device,
            date_from=selected_date_from,
            date_to=selected_date_to,
        )
        filtered_ids = {reading.id for reading in filtered_history}
        history_data = manager.format_history_for_ui()
        filtered_history_data = [row for row in history_data if row["id"] in filtered_ids]

        st.caption(f"{len(filtered_history_data)}件 / 全{len(history_data)}件")
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
            if overlay_path and os.path.exists(overlay_path):
                st.image(overlay_path, caption="検出結果オーバーレイ", use_container_width=True)
            else:
                st.caption("この記録にはオーバーレイ画像がありません。")

        if st.button("CSVを書き出す"):
            csv_path = "readings_export.csv"
            export_to_csv(manager.get_history(), csv_path)
            with open(csv_path, "rb") as f:
                st.download_button(
                    label="CSVを保存",
                    data=f,
                    file_name="readings_export.csv",
                    mime="text/csv",
                )

        if st.button("JSONLを書き出す"):
            jsonl_path = "readings_export.jsonl"
            export_to_jsonl(manager.get_history(), jsonl_path)
            with open(jsonl_path, "rb") as f:
                st.download_button(
                    label="JSONLを保存",
                    data=f,
                    file_name="readings_export.jsonl",
                    mime="application/x-ndjson",
                )
    else:
        st.caption("0件 / 全0件")
        st.info("履歴データが存在しません。")

    st.header("機器別の推移")
    grouped_readings = group_by_device(manager.get_history())

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
