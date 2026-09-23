"""Compare to the latest completed run with the same definition and scope."""
import json
from pydantic import TypeAdapter
from astock.screening.models import Node


def _tree(raw):
    value=TypeAdapter(Node).validate_python(json.loads(raw)).model_dump(mode='json')
    def canonical(node):
        if isinstance(node,dict):
            node={k:canonical(v) for k,v in node.items()}
            if node.get('logic') in ('and','or'):
                node['children']=sorted(node['children'],key=lambda v:json.dumps(v,sort_keys=True))
        elif isinstance(node,list):
            node=[canonical(v) for v in node]
        return node
    return canonical(value)


def _scope(raw):
    scope=(json.loads(raw) if raw else {}).get('scope',{})
    defaults={'scope':'market','instrument_type':'all','boards':[],'source_run_id':None,'watch_group_id':None,'watch_ungrouped':False}
    defaults.update(scope)
    defaults['boards']=sorted(defaults.get('boards') or [])
    return defaults


def previous_run_comparison(con,run_id):
    row=con.execute('select condition_tree,mode,diagnostics,created_at from screen_runs where run_id=?',[run_id]).fetchone()
    if not row:return None
    definition,mode,scope,created=row
    definition=_tree(definition);scope=_scope(scope)
    candidates=con.execute("select run_id,condition_tree,diagnostics,as_of_date,finished_at from screen_runs where mode=? and status='completed' and finished_at<=? and run_id<>? order by finished_at desc,created_at desc,run_id desc",[mode,created,run_id]).fetchall()
    for identifier,tree,diagnostics,as_of,finished in candidates:
        if _tree(tree)!=definition or _scope(diagnostics)!=scope:continue
        entered=[r[0] for r in con.execute('select symbol from screen_matches where run_id=? except select symbol from screen_matches where run_id=? order by symbol',[run_id,identifier]).fetchall()]
        return dict(run_id=str(identifier),as_of=str(as_of),finished_at=finished.isoformat(),entered=entered,count=len(entered))
    return None
