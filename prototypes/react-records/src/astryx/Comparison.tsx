import { useState } from 'react';
import { Card } from '@astryxdesign/core/Card';
import { VStack } from '@astryxdesign/core/VStack';
import { Badge } from '@astryxdesign/core/Badge';
import { Table, TableHeader, TableBody, TableRow, TableCell, TableHeaderCell } from '@astryxdesign/core/Table';
import '@astryxdesign/core/astryx.css';
import { data } from '../mock/data';
import { filterReadings, latestPerDevice } from '../lib/records';

export default function Comparison() {
  const [inspection, setInspection] = useState('all');
  const [device, setDevice] = useState('all');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const rows = latestPerDevice(filterReadings(data, { inspection, device, start, end }));
  const status = (r: typeof data[number]) => !r.device || r.status === 'low_confidence' ? '要確認' : r.status === 'failed' ? '失敗' : '正常';
  return <VStack><Card><h1>機器の最新値（Astryx比較）</h1>
    <label>点検 <select value={inspection} onChange={e => setInspection(e.target.value)}><option value="all">すべて</option><option value="none">点検なし</option>{[...new Set(data.map(r => r.inspection).filter(Boolean))].map(x => <option key={x}>{x}</option>)}</select></label>
    <label>機器名 <select value={device} onChange={e => setDevice(e.target.value)}><option value="all">すべて</option>{[...new Set(data.map(r => r.device).filter(Boolean))].map(x => <option key={x}>{x}</option>)}</select></label>
    <label>開始日 <input type="date" value={start} onChange={e => setStart(e.target.value)} /></label>
    <label>終了日 <input type="date" value={end} onChange={e => setEnd(e.target.value)} /></label>
    <Table><TableHeader><TableRow><TableHeaderCell>機器</TableHeaderCell><TableHeaderCell>日時</TableHeaderCell><TableHeaderCell>値</TableHeaderCell><TableHeaderCell>状態</TableHeaderCell></TableRow></TableHeader><TableBody>{rows.map(r => <TableRow key={r.id}><TableCell>{r.device || '名前なし'}</TableCell><TableCell>{new Date(r.timestamp).toLocaleString('ja-JP')}</TableCell><TableCell>{r.value ?? '—'}</TableCell><TableCell><Badge label={status(r)} /></TableCell></TableRow>)}</TableBody></Table>
    <p>要確認 {rows.filter(r => status(r) === '要確認').length}件・失敗 {rows.filter(r => status(r) === '失敗').length}件・名前なし {rows.filter(r => !r.device).length}件</p>
  </Card></VStack>;
}
