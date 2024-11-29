from typing import *
import os
from dataclasses import dataclass, field
import time
import traceback
from threading import Thread

from .utils import logger, restart


@dataclass()
class CronJob:
    """
    State:
    1. Init: _job_thread is None
    2. During execution: _job_thread is alive
    2a. Execution timeout: time.time() - _last_start > timeout
    3. After execution and before check: _job_thread is not alive and _checked is None
    3a. Execution failed with exception: _no_exception is False
    3b. Execution success: _no_exception is True
    """
    name: str
    func_to_call: Callable
    execute_gap: int  # in times
    timeout: int  # in second
    args: List[Any] = field(default_factory=list)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    skip_first: bool = False
    in_error: Callable = None
    exit_when_timeout: bool = True
    _job_thread: Optional[Thread] = None
    _last_start: Optional[float] = None
    _running_time: Optional[float] = None
    _no_exception: bool = False
    _is_checked: bool = False

    def job_wrapper(self):
        self._no_exception = self._is_checked = False
        self._last_start = time.time()
        self.func_to_call(*self.args, **self.kwargs)
        self._no_exception = True
        self._running_time = time.time() - self._last_start

    def _execute(self):
        self._job_thread = Thread(target=self.job_wrapper, daemon=True)
        self._job_thread.start()

    def check(self):
        if self._job_thread is None:
            return
        if self._job_thread.is_alive():
            if time.time() - self._last_start > self.timeout:
                if self.exit_when_timeout:
                    restart()
                else:
                    logger.warning(f'{self.name} timeout!')
        elif not self._is_checked:
            # after execution and before check
            self._is_checked = True
            if not self._no_exception and self.in_error is not None:
                self.in_error()

    def run(self):
        if self._job_thread is None:
            self._execute()
        elif self._job_thread.is_alive():
            logger.debug(f'Job is running. Skip execution of {self.name}.')
        else:
            self._execute()


class CronManager:
    def __init__(self):
        self.jobs: Dict[str, CronJob] = dict()
        self.minute_counter: int = 0
        self.sleep_time = 60

    def loop_jobs(self):
        for name, job in self.jobs.items():
            job.check()
            if self.minute_counter == 0 and job.skip_first:
                continue
            if self.minute_counter % job.execute_gap != 0:
                continue
            logger.debug(f'Running {name}.')
            job.run()

    def new_job(self, job: CronJob):
        self.jobs[job.name] = job

    def run(self):
        start_time = time.time()
        try:
            while True:
                self.loop_jobs()
                self.minute_counter += 1
                time.sleep(max(self.sleep_time * self.minute_counter + start_time - time.time(), 1))
        except Exception as e:
            logger.error(f'Error! Loop stopped. {e}')
            logger.error(traceback.format_exc())
