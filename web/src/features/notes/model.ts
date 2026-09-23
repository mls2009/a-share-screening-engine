export type Annotation = {id:string; kind:'text'|'line'|'arrow'|'box'; x:number; y:number; x2?:number; y2?:number; text:string; color:string; fontSize?:number; lineWidth?:number};
export type ChartSnapshot = {image:string; timeframe:string; captured_at:string; start:string; end:string};
export type Note = {id:string; title:string; body:string; group_id:string|null; symbol:string|null; chart:ChartSnapshot|null; annotations:Annotation[]; revision:number; updated_at:string};
export type NoteSummary = Pick<Note,'id'|'title'|'group_id'|'symbol'|'revision'|'updated_at'> & {has_chart:boolean};
export type NoteGroup = {id:string;name:string};
