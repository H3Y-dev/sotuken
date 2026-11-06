"""Streamlit route editor, using the same widgets as the existing inspection UI."""
import io

import pandas as pd
import qrcode
import streamlit as st

from manager.devices import list_devices
from manager.routes import delete_route, get_route, list_routes, route_qr_payload, save_route


def render_routes(storage):
    st.header('点検ルート — 巡回で撮る機器と順番')
    st.caption('撮影する機器の一覧をスマホに渡します。機器ごとの読み取り判定は「点検結果」で確認できます。')
    routes = list_routes(storage)['routes']
    labels = {None: '新規作成', **{r['route_id']: f"{r['name']}（{r['count']}台）" for r in routes}}
    if 'route_pending_selection' in st.session_state:
        st.session_state['route_selection'] = st.session_state.pop('route_pending_selection')
    selected = st.selectbox('編集・配布するルート', list(labels), format_func=labels.get, key='route_selection')
    route = get_route(storage, selected) if selected else None
    editor_key = (selected, route['updated_at'] if route else None)
    if st.session_state.get('route_editor_key') != editor_key:
        st.session_state['route_editor_key'] = editor_key
        st.session_state['route_draft'] = list(route['devices']) if route else []
        st.session_state['route_name'] = route['name'] if route else ''
        st.session_state['route_revision'] = 0
    st.text_input('ルート名', key='route_name', max_chars=64)
    draft = st.session_state['route_draft']
    registry = list_devices(storage)
    choices = {d['device_id']: d for d in registry}
    with st.form('route_add_registered'):
        chosen = st.selectbox('既存の機器から追加', list(choices),
                              format_func=lambda k: f"{k}  {choices[k].get('device_name') or ''}") if choices else None
        if st.form_submit_button('選んだ機器を追加', disabled=not choices):
            draft.append(dict(id=chosen, name=choices[chosen].get('device_name') or chosen))
            st.session_state['route_revision'] += 1
    with st.form('route_add_manual'):
        manual_id = st.text_input('機器ID（手入力）', max_chars=32)
        manual_name = st.text_input('機器名（手入力）', max_chars=64)
        if st.form_submit_button('手入力で追加'):
            from manager.qr_label import validate_device_id, validate_device_name
            try:
                validate_device_id(manual_id)
                draft.append(dict(id=manual_id, name=validate_device_name(manual_name)))
                st.session_state['route_revision'] += 1
            except ValueError as error:
                st.error(str(error))
    st.caption('順番の数字を変更して並べ替えられます。不要な機器は「削除」にチェックしてください。')
    table = pd.DataFrame([{'順番': i + 1, '機器ID': d['id'], '機器名': d['name'], '削除': False}
                          for i, d in enumerate(draft)], columns=['順番', '機器ID', '機器名', '削除'])
    edited = st.data_editor(table, hide_index=True, use_container_width=True,
                            disabled=['機器ID'], key=f'route_devices_{selected}_{st.session_state["route_revision"]}',
                            column_config={'順番': st.column_config.NumberColumn(min_value=1, step=1),
                                           '削除': st.column_config.CheckboxColumn()})
    if st.button('ルートを保存'):
        try:
            devices = [dict(id=row['機器ID'], name=row['機器名']) for row in
                       edited.sort_values('順番', kind='stable').to_dict('records') if not row['削除']]
            saved = save_route(storage, st.session_state['route_name'], devices, selected)
            st.session_state['route_saved_message'] = f"保存しました: {saved['name']}（{saved['route_id']}）"
            st.session_state.pop('route_editor_key', None)
            st.session_state['route_pending_selection'] = saved['route_id']
            st.rerun()
        except (ValueError, TypeError) as error:
            st.error(str(error))
    if 'route_saved_message' in st.session_state:
        st.success(st.session_state.pop('route_saved_message'))
    if route:
        st.subheader('スマホへ渡すルートQR（保存済みの内容）')
        payload = route_qr_payload(route)
        if payload is None:
            st.info('機器の一覧が大きいため、Wi-Fiで取得してください。')
        else:
            image = io.BytesIO()
            qrcode.make(payload).save(image, format='PNG')
            st.image(image.getvalue(), width=320)
        st.caption(f"ルートID: {route['route_id']} ／ 更新: {route['updated_at']}")
        confirm = st.checkbox('このルートを削除することを確認しました', key=f'delete_route_{selected}')
        def remove_route():
            delete_route(storage, selected)
            st.session_state['route_pending_selection'] = None
        st.button('ルートを削除', disabled=not confirm, on_click=remove_route)
