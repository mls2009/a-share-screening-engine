import type { Note, NoteGroup, NoteSummary } from './model';
async function request<T>(path:string, method='GET', body?:unknown):Promise<T> {
  const response=await fetch(`/api/notes${path}`,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  if(!response.ok) { const error=await response.json().catch(()=>null); throw new Error(typeof error?.detail==='string'?error.detail:`笔记保存失败（${response.status}）`); }
  return response.status===204?undefined as T:response.json();
}
export const notesApi={
  list:(symbol?:string)=>request<NoteSummary[]>(symbol?`?symbol=${encodeURIComponent(symbol)}`:''),
  get:(id:string)=>request<Note>(`/${id}`),
  create:(value:Partial<Note>)=>request<Note>('','POST',value),
  save:(note:Note)=>request<Note>(`/${note.id}`,'PUT',note),
  remove:(id:string)=>request<void>(`/${id}`,'DELETE'),
  groups:()=>request<NoteGroup[]>('/groups'),
  createGroup:(name:string)=>request<NoteGroup>('/groups','POST',{name}),
  renameGroup:(id:string,name:string)=>request<NoteGroup>(`/groups/${id}`,'PUT',{name}),
  deleteGroup:(id:string)=>request<void>(`/groups/${id}`,'DELETE'),
};
