from typing import *
import random
import os
from datetime import datetime, timedelta
import time

import pytz
from walless_utils import Node,  db, user_pool, node_pool
from walless_utils.network_status import NetworkStatus
from walless_utils import EditReservior

from .utils import active_user, logger, restart, report_error
from .account import Account
from .cron import CronJob, CronManager


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
        return sum(not user.deleted for user in self.id2user.values())

    def fetch_user_config(self):
        fetched_users = user_pool.all_users()
        if self.node_obj.weight > 1e-3:
            # We do not check balance for free node.
            fetched_users = list(filter(lambda x: x.balance > 1024, fetched_users))
        fetched_users = list(filter(lambda x: self.node_obj.can_be_used_by(x.tag), fetched_users))

        """
        Here we consider the following situations:
        For users in the `fetched_users`:
        1. User existed locally, enabled and no changes happened to a user -- do nothing.
        2. User existed locally, enabled but changes happened to the user -- add the account obj to var_users.
        3. User existed locally, disabled -- enable the user account and add it to new_users.
        4. User non-existed locally -- create the corresponding Account obj and add it to new_users.
        For users not in the `fetched_users`:
        5. User existed locally and enabled -- Put to the del_users
        6. User existed locally and disabled -- nothing to do
        """
        new_users, var_users, del_users = list(), list(), list()
        id_left = set(self.id2user.keys())
        for u in fetched_users:
            if u.user_id in self.id2user:
                if not self.id2user[u.user_id].deleted:
                    if not (u == self.id2user[u.user_id].user):
                        # case 2
                        logger.info(f'User {u} config changed.')
                        self.id2user[u.user_id].user = u
                        var_users.append(self.id2user[u.user_id])
                    # else case 1
                else:
                    # case 3
                    logger.info(f'User {u} is going to be re-enabled.')
                    new_users.append(self.id2user[u.user_id])
            elif u.user_id not in self.id2user:
                # case 4
                self.id2user[u.user_id] = Account(u)
                new_users.append(self.id2user[u.user_id])
            id_left.discard(u.user_id)
        for uid in id_left:
            if not self.id2user[uid].deleted:
                # case 5
                del_users.append(self.id2user[uid])
                logger.info(f'User {self.id2user[uid].user} is going to be disabled.')
            # else case 6

        if len(new_users) + len(var_users) + len(del_users) > 0:
            logger.warning(f'Added {len(new_users)}, changed {len(var_users)}, deleted {len(del_users)}.')

        return new_users, var_users, del_users

    def upload_traffic(self):
        to_update = dict()
        n_total = 0
        for u in self.id2user.values():
            u_delta, d_delta = u.diff()
            if u_delta + d_delta == 0:
                continue
            n_total += 1
            if not u.need_report():
                continue
            to_update[u.user.user_id] = (u_delta, d_delta)
            u.reset()
        self.n_active = len(to_update)
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
        open(active_user, 'w').write('{} {}'.format(int(time.time()), self.n_active))

    def check_node_update(self):
        new_node = db.get_node_by_uuid(self.node_obj.uuid)

        def has_update():
            if new_node.node_id == -1:
                return True
            for k in ['tag', 'weight', 'properties']:
                if getattr(new_node, k) != getattr(self.node_obj, k):
                    return True
            return False

        if has_update():
            os.system('/usr/bin/rebot')

    def randomly_add_traffic(self):
        # DEBUG ONLY, WARNING!
        print('Warning: randomly add traffic!!')
        import random
        users = list(self.id2user.values())
        users = random.sample(users, len(users) // 100)
        for u in users:
            u.update_traffic(random.randint(0, 10*2**20), random.randint(0, 10*2**20))

    def run(self):
        # self.sync_db()
        # self.randomly_add_traffic()
        # self.sync_db()
        # return

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