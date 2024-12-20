from typing import *
import random
import os
from datetime import datetime, timedelta
import time
from copy import deepcopy
import logging

import pytz
from walless_utils import Node,  db, user_pool, node_pool
from walless_utils.network_status import NetworkStatus
from walless_utils import EditReservior

from .utils import report_active_user, restart, report_error
from .account import Account
from .cron import CronJob, CronManager

logger = logging.getLogger('walless')


class PortBase:
    def __init__(self, node_obj: Node, network_status: NetworkStatus = None):
        self.root = os.environ.get('WALLESS_ROOT', os.environ.get('HOME'))
        self.network_status = network_status if network_status is None else NetworkStatus()
        self.node_obj = node_obj
        self.id2user: Dict[int, Account] = dict()
        self.n_active = 0

        self.cron_mgr = CronManager()

    @property
    def n_user(self):
        return len(self.id2user)

    def fetch_user_config(self):
        fetched_users = user_pool.all_users()
        if self.node_obj.weight > 1e-3:
            # We do not check balance for free node.
            fetched_users = list(filter(lambda x: x.balance > 1024, fetched_users))
        fetched_users = list(filter(lambda x: self.node_obj.can_be_used_by(x.tag), fetched_users))

        n_new = n_alter = n_del = 0
        new_users, del_users = list(), list()
        missing_user_ids = set(self.id2user.keys())
        for u in fetched_users:
            missing_user_ids.discard(u.user_id)
            if u.user_id in self.id2user:
                # this user existsed in local record
                if u.uuid == self.id2user[u.user_id].user.uuid:
                    # no change happened to this user
                    pass
                else:
                    logger.warning(f'User {u} config changed.')
                    # delete the old user. copy its uuid
                    del_users.append(deepcopy(self.id2user[u.user_id]))
                    # assign new uuid to local copy of this user
                    self.id2user[u.user_id].user = u
                    new_users.append(self.id2user[u.user_id])
                    n_alter += 1
            else:
                # this is a new user. it might just register, or it is re-enabled
                self.id2user[u.user_id] = Account(u)
                new_users.append(self.id2user[u.user_id])
                n_new += 1

        for uid in missing_user_ids:
            # this user existed in local record but now missing in database
            # it might be disabled, or its balance is empty
            logger.info(f'User {self.id2user[uid].user} is going to be disabled.')
            del_users.append(self.id2user.pop(uid))
            n_del += 1

        if len(new_users) + len(del_users) > 0:
            logger.warning(f'Added {n_new}, altered {n_alter}, and deleted {n_del} users.')

        return new_users, del_users

    def upload_traffic(self):
        to_update = dict()
        n_total = 0
        # user with more than 1MB traffic will be considered as active
        n_active = 0
        active_threshold = 1 * 1024**2
        for u in self.id2user.values():
            u_delta, d_delta = u.diff()
            if u_delta + d_delta == 0:
                continue
            n_total += 1
            if not u.need_report():
                continue
            to_update[u.user.user_id] = (u_delta, d_delta)
            if sum(to_update[u.user.user_id]) > active_threshold:
                n_active += 1
            u.reset()
        report_active_user(n_active)
        self.n_active = n_active
        logger.info('Found {} pieces of updates, {} among which will be uploaded.'.format(n_total, len(to_update)))
        if len(to_update) == 0:
            return
        editor = EditReservior(sql=db.upload_log_sql, db=db, block=True, cache_size=1024)
        now = int(time.time())
        for user_id, (u_delta, d_delta) in to_update.items():
            editor.add((user_id, self.node_obj.uuid, u_delta, d_delta, now))
        editor.flush()

    def sync_db(self):
        loop_since = time.time()

        def action(func, name):
            try:
                since = time.time()
                func()
                logger.info(f'Finished {name}. Time cost: {time.time()-since:.3f}sec.')
            except Exception as e:
                logger.error(f'Error while {name}: {e}')
                raise e

        action(self.sync_users, 'user config fetching')
        action(self.fetch_traffic, 'traffic fetching')
        action(self.upload_traffic, 'traffic uploading')

        logger.warning(f'Loop done in {time.time() - loop_since:.3f}s. {self.n_active}/{self.n_user} active users.')

    def check_node_update(self):
        new_node = db.get_node_by_uuid(self.node_obj.uuid)

        def has_update():
            if new_node is None:
                return False
            for k in ['tag', 'weight', 'properties']:
                if getattr(new_node, k) != getattr(self.node_obj, k):
                    return True
            return False

        if has_update():
            os.system('/usr/bin/rebot')

    def run(self):
        self.cron_mgr.new_job(CronJob('sync_db', self.sync_db, 1, 360, in_error=report_error))

        if 'restart' in self.node_obj.properties:
            now = datetime.fromtimestamp(int(time.time()), pytz.timezone('Asia/Shanghai'))
            now = now.replace(tzinfo=None)
            next4am = datetime(year=now.year, month=now.month, day=now.day, hour=4) + timedelta(days=1)
            restart_gaps = ((next4am - now).seconds + 600 * random.random()) // self.cron_mgr.sleep_time
            self.cron_mgr.new_job(CronJob('restart', restart, restart_gaps, 180, skip_first=True))

        self.cron_mgr.new_job(CronJob('check_node_update', self.check_node_update, 2, 360))

        self.cron_mgr.run()

    def update_traffic(self, identifier, upload=None, download=None):
        self.id2user[identifier].update_traffic(upload, download)

    def fetch_traffic(self):
        raise NotImplementedError

    def sync_users(self):
        raise NotImplementedError
