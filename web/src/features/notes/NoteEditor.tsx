import { useEffect, useRef, useState } from 'react';
import { notesApi } from './client';
import { AnnotationCanvas } from './AnnotationCanvas';
import type { Note, NoteGroup } from './model';
import './notes.css';

export function NoteEditor({initial,groups,onClose,onLatest,isNew=false}:{isNew?:boolean;initial:Note;groups:NoteGroup[];onClose:()=>void;onLatest?:(symbol:string)=>void}) {
  const [note,setNote]=useState(initial);
  const current=useRef(initial), sequence=useRef(0), saved=useRef(0);
  const pending=useRef<Promise<void>|null>(null), timer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined);
  const [status,setStatus]=useState('已保存');
  const [error,setError]=useState('');
  const discarding=useRef(false);
  const [closing,setClosing]=useState(false);
  const persist=():Promise<void>=>{
    clearTimeout(timer.current);
    if(discarding.current) return Promise.resolve();
    if(pending.current) return pending.current;
    const task=async()=>{
      setError('');
      while(!discarding.current && saved.current<sequence.current) {
        const version=sequence.current;
        setStatus('保存中…');
        try {
          const result=await notesApi.save({...current.current,title:current.current.title.trim()||'未命名笔记'});
          current.current={...current.current,revision:result.revision,updated_at:result.updated_at};
          saved.current=version;
        } catch(cause) {setStatus('未保存');setError(cause instanceof Error?cause.message:'保存失败，请重试');throw cause;}
      }
      setStatus('已保存');
    };
    pending.current=task().finally(()=>{pending.current=null;});
    return pending.current;
  };
  const update=(patch:Partial<Note>)=>{
    if(discarding.current)return;
    current.current={...current.current,...patch}; sequence.current+=1;
    setNote(current.current);setStatus('等待保存…');
    clearTimeout(timer.current);timer.current=setTimeout(()=>{void persist().catch(()=>{});},600);
  };
  useEffect(()=>{
    const warn=(event:BeforeUnloadEvent)=>{if(saved.current<sequence.current){event.preventDefault();event.returnValue='';}};
    window.addEventListener('beforeunload',warn);
    return ()=>{window.removeEventListener('beforeunload',warn);clearTimeout(timer.current);void persist().catch(()=>{});};
  },[]);
  const discard=async()=>{
    if(discarding.current)return;
    discarding.current=true;setClosing(true);clearTimeout(timer.current);
    try {
      // Wait for an already-sent autosave before reverting its revision.
      await pending.current?.catch(()=>{});
      if(isNew) await notesApi.remove(initial.id);
      else if(saved.current>0) await notesApi.save({...initial,revision:current.current.revision});
      saved.current=sequence.current;
      onClose();
    } catch(cause) {
      setError(cause instanceof Error?cause.message:'撤销修改失败');
      setStatus('未关闭');setClosing(false);
      // Keep autosave stopped so a failed discard cannot re-save the draft.
      discarding.current=false;
    }
  };
  const close=async()=>{try{await persist();onClose();}catch{/* Keep unsaved editor open. */}};
  return <section className="note-editor" aria-label="笔记编辑器">
    <header><div><p className="eyebrow">RESEARCH NOTES</p><h2>{note.symbol ? `${note.symbol} · 图表笔记`:'研究笔记'}</h2></div><div className="note-actions"><span role="status">{status}</span><button disabled={closing} title="放弃本次修改；新笔记不保留" onClick={()=>void discard()}>直接关闭</button><button disabled={closing} onClick={()=>void close()}>保存并关闭</button></div></header>
    {error&&<p role="alert">{error}。内容仍保留在编辑器中，可重试保存。</p>}
    <div className="note-fields"><label>标题<input aria-label="笔记标题" maxLength={200} value={note.title} onChange={e=>update({title:e.target.value})} onBlur={()=>{if(!current.current.title.trim())update({title:'未命名笔记'});}}/></label><label>分组<select aria-label="笔记分组" value={note.group_id??''} onChange={e=>update({group_id:e.target.value||null})}><option value="">未分组</option>{groups.map(g=><option key={g.id} value={g.id}>{g.name}</option>)}</select></label></div>
    {note.chart&&<>
      <AnnotationCanvas image={note.chart.image} annotations={note.annotations} onChange={annotations=>update({annotations})}/>
      <p className="note-hint">快照时间：{note.chart.captured_at} · {note.chart.timeframe} · 数据窗口 {note.chart.start} 至 {note.chart.end}。快照保留当时的图形，不随行情更新。</p>
    </>}
    <label>研究内容<textarea aria-label="笔记正文" placeholder="记录判断、观察和后续计划…" value={note.body} onChange={e=>update({body:e.target.value})}/></label>
    {note.symbol&&onLatest&&<button onClick={async()=>{try{await persist();onLatest(note.symbol!);}catch{}}}>查看该股票最新行情</button>}
  </section>;
}
