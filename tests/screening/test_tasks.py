from fastapi import HTTPException
import pytest
from astock.screening.tasks import ScreeningTasks


def test_task_progress_dedup_completion_and_failure():
    tasks=ScreeningTasks()
    job,created=tasks.start({'tree':'same'})
    assert created
    assert tasks.start({'tree':'same'}) == (job,False)
    with pytest.raises(HTTPException):
        tasks.start({'tree':'different'})
    def execute(report):
        report(65,'逐股判断',50,100)
        assert tasks.get(job['job_id'])['processed']==50
        return {'run_id':'saved'}
    tasks.run(job['job_id'],execute)
    assert tasks.get(job['job_id'])['result']=={'run_id':'saved'}
    next_job,_=tasks.start({'tree':'different'})
    def fail(report):
        raise ValueError('测试失败')
    tasks.run(next_job['job_id'],fail)
    assert tasks.get(next_job['job_id'])['status']=='failed'
    assert tasks.get(next_job['job_id'])['error']=='测试失败'
