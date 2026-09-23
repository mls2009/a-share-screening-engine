export function shanghaiToday() {
  return new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
}

// Empty value means a moving cutoff, resolved when a request is made.
export function DataDateInput({label,value,onChange}:{label:string;value:string;onChange:(value:string)=>void}) {
  return <div className="data-date-input"><span>{label}</span><select aria-label={`${label}模式`} value={value?'history':'latest'} onChange={e=>onChange(e.target.value==='latest'?'':shanghaiToday())}>
    <option value="latest">最新</option><option value="history">指定日期</option>
  </select>{value&&<input aria-label={label} type="date" max={shanghaiToday()} value={value} onChange={e=>onChange(e.target.value)}/>}</div>;
}
