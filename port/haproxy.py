import os
import socket
import re
import base64
import hashlib
from subprocess import check_output
import subprocess

from walless_utils import User

from .port_base import PortBase, Account
from .utils import haproxy_executable, logger


class HAProxy(PortBase):
    def __init__(self, node_obj, network_status):
        super().__init__(node_obj, network_status)
        with open('/tmp/usermap', 'w') as fp:
            fp.write('/9192631770 198964')

        self.dump_haproxy_cfg()
        env = None
        # force IvyBridge-v2 CPU feature
        if 'aes' not in check_output('lscpu').decode():
            env = {'OPENSSL_ia32cap': '0xffb82203078bffff'}
        subprocess.Popen([haproxy_executable, '-f', './haproxy_config'], env=env)
        logger.warning('Listening for incoming http connection.')

    def dump_haproxy_cfg(self):
        # if the node has IPv6, then do not include `,ipv4`
        ha_cfg = haproxy_cfg
        self.network_status.wait_for_checkups()
        self.network_status.ipv6 is not None and os.system('ip -6 route add default dev wgcf metric 99999')
        ha_cfg = ha_cfg.replace('$IP$', ',ipv4' if self.network_status.ipv6 is None else '')
        for relay in self.node_obj.relay_out:
            logger.warning(f'Add {relay}')
            port_start, port_end = relay.port_range()
            if relay.tunnel is None or len(relay.tunnel) == 0:
                relay_tunnel = f'{relay.target.real_urls(4)}:4430'
            else:
                relay_tunnel = relay.tunnel
            relay_cfg = f'''\
listen relay{relay.relay_id}
    mode tcp
    bind *:{port_start}-{port_end-1}
    bind :::{port_start}-{port_end-1}
    server relay{relay.relay_id}backend {relay_tunnel}
            '''
            ha_cfg += '\n' + relay_cfg + '\n'
        if 'gre' in self.node_obj.properties:
            ha_cfg = ha_cfg[:ha_cfg.index('listen proxy')] + gre_suffix
        ha_cfg = ha_cfg.replace('WALLESS_ROOT', self.root)
        with open('haproxy_config/haproxy.cfg', 'w') as fp:
            fp.write(ha_cfg)

    @staticmethod
    def talk(msg, need_return):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect('/tmp/haproxy.sock')
        s.send(msg.encode() if msg.endswith('\n') else (msg + '\n').encode())
        if need_return:
            ret = list()
            while True:
                piece = s.recv(1024000)
                if not piece:
                    break
                ret.append(piece)
            s.close()
            ret = b''.join(ret)
            return ret.decode()
        else:
            s.close()

    @staticmethod
    def sha1_map(user: User):
        return hashlib.sha1(b'Basic ' + base64.b64encode(f'walless:{user.uuid}'.encode())).hexdigest().upper()

    def del_user(self, user: Account):
        try:
            self.talk(f'del map /tmp/usermap {self.sha1_map(user.user)}\n', False)
        except Exception as e:
            logger.error(f'Exception while removing user {user.user}. {e}')

    def add_user(self, user: Account):
        try:
            self.talk(f'add map /tmp/usermap {self.sha1_map(user.user)} {user.user.user_id}\n', False)
        except Exception as e:
            logger.error(f'Exception while adding user {user.user}. {e}')

    def fetch_traffic(self):
        pat = re.compile(r'key=(\d*) use.*?cnt=(\d*)')
        for direction in ['in', 'out']:
            table = self.talk('show table st_{}\n'.format(direction), True)
            for uid, size in pat.findall(table):
                uid, size = int(uid), int(size)
                if uid in [0, 198964]:
                    continue
                if uid not in self.id2user:
                    logger.error(f'User {self.id2user[uid].user} not found!')
                    continue
                acc = self.id2user[uid]
                if direction == 'in':
                    changed = acc.update_traffic(upload=size)
                else:
                    changed = acc.update_traffic(download=size)
                if changed and acc.deleted:
                    logger.warning(f'{acc.user} disabled but had activities. Try to delete it.')
                    self.del_user(acc)
                    acc.disable()

    def sync_users(self):
        new_users, var_users, del_users = self.fetch_user_config()

        # If alert file exists, delete all users
        if os.path.exists('/tmp/stop_walless'):
            logger.warning('Disable all users because stop_walless exists.')
            new_users = var_users = []
            del_users = [u for u in self.id2user.values() if not u.deleted]

        for u in var_users + del_users:
            self.del_user(u)
        for u in var_users + new_users:
            self.add_user(u)
        if len(var_users + new_users + del_users) > 0 :
            self.fetch_traffic()

        # set the deleted flag and reset the traffic
        for u in var_users + new_users:
            u.enable()
        for u in del_users:
            u.disable()


