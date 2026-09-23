"""One active interactive screening task per service, with bounded progress snapshots."""
from threading import RLock
from uuid import uuid4

from fastapi import HTTPException
from starlette.responses import Response


class ScreeningTasks:
    def __init__(self):
        self.lock = RLock()
        self.jobs = {}

    def start(self, payload):
        with self.lock:
            for job in self.jobs.values():
                if job['status'] == 'running':
                    if job['payload'] == payload:
                        return self.get(job['job_id']), False
                    raise HTTPException(409, '已有条件选股正在运行，请等待完成')
            for key in list(self.jobs)[:-9]:
                del self.jobs[key]
            key = str(uuid4())
            self.jobs[key] = dict(job_id=key, status='running', progress=0,
                                  message='正在准备筛选范围', processed=0, total=0, payload=payload)
            return self.get(key), True

    def get(self, key):
        with self.lock:
            if key not in self.jobs:
                raise HTTPException(404, '筛选任务不存在或服务已重启，请查看历史结果或重新运行')
            return {k:v for k,v in self.jobs[key].items() if k != 'payload'}

    def run(self, key, execute):
        def progress(percent, message, processed=0, total=0):
            with self.lock:
                self.jobs[key].update(progress=max(percent, self.jobs[key]['progress']), message=message, processed=processed, total=total)
        try:
            result = execute(progress)
            if isinstance(result, Response):
                import json
                detail = json.loads(result.body)
                raise ValueError(detail.get('message') or (detail.get('errors') or [{}])[0].get('message') or '筛选失败')
            with self.lock:
                self.jobs[key].update(status='completed', progress=100, message='筛选完成', result=result)
        except Exception as error:
            import logging
            logging.getLogger(__name__).exception('Interactive screening task failed')
            with self.lock:
                self.jobs[key].update(status='failed', message='筛选失败', error=str(error))
