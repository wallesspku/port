import os
import time
import logging

logger = logging.getLogger('walless')


def guess_executable(name):
    for trial in [
        os.path.join(os.environ.get('HOME'), name),
        f'/usr/bin/{name}',
        f'/usr/local/bin/{name}',
        f'/usr/sbin/{name}',
        f'/sbin/{name}',
    ]:
        if os.path.exists(trial):
            return trial
    return ''


haproxy_executable = guess_executable('haproxy')


def restart():
    logger.error('Reboot in 60s.')
    time.sleep(60)
    os.system('rebot')


def report_active_user(n_active_user: int):
    active_user_path = os.path.join(os.environ.get('WALLESS_ROOT', os.environ.get('HOME')), '.active_user')
    with open(active_user_path, 'w') as fp:
        fp.write('{} {}'.format(int(time.time()), n_active_user))


def report_error():
    logger.error('Error occurred. Dumping `active_user` with error code -1.')
    report_active_user(-1)