haproxy_cfg = '''
global
    maxconn 65535
    lua-load haproxy_config/h2p.lua
    stats timeout 1m
    stats socket /tmp/haproxy.sock mode 600 level admin
    ssl-default-bind-ciphersuites TLS_AES_128_GCM_SHA256

defaults
    mode tcp
    maxconn 65535
    timeout connect 5s
    timeout client 20s
    timeout server 20s
    timeout tunnel 15m
    option splice-auto

resolvers mydns
    nameserver cloudflare 1.1.1.1:53
    nameserver google 8.8.8.8:53
    timeout retry 2s
    hold valid 10s

backend st_in
    stick-table type integer size 1m nopurge store bytes_in_cnt

backend st_out
    stick-table type integer size 1m nopurge store bytes_out_cnt

backend st_rate
    stick-table type integer size 1m nopurge store gpc0,http_req_rate(1s)

backend h2pproxy
    mode http
    server h2pproxy /tmp/proxy.sock

listen proxy
    mode tcp
    bind /tmp/proxy.sock

    acl localhost var(txn.host) -m ip -f haproxy_config/private.txt
    acl valid_ip var(txn.host) -m ip 0.0.0.0/0
    tcp-request inspect-delay 1s
    tcp-request content lua.hproxy
    tcp-request content set-var(txn.domain) var(txn.host)
    tcp-request content do-resolve(txn.host,mydns$IP$) var(txn.host) if !valid_ip
    tcp-request content set-dst var(txn.host)
    tcp-request content set-dst-port var(txn.port)
    tcp-request content reject unless !localhost
    server clear 0.0.0.0:0
    server wgcf 0.0.0.0:0 weight 0 source 0.0.0.0 interface wgcf
    use-server wgcf if { var(txn.domain) -m sub -f haproxy_config/wgcf_domains.txt }

frontend main_proxy
    mode http
    bind *:4400-4499 ssl crt WALLESS_ROOT/ca/pem alpn h2,http/1.1
    bind :::4400-4499 ssl crt WALLESS_ROOT/ca/pem alpn h2,http/1.1

    # map user id (stored as the authorization) to id based on the user table (/tmp/usermap, maintained in memory)
    http-request set-var(req.userid) hdr(Proxy-Authorization),sha1,hex,map_str_int(/tmp/usermap,0)

    # save user traffic to track-sc table (in and out)
    http-request track-sc0 var(req.userid) table st_in
    http-request track-sc1 var(req.userid) table st_out
    http-request track-sc2 var(req.userid) table st_rate
    
    # ===== copied from haproxy Configuration Manual =====
    # block if 5 consecutive requests continue to come faster than 10 sess
    # per second, and reset the counter as soon as the traffic slows down.
    acl abuse sc2_http_req_rate(st_rate) gt 10
    acl kill  sc2_inc_gpc0(st_rate) gt 5
    acl save  sc2_clr_gpc0(st_rate) ge 0

    # for illegal user, return 403 instead of 407 to fool them
    http-request return status 403 unless { var(req.userid) -m found -m int gt 0 }
    http-request allow if !abuse save
    # tie up bots so that they cannot immediately retry their requests
    timeout tarpit 10s
    http-request tarpit deny_status 429 if abuse kill
    
    # otherwise return haproxy backend
    use_backend h2pproxy 
    
'''

