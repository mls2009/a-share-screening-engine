import { useRef, useState, type PointerEvent } from 'react';
import { MousePointer2, Type, MoveUpRight, Square, Minus, Undo2, Redo2, Trash2 } from 'lucide-react';
import type { Annotation } from './model';

// Unlike randomUUID, getRandomValues is available on HTTP LAN/Tailscale origins.
function annotationId():string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), byte=>byte.toString(16).padStart(2,'0')).join('');
}

type Point={x:number;y:number};
type Gesture={action:'draw'|'move'|'start'|'end';origin:Point;item:Annotation;before:Annotation[]};
export function AnnotationCanvas({image,annotations,onChange}:{image:string;annotations:Annotation[];onChange:(items:Annotation[])=>void}) {
  const [tool,setTool]=useState<Annotation['kind']|'select'>('select');
  const [selected,setSelected]=useState<string>();
  const [color,setColor]=useState('#f3c969');
  const [fontSize,setFontSize]=useState(16),[lineWidth,setLineWidth]=useState(2);
  const [preview,setPreview]=useState<Annotation[]>();
  const [editing,setEditing]=useState<string>();
  const [editText,setEditText]=useState('');
  const gesture=useRef<Gesture|null>(null);
  const lastTap=useRef<{id:string;time:number}|null>(null);
  const latestPreview=useRef<Annotation[]|undefined>(undefined);
  const svg=useRef<SVGSVGElement>(null);
  const undo=useRef<Annotation[][]>([]),redo=useRef<Annotation[][]>([]);
  const [,renderHistory]=useState(0);
  const items=preview??annotations;
  const active=items.find(a=>a.id===selected);
  const commit=(next:Annotation[])=>{if(JSON.stringify(next)===JSON.stringify(annotations))return;undo.current.push(annotations);redo.current=[];onChange(next);};
  const patch=(id:string,values:Partial<Annotation>)=>commit(annotations.map(a=>a.id===id?{...a,...values}:a));
  const history=(back:boolean)=>{const source=back?undo.current:redo.current,target=back?redo.current:undo.current;const next=source.pop();if(next){target.push(annotations);onChange(next);setSelected(undefined);renderHistory(x=>x+1);}};
  const point=(event:PointerEvent):Point=>{const rect=svg.current!.getBoundingClientRect();return{x:Math.max(0,Math.min(1000,(event.clientX-rect.left)/rect.width*1000)),y:Math.max(0,Math.min(600,(event.clientY-rect.top)/rect.height*600))};};
  const start=(event:PointerEvent<SVGSVGElement>)=>{
    if(event.button!==0||editing)return;
    event.preventDefault();
    svg.current?.focus({preventScroll:true});
    const target=event.target as Element;
    const id=target.closest('[data-annotation-id]')?.getAttribute('data-annotation-id');
    const hit=annotations.find(a=>a.id===id);
    const origin=point(event);
    if(hit&&tool==='select') {
      setSelected(hit.id);
      const handle=target.getAttribute('data-handle');
      gesture.current={action:handle==='start'||handle==='end'?handle:'move',origin,item:hit,before:annotations};
    } else if(tool==='select'){setSelected(undefined);return;}
    else {
      const item:Annotation={id:annotationId(),kind:tool,...origin,x2:origin.x,y2:origin.y,text:tool==='text'?'输入文字':'',color,fontSize,lineWidth};
      if(tool==='text'){
        commit([...annotations,item]);setSelected(item.id);setTool('select');
        setEditing(item.id);setEditText('');
        return;
      }
      gesture.current={action:'draw',origin,item,before:annotations};
    }
    svg.current!.setPointerCapture(event.pointerId);
    event.preventDefault();
  };
  const move=(event:PointerEvent<SVGSVGElement>)=>{
    const g=gesture.current;if(!g)return;
    const p=point(event);let a={...g.item};
    if(g.action==='draw'||g.action==='end'){a.x2=p.x;a.y2=p.y;}
    else if(g.action==='start'){a.x=p.x;a.y=p.y;}
    else {
      const dx=Math.max(-Math.min(a.x,a.x2??a.x),Math.min(1000-Math.max(a.x,a.x2??a.x),p.x-g.origin.x));
      const dy=Math.max(-Math.min(a.y,a.y2??a.y),Math.min(600-Math.max(a.y,a.y2??a.y),p.y-g.origin.y));
      a={...a,x:a.x+dx,y:a.y+dy,x2:(a.x2??a.x)+dx,y2:(a.y2??a.y)+dy};
    }
    const next=g.action==='draw'?[...g.before,a]:g.before.map(item=>item.id===a.id?a:item);
    latestPreview.current=next;setPreview(next);
  };
  const finish=(event:PointerEvent<SVGSVGElement>)=>{
    const g=gesture.current;if(!g)return;
    const next=latestPreview.current;
    if(next){const a=next.find(item=>item.id===g.item.id)!;if(g.action!=='draw'||Math.hypot((a.x2??a.x)-a.x,(a.y2??a.y)-a.y)>3)commit(next);}
    const end=point(event);
    if(g.action==='move'&&Math.hypot(end.x-g.origin.x,end.y-g.origin.y)<3) {
      const time=performance.now();
      if(lastTap.current?.id===g.item.id&&time-lastTap.current.time<450) {setEditing(g.item.id);setEditText(g.item.text);lastTap.current=null;}
      else lastTap.current={id:g.item.id,time};
    } else lastTap.current=null;
    setSelected(g.item.id);setTool('select');gesture.current=null;latestPreview.current=undefined;setPreview(undefined);
    if(svg.current?.hasPointerCapture(event.pointerId))svg.current.releasePointerCapture(event.pointerId);
  };
  const finishText=()=>{if(editing){patch(editing,{text:editText});setEditing(undefined);}};
  const controls=[['select','选择移动',MousePointer2],['text','文字',Type],['arrow','箭头',MoveUpRight],['box','框选',Square],['line','画线',Minus]] as const;
  return <div className="annotation-workspace">
    <div className="note-actions annotation-tools" role="toolbar" aria-label="图表标注工具">
      {controls.map(([kind,name,Icon])=><button key={kind} title={name} aria-label={name} aria-pressed={tool===kind} className={tool===kind?'active':''} onClick={()=>{setTool(kind);setSelected(undefined);}}><Icon size={18}/></button>)}
      <label>字号<input aria-label="文字大小" type="number" min={10} max={64} value={active?.fontSize??fontSize} onChange={e=>{const value=Number(e.target.value);if(value>=10&&value<=64){setFontSize(value);if(active)patch(active.id,{fontSize:value});}}}/></label>
      <label>线宽<input aria-label="线条粗细" type="number" min={1} max={10} value={active?.lineWidth??lineWidth} onChange={e=>{const value=Number(e.target.value);if(value>=1&&value<=10){setLineWidth(value);if(active)patch(active.id,{lineWidth:value});}}}/></label>
      <input type="color" aria-label="标注颜色" value={active?.color??color} onChange={e=>{setColor(e.target.value);if(active)patch(active.id,{color:e.target.value});}}/>
      <button title="撤销" aria-label="撤销" disabled={!undo.current.length} onClick={()=>history(true)}><Undo2 size={18}/></button><button title="重做" aria-label="重做" disabled={!redo.current.length} onClick={()=>history(false)}><Redo2 size={18}/></button>
      <button title="删除选中标注" aria-label="删除选中标注" disabled={!active} onClick={()=>{commit(annotations.filter(a=>a.id!==selected));setSelected(undefined);}}><Trash2 size={18}/></button>
    </div>
    <p className="note-hint">选择文字工具后点击图上输入；选择工具可直接拖动文字或图形；拖动端点调整箭头、线条和框的大小。文字双击编辑，字号、线宽和颜色对当前选中项生效。画箭头、线条或框时按住鼠标拖动，松开完成。</p>
    <div className="note-canvas"><img src={image} alt="笔记中的K线快照" draggable={false}/><svg ref={svg} aria-label="K线笔记标注画布" viewBox="0 0 1000 600" preserveAspectRatio="none" tabIndex={0} onKeyDown={e=>{
      if(e.key==='Delete'||e.key==='Backspace'){e.preventDefault();if(selected){commit(annotations.filter(a=>a.id!==selected));setSelected(undefined);}}
      if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();history(!e.shiftKey);}
      if(e.key==='Escape'){setSelected(undefined);setTool('select');}
    }} style={{cursor:tool==='select'?'default':'crosshair',touchAction:'none'}} onPointerDown={start} onPointerMove={move} onPointerUp={finish} onPointerCancel={()=>{gesture.current=null;latestPreview.current=undefined;setPreview(undefined);}}>
      {items.map(a=><g key={a.id} data-annotation-id={a.id} data-x={a.x} stroke={a.color} strokeWidth={a.lineWidth??2} fill="none" style={{cursor:tool==='select'?'move':undefined}} onDoubleClick={()=>{setSelected(a.id);setEditing(a.id);setEditText(a.text);}}>
        {a.kind==='box'?<rect x={Math.min(a.x,a.x2??a.x)} y={Math.min(a.y,a.y2??a.y)} width={Math.abs((a.x2??a.x)-a.x)} height={Math.abs((a.y2??a.y)-a.y)} fill={a.color} fillOpacity="0.08"/>:a.kind!=='text'?<><line x1={a.x} y1={a.y} x2={a.x2} y2={a.y2} stroke="transparent" strokeWidth="16"/><line x1={a.x} y1={a.y} x2={a.x2} y2={a.y2}/></>:null}
        {a.kind==='arrow'&&<path d="M -12 -6 L 0 0 L -12 6" transform={`translate(${a.x2} ${a.y2}) rotate(${Math.atan2((a.y2??0)-a.y,(a.x2??0)-a.x)*180/Math.PI})`}/>}
        <text x={a.x+4} y={Math.max(a.fontSize??16,a.y-6)} fill={a.color} stroke="none" fontSize={a.fontSize??16} style={{userSelect:'none'}}>{a.text}</text>
        {a.id===selected&&a.kind!=='text'&&<>{(['start','end'] as const).map(handle=><circle key={handle} data-handle={handle} cx={handle==='start'?a.x:a.x2} cy={handle==='start'?a.y:a.y2} r="6" fill="#14271e" stroke="#fff" strokeWidth="1.5" style={{cursor:'crosshair'}}/>)}</>}
        {a.id===selected&&a.kind==='text'&&<line x1={a.x} y1={a.y+2} x2={Math.min(1000,a.x+Math.max(40,a.text.length*(a.fontSize??16)))} y2={a.y+2} strokeDasharray="3 3" strokeWidth="1"/>}
      </g>)}
    </svg>{editing&&active&&<input className="annotation-inline-input" aria-label="编辑图中文字" autoFocus style={{left:`${Math.min(75,active.x/10)}%`,top:`${Math.max(0,active.y/6-5)}%`}} value={editText} onChange={e=>setEditText(e.target.value)} onBlur={finishText} onKeyDown={e=>{if(e.key==='Enter')finishText();if(e.key==='Escape')setEditing(undefined);}}/>}</div>

  </div>;
}
