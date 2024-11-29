import os
import time
import logging
from logging import handlers


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


def get_hostname():
    if os.path.exists('/etc/hostname'):
        return open('/etc/hostname').read().strip()
    return None


def get_logger():
    log_format = logging.Formatter('[{asctime}] {message}', style='{')
    _logger = logging.getLogger('port')
    try:
        rfh = handlers.RotatingFileHandler('/tmp/wallesspku.log', maxBytes=(1048576 * 5), backupCount=7,)
        rfh.setFormatter(log_format)
        _logger.addHandler(rfh)
    except:
        pass
    sh = logging.StreamHandler()
    sh.setFormatter(log_format)
    _logger.addHandler(sh)
    return _logger


logger = get_logger()
hostname = get_hostname()
haproxy_executable = guess_executable('haproxy')
active_user = os.path.join(os.environ.get('HOME'), '.active_user')


def restart():
    logger.warning('Reboot in 60s.')
    time.sleep(60)
    os.system('rebot')


def report_error():
    logger.info('Error occurred. Dumping `active_user` with error code -1.')
    open(active_user, 'w').write('{} {}'.format(int(time.time()), -1))
