export function FailureButton({symbol, failed, disabled, onClick}: {symbol:string;failed:boolean;disabled:boolean;onClick:()=>void}) {
  return <button type="button" className={`failure-review ${failed ? 'is-failed' : ''}`} aria-label={`${failed ? '撤销失败' : '标记失败'} ${symbol}`} aria-pressed={failed} disabled={disabled} title={failed ? '此股票在相同筛选条件下已标记失败，点击撤销' : '标记失败；相同条件再次筛选时保留，不影响不同条件'} onClick={event=>{event.stopPropagation();onClick();}}>{failed ? '✕ 已失败 · 撤销' : '标记失败'}</button>;
}
