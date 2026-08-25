import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import streamlit as st
from manager.manager import MeterManager

try:
    from reader import read_meter
except ImportError:

    def read_meter(image_path):
        return {
            "stage": "ok",
            "value": 42.5,
            "ratio": 0.425,
            "angle_deg": 120.0,
            "error": None,
        }


st.set_page_config(page_title="メーター自動読み取りシステム", layout="wide")
st.title("📟 アナログメーター自動読み取りシステム")

manager = MeterManager(db_path="manager.db")

tab1, tab2 = st.tabs(["📸 画像解析", "📜 履歴確認・CSV出力"])

with tab1:
    st.header("画像のアップロードと解析")

    col_input1, col_input2, col_input3 = st.columns(3)
    with col_input1:
        device_name = st.text_input("機器名", value="Gauge_01")
    with col_input2:
        th_min = st.number_input("下限閾値 (Min)", value=0.0, step=1.0)
    with col_input3:
        th_max = st.number_input("上限閾値 (Max)", value=40.0, step=1.0)

    uploaded_file = st.file_uploader(
        "メーター画像を選択してください", type=["jpg", "jpeg", "png"]
    )

    if uploaded_file is not None:
        temp_path = os.path.join("temp_" + uploaded_file.name)
        with open(temp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        st.image(
            uploaded_file, caption="アップロード画像", use_container_width=True
        )

        if st.button("解析実行", type="primary"):
            res = manager.process_image(
                image_path=temp_path,
                device_name=device_name,
                reader_func=read_meter,
                threshold_max=th_max,
                threshold_min=th_min,
            )

            st.success("解析が完了しました！")

            # メトリクス表示
            col1, col2 = st.columns(2)
            col1.metric("判定ステータス", res["stage"])
            col2.metric(
                "読み取り値", f"{res['val']:.2f}" if res["val"] is not None else "N/A"
            )

            # 警告アラート表示
            if res["is_alert"]:
                st.error(f"⚠️ **警告アラート**: {res['alert_message']}")
            else:
                st.info("✅ 測定値は正常範囲内です。")

            if os.path.exists(temp_path):
                os.remove(temp_path)

with tab2:
    st.header("読み取り履歴")
    history_data = manager.format_history_for_ui()

    if history_data:
        df = pd.DataFrame(history_data)
        st.dataframe(df, use_container_width=True)

        if st.button("CSV形式でエクスポート準備"):
            csv_path = manager.export_to_csv()
            with open(csv_path, "rb") as f:
                st.download_button(
                    label="CSVファイルをダウンロード",
                    data=f,
                    file_name="readings_export.csv",
                    mime="text/csv",
                )
    else:
        st.info("履歴データが存在しません。")