gre_suffix = '''

resolvers edns
    nameserver dnsmasq 127.0.0.1:53
    timeout retry 2s
    hold valid 10s

listen proxy
    mode tcp
    bind /tmp/proxy.sock

    acl localhost var(txn.host) -m ip -f haproxy_config/private.txt
    acl valid_ip var(txn.host) -m ip 0.0.0.0/0
    acl valid_ip_bk var(txn.host_bk) -m ip 0.0.0.0/0
    tcp-request inspect-delay 1s
    tcp-request content lua.hproxy
    tcp-request content set-var(txn.domain) var(txn.host)
    tcp-request content set-var(txn.domain) var(txn.host_bk)
    tcp-request content do-resolve(txn.host,edns) var(txn.host) if !valid_ip
    tcp-request content do-resolve(txn.host,mydns,ipv4) var(txn.host_bk) if valid_ip !valid_ip_bk
    tcp-request content set-dst var(txn.host)
    tcp-request content set-dst-port var(txn.port)
    server clear 0.0.0.0:0 weight 0
    server wgcf 0.0.0.0:0 weight 0 source 0.0.0.0 interface wgcf
    server gre1 0.0.0.0:0 weight 0 source 0.0.0.0 interface gre1
    use-server clear if valid_ip !localhost
    use-server gre1 if !localhost


frontend main_proxy
    mode http
    bind *:4400-4499 ssl crt WALLESS_ROOT/ca/pem alpn h2,http/1.1
    bind :::4400-4499 ssl crt WALLESS_ROOT/ca/pem alpn h2,http/1.1

    # map user id (stored as the authorization) to id based on the user table (/tmp/usermap, maintained in memory)
    http-request set-var(req.userid) hdr(Proxy-Authorization),sha1,hex,map_str_int(/tmp/usermap,0)

    # save user traffic to track-sc table (in and out)
    http-request track-sc0 var(req.userid) table st_in
    http-request track-sc1 var(req.userid) table st_out
    http-request track-sc2 var(req.userid) table st_rate

    # ===== copied from haproxy Configuration Manual =====
    # block if 5 consecutive requests continue to come faster than 10 sess
    # per second, and reset the counter as soon as the traffic slows down.
    acl abuse sc2_http_req_rate(st_rate) gt 10
    acl kill  sc2_inc_gpc0(st_rate) gt 5
    acl save  sc2_clr_gpc0(st_rate) ge 0

    # for illegal user, return 403 instead of 407 to fool them
    http-request return status 403 unless { var(req.userid) -m found -m int gt 0 }
    http-request allow if !abuse save
    #http-request return status 429 if abuse kill
    timeout tarpit 5s
    http-request tarpit deny_status 429 if abuse kill

    # otherwise return haproxy backend
    use_backend h2pproxy

listen proxy2
    mode tcp
    bind /tmp/proxy2.sock
    acl localhost var(txn.host) -m ip 127.0.0.1/8
    acl valid_ip var(txn.host) -m ip 0.0.0.0/0
    tcp-request inspect-delay 1s
    tcp-request content lua.hproxy
    tcp-request content set-var(txn.domain) var(txn.host)
    tcp-request content do-resolve(txn.host,mydns) var(txn.host) if !valid_ip
    tcp-request content set-dst var(txn.host)
    tcp-request content set-dst-port var(txn.port)
    server gre1 0.0.0.0:0 weight 0 source 0.0.0.0 interface gre1
    server clear 0.0.0.0:0 weight 0
    use-server clear if valid_ip !localhost
    use-server gre1 if !localhost

backend h2pproxy_gre
    mode http
    server h2pproxy_gre /tmp/proxy2.sock

frontend main_proxy_gre
    mode http
    bind *:14400-14499 ssl crt WALLESS_ROOT/ca/pem alpn h2,http/1.1
    bind :::14400-14499 ssl crt WALLESS_ROOT/ca/pem alpn h2,http/1.1
    # map user id (stored as the authorization) to id based on the user table (/tmp/usermap, maintained in memory)
    http-request set-var(req.userid) hdr(Proxy-Authorization),sha1,hex,map_str_int(/tmp/usermap,0)

    # save user traffic to track-sc table (in and out)
    http-request track-sc0 var(req.userid) table st_in
    http-request track-sc1 var(req.userid) table st_out
    http-request track-sc2 var(req.userid) table st_rate

    # ===== copied from haproxy Configuration Manual =====
    # block if 5 consecutive requests continue to come faster than 10 sess
    # per second, and reset the counter as soon as the traffic slows down.
    acl abuse sc2_http_req_rate(st_rate) gt 10
    acl kill  sc2_inc_gpc0(st_rate) gt 5
    acl save  sc2_clr_gpc0(st_rate) ge 0

    # for illegal user, return 403 instead of 407 to fool them
    http-request return status 403 unless { var(req.userid) -m found -m int gt 0 }
    http-request allow if !abuse save
    http-request return status 429 if abuse kill

    # otherwise return haproxy backend
    use_backend h2pproxy_gre
'''
