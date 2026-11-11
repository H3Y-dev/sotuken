import os
from datetime import date, datetime
import pandas as pd
import streamlit as st
from image_cache import get_thumbnail_path
from manager.export import (export_to_csv, export_to_jsonl, filter_readings,
    group_by_device, readings_to_series, latest_per_device,
    export_inspection_csv, inspection_options, inspection_devices)
from manager.inspection_ui import (default_inspection_id, device_choices,
    missing_devices, preview_inspection, save_inspection)
from manager.web_data_ui import load_history, load_overview, render_pending, persistent_widget


def _show_more(key, step):
    st.session_state[key] = st.session_state.get(key, step) + step

# 画面に出す列の名前と並び。DBの列名をそのまま見せると、画面の他の文言と
# 言語が揃わず作りかけに見えるため、ここで日本語へ寄せる。
_COLUMN_LABELS = {
    "id": "記録番号",
    "timestamp": "取込日時",
    "device_name": "機器名",
    "inspection_name": "点検",
    "stage": "判定",
    "value": "読み取り値",
    "pipeline_version": "版",
    "image_path": "画像",
}
_COLUMN_ORDER = ["記録番号", "取込日時", "機器名", "点検", "判定", "読み取り値", "版", "画像"]


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



def render_manual(manager):
    from manager.pipeline_caller import execute_pipeline
    st.header("画像から読み取る")

    col_input1, col_input2, col_input3 = st.columns(3)
    with col_input1:
        device_name = persistent_widget(st.text_input, "機器名", value="Gauge_01", key="manual_device")
    with col_input2:
        th_min = persistent_widget(st.number_input, "下限閾値 (Min)", key="manual_min", value=0.0, step=1.0)
    with col_input3:
        th_max = persistent_widget(st.number_input, "上限閾値 (Max)", key="manual_max", value=40.0, step=1.0)

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
                    reader_func=execute_pipeline,
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


@st.cache_data(show_spinner=False, max_entries=16)
def _render_latest(latest_rows):
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


@st.cache_data(show_spinner=False, max_entries=16)
def _render_trend(series_data):
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


