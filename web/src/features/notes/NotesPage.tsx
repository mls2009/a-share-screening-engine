import { useEffect, useState } from 'react';
import { notesApi } from './client';
import { NoteEditor } from './NoteEditor';
import type { Note, NoteGroup, NoteSummary } from './model';
import './notes.css';
export function NotesPage({onLatest}:{onLatest:(symbol:string)=>void}) {
  const [notes,setNotes]=useState<NoteSummary[]>([]),[groups,setGroups]=useState<NoteGroup[]>([]);
  const [selected,setSelected]=useState<Note>(),[group,setGroup]=useState('all'),[groupName,setGroupName]=useState('');
  const [isNew,setIsNew]=useState(false);
  const [error,setError]=useState(''),[busy,setBusy]=useState(false);
  const load=async()=>{const [n,g]=await Promise.all([notesApi.list(),notesApi.groups()]);setNotes(n);setGroups(g);};
  const act=async(action:()=>Promise<unknown>)=>{setBusy(true);setError('');try{await action();}catch(e){setError(e instanceof Error?e.message:'操作失败');}finally{setBusy(false);}};
  useEffect(()=>{void act(load);},[]);
  return <main className="notes-page"><p className="eyebrow">RESEARCH JOURNAL</p><h1>笔记</h1><p>记录每一次判断，保留当时的图形与标注。</p>{error&&<p role="alert">{error}</p>}
    {selected?<NoteEditor key={selected.id} initial={selected} isNew={isNew} groups={groups} onClose={()=>{setSelected(undefined);void act(load);}} onLatest={onLatest}/>:<>
      <div className="note-actions"><button disabled={busy} onClick={()=>void act(async()=>{setIsNew(true);setSelected(await notesApi.create({title:'新笔记',group_id:group==='all'||group==='none'?null:group}));})}>新建笔记</button><select aria-label="筛选笔记分组" value={group} onChange={e=>setGroup(e.target.value)}><option value="all">全部笔记</option><option value="none">未分组</option>{groups.map(g=><option value={g.id} key={g.id}>{g.name}</option>)}</select></div>
      <details><summary>管理笔记分组</summary><div className="note-actions"><input aria-label="新笔记分组名称" placeholder="分组名称" value={groupName} onChange={e=>setGroupName(e.target.value)}/><button disabled={busy||!groupName.trim()} onClick={()=>void act(async()=>{await notesApi.createGroup(groupName.trim());setGroupName('');await load();})}>创建笔记分组</button></div>{groups.map(g=><div className="note-actions" key={g.id}><input aria-label={`分组名称 ${g.name}`} defaultValue={g.name} onBlur={e=>{if(e.target.value.trim()&&e.target.value.trim()!==g.name)void act(async()=>{await notesApi.renameGroup(g.id,e.target.value.trim());await load();});}}/><button disabled={busy} onClick={()=>void act(async()=>{await notesApi.deleteGroup(g.id);setGroup('all');await load();})}>删除分组（保留笔记）</button></div>)}</details>
      <div className="note-list">{notes.filter(n=>group==='all'||(group==='none'?!n.group_id:n.group_id===group)).map(n=><article className="note-card" key={n.id}><h3>{n.title}</h3><p>{n.symbol??'文字笔记'} · {groups.find(g=>g.id===n.group_id)?.name??'未分组'}</p><p>{n.has_chart?'包含K线快照与标注 · ':''}{n.updated_at.replace('T',' ').slice(0,19)}</p><div className="note-actions"><button disabled={busy} onClick={()=>void act(async()=>{setIsNew(false);setSelected(await notesApi.get(n.id));})}>打开笔记</button><button disabled={busy} onClick={()=>{if(window.confirm(`删除笔记“${n.title}”？`))void act(async()=>{await notesApi.remove(n.id);await load();});}}>删除笔记</button></div></article>)}</div>{!notes.length&&<p className="note-hint">还没有笔记。可以新建文字笔记，或在任意股票的K线研究中点击“标注并记笔记”。</p>}
    </>}
  </main>;
}
