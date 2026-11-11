"""Shared, versioned DB snapshots and the administrator's landing page."""
from copy import deepcopy
from pathlib import Path

import streamlit as st

from manager.manager import MeterManager
from manager.pending_images import pending_images
from manager.receiver import get_default_incoming_dir
from manager.routes import inspection_status


def persistent_widget(widget, *args, key, **kwargs):
    """Keep input state outside Streamlit's disposable widget keys."""
    saved_key = f'persisted_{key}'
    # data_editor rejects session_state assignment; restore its table instead.
    if widget == st.data_editor:
        base_key = f'{saved_key}_base'
        if key not in st.session_state:
            st.session_state[base_key] = deepcopy(st.session_state.get(saved_key, args[0]))
        result = widget(st.session_state[base_key], *args[1:], key=key, **kwargs)
        st.session_state[saved_key] = deepcopy(result)
        return result
    if key not in st.session_state and saved_key in st.session_state:
        st.session_state[key] = deepcopy(st.session_state[saved_key])
    result = widget(*args, key=key, **kwargs)
    st.session_state[saved_key] = deepcopy(st.session_state[key])
    return result


def database_version(db_path):
    # SQLite may write only the WAL; metadata edits need invalidation too.
    path = Path(db_path).resolve()
    versions = []
    for name in (str(path), str(path) + '-wal'):
        try:
            stat = Path(name).stat()
            versions.append((stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            versions.append(None)
    return str(path), tuple(versions)


@st.cache_data(show_spinner=False, max_entries=16)
def _history(db_path, version):
    return MeterManager(db_path=db_path).get_history(include_raw=False)


def load_history(db_path):
    path, version = database_version(db_path)
    return _history(path, version)


load_history.clear = _history.clear


def incoming_path(receiver):
    return getattr(receiver.get('server'), 'incoming_dir', get_default_incoming_dir())


def render_pending(manager, receiver):
    try:
        count, names = pending_images(incoming_path(receiver), manager.storage)
    except OSError as exc:
        st.warning(f'読み取り待ちの確認ができませんでした: {exc}')
    else:
        if count:
            st.info(f'読み取り中 {count}枚')
            st.caption('、'.join(names))
        else:
            st.caption('読み取り中 0枚')


def inspection_list(manager, history):
    with manager.storage.connection() as conn:
        rows = conn.execute('SELECT inspection_id, inspection_name, started_at FROM inspections').fetchall()
    inspections = {key: [name or key, started or '', []] for key, name, started in rows}
    for reading in history:
        if reading.inspection_id:
            item = inspections.setdefault(reading.inspection_id,
                [reading.inspection_name or reading.inspection_id, reading.timestamp, []])
            item[2].append(reading)
    return [(key, name, readings) for key, (name, started, readings) in
            sorted(inspections.items(), key=lambda item: (item[1][1], item[0]), reverse=True)]


def load_overview(manager, receiver):
    path, version = database_version(manager.storage.db_path)
    incoming = Path(incoming_path(receiver)).resolve()
    try:
        files = tuple(sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns)
                             for p in incoming.iterdir() if p.is_file()))
    except FileNotFoundError:
        files = ()
    return _overview(path, version, str(incoming), files)


@st.cache_data(show_spinner=False, max_entries=16)
def _overview(path, version, incoming, files):
    manager = MeterManager(db_path=path)
    history = _history(path, version)
    return [(key, name, inspection_status(manager.storage, key, incoming),
             len(readings), len({r.device_id or r.device_name for r in readings}))
            for key, name, readings in inspection_list(manager, history)]


def _open_inspection(inspection_id):
    st.session_state['selected_inspection'] = inspection_id
    st.session_state['page'] = '点検'


def render_home(manager, receiver):
    st.header('ホーム')
    if receiver.get('running'):
        st.caption(f"受信口: 待ち受け中 / {receiver['url']}")
    else:
        st.warning(f"受信口が起動していません: {receiver.get('error')}")
    auto = persistent_widget(st.checkbox, '自動更新(5秒ごと)', value=False, key='home_auto')

    @st.fragment(run_every='5s' if auto else None)
    def summary():
        if st.button('更新', key='refresh_home'):
            load_history.clear()
        render_pending(manager, receiver)
        st.subheader('最近の点検')
        inspections = load_overview(manager, receiver)
        if not inspections:
            st.info('点検はまだありません。スマホから点検を送信すると表示されます。')
        for key, name, status, photos, devices in inspections[:5]:
            if st.button(name, key=f'open_{key}', on_click=_open_inspection, args=(key,)):
                st.rerun()
            st.caption(f"{status['state']} / 写真 {max(photos, status['matched'])}枚 / 機器 {devices}台")
    summary()