def render_records(manager, receiver, device_page=False):
    st.header("機器" if device_page else "点検")
    auto_refresh = persistent_widget(st.checkbox, "自動更新(5秒ごと)", value=False, key="records_auto")

    @st.fragment(run_every="5s" if auto_refresh else None)
    def _render_records():
        if st.button("更新", key="refresh_records"):
            load_history.clear()
        history = load_history(manager.storage.db_path)
        render_pending(manager, receiver)

        inspection_labels = {None: "すべて", "": "点検なし(旧データ)"}
        for key, name, status, photos, devices in load_overview(manager, receiver):
            inspection_labels[key] = f"{name}（{status['state']}・{photos}枚・{devices}台）"
        from manager.routes import get_manifest, get_route, inspection_status, route_progress, arrived_manifest_devices
        selected_inspection = persistent_widget(st.selectbox, "点検", options=list(inspection_labels),
                                         key="selected_inspection",
                                         format_func=inspection_labels.get)

        device_options = ["すべて"] + sorted({reading.device_name for reading in history})
        history_dates = [datetime.fromisoformat(reading.captured_at or reading.received_at or reading.timestamp).date()
                         for reading in history]
        default_date_from = min(history_dates) if history_dates else date.today()
        default_date_to = max(history_dates) if history_dates else date.today()

        filter_device, filter_date_from, filter_date_to = st.columns(3)
        with filter_device:
            selected_history_device = persistent_widget(st.selectbox, "機器名", options=device_options, key="records_device")
        with filter_date_from:
            selected_date_from = persistent_widget(st.date_input, "開始日", key="records_from", value=default_date_from)
        with filter_date_to:
            selected_date_to = persistent_widget(st.date_input, "終了日", key="records_to", value=default_date_to)

        filtered_history = filter_readings(
            history,
            device_name=selected_history_device,
            date_from=selected_date_from,
            date_to=selected_date_to,
            inspection_id=selected_inspection,
        )
        st.caption(f"絞り込み結果 {len(filtered_history)}件 / 全{len(history)}件")
        if selected_inspection and not device_page:
            inspection_rows = filter_readings(history, inspection_id=selected_inspection)
            from manager.receiver import get_default_incoming_dir
            incoming_dir = getattr(receiver.get('server'), 'incoming_dir', get_default_incoming_dir())
            status = inspection_status(manager.storage, selected_inspection, incoming_dir)
            st.subheader(f"点検の受信状態: {status['state']}")
            if status['missing_photos']:
                st.warning(f"{len(status['missing_photos'])}枚未着: " + '、'.join(status['missing_photos']))
            manifest = get_manifest(manager.storage, selected_inspection)
            route_id = (manifest or {}).get('route_id') or next((r.route_id for r in inspection_rows if r.route_id), None)
            route = get_route(manager.storage, route_id) if route_id else None
            if route:
                st.subheader('ルートの撮影状況（実際に届いた写真を優先）')
                arrived = arrived_manifest_devices(manager.storage, manifest, inspection_rows, incoming_dir)
                st.dataframe(pd.DataFrame(route_progress(route, [*inspection_rows, *arrived], manifest)), use_container_width=True, hide_index=True)
            devices_table = inspection_devices(inspection_rows)
            st.subheader("この点検のメーター一覧")
            st.caption("選択した点検全体の一覧（機器名・日付の絞り込み前）")
            st.dataframe(pd.DataFrame(devices_table), use_container_width=True, hide_index=True)
            missing_id_count = sum(row["写真の枚数"] for row in devices_table if row["機器ID"] == "機器IDなし")
            st.caption(f"機器IDなしの写真: {missing_id_count}枚")
        latest_rows = latest_per_device(filtered_history)
        if device_page:
            _render_latest(latest_rows)
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
            filter_key = (selected_history_device, str(selected_date_from), str(selected_date_to), selected_inspection)
            if st.session_state.get("history_filter") != filter_key:
                st.session_state["history_limit"] = 100
                st.session_state["photo_limit"] = 20
                st.session_state["history_filter"] = filter_key
            limit = st.session_state.get("history_limit", 100)
            visible = filtered_history[:limit]
            with st.expander("全履歴", expanded=False):
                st.caption(f"{len(filtered_history)}件 / 全{len(history)}件（表示 {len(visible)}件）")
                if len(filtered_history) > limit:
                    st.button("さらに表示", key="more_history", on_click=_show_more,
                              args=("history_limit", 100))
                _render_history_table(manager.format_history_for_ui(visible))
            if not device_page:
                st.subheader("写真の一覧")
                if persistent_widget(st.checkbox, "写真を表示", value=False, key="records_photos"):
                    photo_limit = st.session_state.get("photo_limit", 20)
                    for reading in filtered_history[:photo_limit]:
                        thumb = get_thumbnail_path(reading.image_path) if reading.image_path else None
                        if thumb and os.path.exists(thumb):
                            st.image(thumb, caption=f"{reading.device_name} / 記録 {reading.id}", width=180)
                        else:
                            st.caption(f"記録 {reading.id}: 元の写真がありません。")
                    if len(filtered_history) > photo_limit:
                        st.button("写真をさらに表示", on_click=_show_more,
                                  args=("photo_limit", 20))

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

        if device_page:
            st.header("機器別の推移")
            grouped_readings = group_by_device(history)

            if not grouped_readings:
                st.info("表示できる記録がありません。")
            else:
                selected_device = persistent_widget(st.selectbox,
                    "機器", key="trend_device", options=list(grouped_readings.keys())
                )
                series_data = readings_to_series(grouped_readings[selected_device])

                if not series_data:
                    st.info("表示できる記録がありません。")
                else:
                    _render_trend(series_data)

        if device_page:
            render_judgment(manager)

    _render_records()


def render_judgment(manager):
    st.header("機器の判定")
    _choices = device_choices(manager.storage)
    if not _choices:
        st.info("機器が登録されていません。")
    else:
        _today = date.today()
        _insp_id = persistent_widget(st.text_input, "点検ID", value=default_inspection_id(), key="insp_id")
        _col_from, _col_to = st.columns(2)
        _insp_from = persistent_widget(_col_from.date_input, "開始日", value=_today, key="insp_from")
        _insp_to = persistent_widget(_col_to.date_input, "終了日", value=_today, key="insp_to")
        _insp_devices = persistent_widget(st.multiselect, "対象機器", list(_choices), default=list(_choices),
                                       format_func=_choices.get, key="insp_devices")
        _insp_result = None
        try:
            _insp_result, _insp_table = preview_inspection(
                manager.storage, _insp_id, _insp_from, _insp_to, _insp_devices)
        except ValueError as exc:
            st.error(f"機器の判定を作れません: {exc}")
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
                    st.error(f"機器の判定を書き出せませんでした: {exc}")
            _paths = st.session_state.get("insp_paths")
            if _paths:
                st.success("保存しました:\n\n" + "\n\n".join(_paths.values()))
