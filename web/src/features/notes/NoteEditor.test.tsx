import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { NoteEditor } from './NoteEditor';
import { notesApi } from './client';
import type { Note } from './model';
vi.mock('./client',()=>({notesApi:{save:vi.fn(),remove:vi.fn()}}));
it('saves edited text while preserving existing chart annotations',async()=>{
  const note:Note={id:'n1',title:'观察',body:'',symbol:'000012.SZ',group_id:null,chart:{image:'data:image/png;base64,AA==',timeframe:'1d',start:'2026-01-01',end:'2026-09-18',captured_at:'2026-09-18'},annotations:[{id:'a1',kind:'text',x:10,y:20,text:'原标注',color:'#f3c969'}],revision:1,updated_at:''};
  vi.mocked(notesApi.save).mockImplementation(async value=>({...value,revision:value.revision+1}));
  render(<NoteEditor initial={note} groups={[]} onClose={()=>{}} />);
  fireEvent.change(screen.getByLabelText('笔记正文'),{target:{value:'新的判断'}});
  fireEvent.click(screen.getByRole('button',{name:'保存并关闭'}));
  await waitFor(()=>expect(notesApi.save).toHaveBeenCalledWith(expect.objectContaining({id:'n1',body:'新的判断',annotations:[expect.objectContaining({text:'原标注'})]})));
  expect(screen.getByAltText('笔记中的K线快照')).toBeInTheDocument();
});

it('serializes saves and keeps edits made while a save is in flight',async()=>{
  const note:Note={id:'n2',title:'观察',body:'',symbol:null,group_id:null,chart:null,annotations:[],revision:1,updated_at:''};
  let resolveFirst!:(value:Note)=>void;
  vi.mocked(notesApi.save).mockReset().mockImplementationOnce(()=>new Promise(resolve=>{resolveFirst=resolve;})).mockImplementation(async value=>({...value,revision:value.revision+1}));
  render(<NoteEditor initial={note} groups={[]} onClose={()=>{}}/>);
  fireEvent.change(screen.getByLabelText('笔记正文'),{target:{value:'第一版'}});
  fireEvent.click(screen.getByRole('button',{name:'保存并关闭'}));
  fireEvent.change(screen.getByLabelText('笔记正文'),{target:{value:'保存时继续输入'}});
  resolveFirst({...note,body:'第一版',revision:2});
  await waitFor(()=>expect(notesApi.save).toHaveBeenLastCalledWith(expect.objectContaining({body:'保存时继续输入',revision:2})));
  await waitFor(()=>expect(screen.getByRole('status')).toHaveTextContent('已保存'));
});

it('keeps editor open on a failed save so the user can retry',async()=>{
  const close=vi.fn();
  vi.mocked(notesApi.save).mockRejectedValueOnce(new Error('网络中断'));
  render(<NoteEditor initial={{id:'n3',title:'观察',body:'',symbol:null,group_id:null,chart:null,annotations:[],revision:1,updated_at:''}} groups={[]} onClose={close}/>);
  fireEvent.change(screen.getByLabelText('笔记正文'),{target:{value:'不能丢失'}});
  fireEvent.click(screen.getByRole('button',{name:'保存并关闭'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('网络中断');
  expect(close).not.toHaveBeenCalled();
  expect(screen.getByLabelText('笔记正文')).toHaveValue('不能丢失');
});

it('direct close cancels queued edits without saving them',async()=>{
  vi.mocked(notesApi.save).mockClear();
  const close=vi.fn();
  render(<NoteEditor initial={{id:'discard',title:'原笔记',body:'原文',symbol:null,group_id:null,chart:null,annotations:[],revision:1,updated_at:''}} groups={[]} onClose={close}/>);
  fireEvent.change(screen.getByLabelText('笔记正文'),{target:{value:'不要保存'}});
  fireEvent.click(screen.getByRole('button',{name:'直接关闭'}));
  await waitFor(()=>expect(close).toHaveBeenCalled());
  expect(notesApi.save).not.toHaveBeenCalled();
});

it('direct close waits for autosave then restores the opening snapshot',async()=>{
  const note:Note={id:'rollback',title:'原笔记',body:'原文',symbol:null,group_id:null,chart:null,annotations:[],revision:1,updated_at:''};
  let resolveSave!:(value:Note)=>void;
  vi.mocked(notesApi.save).mockReset().mockImplementationOnce(()=>new Promise(resolve=>{resolveSave=resolve;})).mockImplementation(async value=>({...value,revision:value.revision+1}));
  const close=vi.fn();
  const view=render(<NoteEditor initial={note} groups={[]} onClose={close}/>);
  fireEvent.change(screen.getByLabelText('笔记正文'),{target:{value:'自动保存的修改'}});
  await waitFor(()=>expect(notesApi.save).toHaveBeenCalledTimes(1));
  fireEvent.change(screen.getByLabelText('笔记标题'),{target:{value:'待保存标题'}});
  fireEvent.click(screen.getByRole('button',{name:'直接关闭'}));
  expect(close).not.toHaveBeenCalled();
  resolveSave({...note,body:'自动保存的修改',revision:2});
  await waitFor(()=>expect(close).toHaveBeenCalledTimes(1));
  expect(notesApi.save).toHaveBeenLastCalledWith({...note,revision:2});
  view.unmount();
  expect(notesApi.save).toHaveBeenCalledTimes(2);
});

it('direct close removes a newly created note',async()=>{
  vi.mocked(notesApi.save).mockClear();
  vi.mocked(notesApi.remove).mockReset().mockResolvedValue(undefined);
  const close=vi.fn();
  const view=render(<NoteEditor isNew initial={{id:'new-note',title:'新笔记',body:'',symbol:null,group_id:null,chart:null,annotations:[],revision:1,updated_at:''}} groups={[]} onClose={close}/>);
  fireEvent.change(screen.getByLabelText('笔记正文'),{target:{value:'不要保留'}});
  fireEvent.click(screen.getByRole('button',{name:'直接关闭'}));
  await waitFor(()=>expect(close).toHaveBeenCalled());
  expect(notesApi.remove).toHaveBeenCalledWith('new-note');
  view.unmount();
  expect(notesApi.save).not.toHaveBeenCalled();
});
