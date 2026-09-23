import { useId, useState, type ButtonHTMLAttributes } from 'react';
import { createPortal } from 'react-dom';
import { NotebookPen, PencilLine } from 'lucide-react';
import { notesApi } from './client';
import { NoteEditor } from './NoteEditor';
import type { Note, NoteGroup, NoteSummary } from './model';
import './notes.css';
function NoteIcon({hint,children,...props}:ButtonHTMLAttributes<HTMLButtonElement>&{hint:string}) {
  const id=useId();
  const [position,setPosition]=useState<{top:number;right:number}>();
  const show=(element:HTMLElement)=>{const rect=element.getBoundingClientRect();setPosition({top:rect.bottom+8,right:Math.max(8,window.innerWidth-rect.right)});};
  return <span className="chart-note-icon-wrap" onMouseEnter={e=>show(e.currentTarget)} onMouseLeave={()=>setPosition(undefined)} onFocus={e=>show(e.currentTarget)} onBlur={()=>setPosition(undefined)}>
    <button {...props} aria-describedby={position?id:undefined}>{children}</button>
    {position&&createPortal(<div id={id} role="tooltip" className="chart-note-tooltip" style={position}>{hint}</div>,document.body)}
  </span>;
}
export function ChartNotes({symbol,timeframe,start,end,capture,disabled}:{symbol:string;timeframe:string;start:string;end:string;capture:()=>string|undefined;disabled:boolean}) {
  const [note,setNote]=useState<Note>(),[groups,setGroups]=useState<NoteGroup[]>([]),[list,setList]=useState<NoteSummary[]>([]);
  const [isNew,setIsNew]=useState(false);
  const [expanded,setExpanded]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const act=async(fn:()=>Promise<void>)=>{setBusy(true);setError('');try{await fn();}catch(e){setError(e instanceof Error?e.message:'笔记加载失败');}finally{setBusy(false);}};
  return <div className="chart-notes"><NoteIcon type="button" className="chart-note-icon" aria-label="标注并记笔记" hint="在当前K线图上添加标注，自动保存到笔记" disabled={disabled||busy} onClick={()=>void act(async()=>{
    const image=capture();if(!image)throw new Error('图表尚未加载完成');
    const g=await notesApi.groups();setGroups(g);
    setIsNew(true);
    setNote(await notesApi.create({title:`${symbol} · ${timeframe} 分析`,symbol,chart:{image,timeframe,start,end,captured_at:new Date().toLocaleString('zh-CN')},body:'',annotations:[]}));
  })}><PencilLine size={17} aria-hidden="true" /></NoteIcon><NoteIcon type="button" className="chart-note-icon" aria-label="该股票的图表笔记" hint="查看和编辑这只股票已保存的图表笔记" aria-expanded={expanded} disabled={busy} onClick={()=>void act(async()=>{setList(await notesApi.list(symbol));setExpanded(!expanded);})}><NotebookPen size={17} aria-hidden="true" /></NoteIcon>
    {expanded&&<><select aria-label="打开该股票笔记" defaultValue="" onChange={e=>{const id=e.target.value;if(id)void act(async()=>{setGroups(await notesApi.groups());setIsNew(false);setNote(await notesApi.get(id));});}}><option value="">选择已有笔记继续编辑</option>{list.map(n=><option value={n.id} key={n.id}>{n.title}</option>)}</select>{!list.length&&<span>暂无笔记</span>}</>}
    {error&&<span role="alert">{error}</span>}
    {note&&createPortal(<div className="note-modal" role="dialog" aria-modal="true" aria-label="图表笔记"><NoteEditor key={note.id} initial={note} isNew={isNew} groups={groups} onClose={()=>{setNote(undefined);setExpanded(false);}}/></div>, document.body)}
  </div>;
}
