import time
import logging
import os
from argparse import ArgumentParser
import traceback

from walless_utils import setup_everything, logger_setup, whoami
from port.haproxy import HAProxy
from walless_utils.network_status import NetworkStatus

logger = logging.getLogger('walless')


def run():
    parser = ArgumentParser()
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()
    logger_setup(log_paths=[os.path.expanduser('~/.var/log/walless_port.log')])
    if args.debug:
        logger.setLevel('DEBUG')

    logger.warning('Server started. Pulling everything.')
    since = time.time()
    setup_everything(pull_node=True, pull_user=True)
    logger.warning('Pulling finished. Time cost: %.2fs.', time.time() - since)

    ns = NetworkStatus()
    ns.wait_for_network()

    while True:
        try:
            me = whoami(ns=ns, debug=args.debug)
            if me is None:
                sleep_time = 60
                logger.warning(f'Node not found in db. Will try again in {sleep_time} sec.')
                time.sleep(sleep_time)
                continue
            logger.warning(f'I am {me.name} with IP {me.ip(4)}. My tags are: {me.tag}.')
            job = HAProxy(me, network_status=ns)
            job.run()
        except KeyboardInterrupt:
            logger.warning('KeyboardInterrupt. Exiting.')
            return
        except Exception as e:
            logger.error(f'Error: {e}')
            logger.error(traceback.format_exc())
            logger.error('Try to restart in 10 sec.')
            time.sleep(10)


if __name__ == '__main__':
    run()
