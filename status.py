#!/usr/bin/env python3
import requests
import socket
import time
import timeit
import re
import os
import sys
import json
import subprocess
import threading
import datetime

from walless_utils import cfg, setup_everything, whoami


class StatusClient:
    def __init__(self):
        setup_everything()
        self.me = whoami()
        monitor_cfg = cfg.get('status')
        self.user = self.me.uuid
        self.password = monitor_cfg['password']
        self.server = monitor_cfg['server']

        # Last success; patience
        self.error_count = [time.time(), 2048]
        self.port = monitor_cfg.get('port', 35601)
        self.interval = 1
        self.probeport = 80

        self.edu = cfg.get('edu', 'cernet.191110.xyz')
        self.cu = cfg.get('cu', "111.205.231.10")
        self.ct = cfg.get('ct', "ct.tz.cloudcpp.com")
        self.cm = cfg.get('cm', "bj.10086.cn")

        self.error_state = 0

        self.lostRate = {
            '10010': 0.0,
            '189': 0.0,
            '10086': 0.0,
            'edu': 0.0,
        }
        self.pingTime = {
            '10010': 0,
            '189': 0,
            '10086': 0,
            'edu': 0,
        }
        self.netSpeed = {
            'netrx': 0.0,
            'nettx': 0.0,
            'clock': 0.0,
            'diff': 0.0,
            'avgrx': 0,
            'avgtx': 0
        }

    @staticmethod
    def get_uptime():
        with open('/proc/uptime', 'r') as f:
            uptime = f.readline().split('.', 2)
            return int(uptime[0])

    @staticmethod
    def get_memory():
        re_parser = re.compile(r'^(?P<key>\S*):\s*(?P<value>\d*)\s*kB')
        result = dict()
        with open('/proc/meminfo') as f:
            for line in f:
                match = re_parser.match(line)
                if not match:
                    continue
                key, value = match.groups(['key', 'value'])
                result[key] = int(value)
        MemTotal = float(result['MemTotal'])
        MemUsed = MemTotal-float(result['MemFree'])-float(result['Buffers'])-float(result['Cached'])-float(result['SReclaimable'])
        SwapTotal = float(result['SwapTotal'])
        SwapFree = float(result['SwapFree'])
        return int(MemTotal), int(MemUsed), int(SwapTotal), int(SwapFree)

    @staticmethod
    def get_hdd():
        p = subprocess.check_output(['df', '-Tlm', '--total', '-t', 'ext4', '-t', 'ext3', '-t', 'ext2', '-t', 'reiserfs', '-t', 'jfs', '-t', 'ntfs', '-t', 'fat32', '-t', 'btrfs', '-t', 'fuseblk', '-t', 'zfs', '-t', 'simfs', '-t', 'xfs']).decode("Utf-8")
        total = p.splitlines()[-1]
        used = total.split()[3]
        size = total.split()[2]
        return int(size), int(used)

    @staticmethod
    def get_time():
        with open("/proc/stat", "r") as f:
            time_list = f.readline().split(' ')[2:6]
            for i in range(len(time_list))  :
                time_list[i] = int(time_list[i])
            return time_list

    def delta_time(self):
        x = self.get_time()
        time.sleep(self.interval)
        y = self.get_time()
        for i in range(len(x)):
            y[i] -= x[i]
        return y

    def get_cpu(self):
        t = self.delta_time()
        st = sum(t)
        if st == 0:
            st = 1
        result = 100-(t[len(t)-1]*100.00/st)
        return round(result, 1)

    def traffic(self):
        NET_IN = 0
        NET_OUT = 0
        try:
            data_stats = json.loads(subprocess.getoutput('vnstat --json'))
            # find the last reset day
            for inti_stats in data_stats['interfaces']:
                for line in inti_stats['traffic']['day']:
                    if datetime.datetime(**line['date']).date() >= self.me.last_reset_day():
                        NET_IN += line['rx']
                        NET_OUT += line['tx']

            if self.me.traffic_limit is not None:
                traffic_limit = self.me.traffic_limit * 1024 ** 3
                alert_path = '/tmp/stop_walless'
                if NET_OUT > traffic_limit * 0.999 and os.path.exists('/root/.stop_when_exceed'):
                    if not os.path.exists(alert_path):
                        print('current traffic:', NET_OUT/1024**3, '; quota:', traffic_limit/1024**3)
                        print('Trying to stop walless')
                        os.system('touch ' + alert_path)
                    self.error_state = -2
                else:
                    if os.path.exists(alert_path):
                        os.system('rm ' + alert_path)
                        print('Resume')
                    if self.error_state == -2:
                        self.error_state = 0
        except:
            NET_IN = NET_OUT = 0
        return NET_IN, NET_OUT

    def tupd(self):
        '''
        Hacked to return active user count
        '''
        s = subprocess.check_output("ss -nt|wc -l", shell=True)
        u = int(s[:-1])-1
        # active user count
        n_active = -1
        if self.error_state == -2:
            n_active = -2
        elif os.path.exists('/root/.active_user'):
            with open('/root/.active_user') as f:
                ts, n = f.read().split()
            delta = abs(time.time() - int(ts))
            if delta < 1024:
                n_active = int(n)
            else:
                print('The active user was recorded {} sec ago. I don\' trust it.'.format(delta))
        if n_active != -1:
            self.error_count[0] = time.time()
        if self.error_count[0] + self.error_count[1] < time.time() and not os.path.exists('.no_restart'):
            print('out of patience; rebooting in 16 sec.')
            time.sleep(16)
            os.system('/usr/bin/rebot')
        s = subprocess.check_output("ss -nu|wc -l", shell=True)
        u = int(s[:-1])-1 + u
        s = subprocess.check_output("ps -ef|wc -l", shell=True)
        p = int(s[:-1])-2
        s = subprocess.check_output("ps -eLf|wc -l", shell=True)
        d = int(s[:-1])-2
        return n_active,u,p,d

    def ip_status(self):
        ip_check = 0
        for i in [self.edu, self.cu, self.ct, self.cm]:
            try:
                socket.create_connection((i, self.probeport), timeout=1).close()
            except:
                ip_check += 1
        if ip_check >= 3:
            return False
        else:
            return True

    def get_network(self, ip_version):
        if(ip_version == 4):
            HOST = "ipv4.google.com"
        elif(ip_version == 6):
            HOST = "ipv6.google.com"
        try:
            socket.create_connection((HOST, 80), 2).close()
            return True
        except:
            return False

    def _ping_thread(self, host, mark, port):
        lostPacket = 0
        allPacket = 0
        startTime = time.time()

        while True:
            try:
                b = timeit.default_timer()
                socket.create_connection((host, port), timeout=1).close()
                self.pingTime[mark] = int((timeit.default_timer()-b)*1000)
            except:
                lostPacket += 1
            finally:
                allPacket += 1

            if allPacket > 100:
                self.lostRate[mark] = float(lostPacket) / allPacket

            endTime = time.time()
            if endTime - startTime > 3600:
                lostPacket = 0
                allPacket = 0
                startTime = endTime

            time.sleep(self.interval)

    def _net_speed(self):
        while True:
            with open("/proc/net/dev", "r") as f:
                net_dev = f.readlines()
                avgrx = 0
                avgtx = 0
                for dev in net_dev[2:]:
                    dev = dev.split(':')
                    if "lo" in dev[0] or "tun" in dev[0] \
                            or "docker" in dev[0] or "veth" in dev[0] \
                            or "br-" in dev[0] or "vmbr" in dev[0] \
                            or "vnet" in dev[0] or "kube" in dev[0]:
                        continue
                    dev = dev[1].split()
                    avgrx += int(dev[0])
                    avgtx += int(dev[8])
                now_clock = time.time()
                self.netSpeed["diff"] = now_clock - self.netSpeed["clock"]
                self.netSpeed["clock"] = now_clock
                self.netSpeed["netrx"] = int((avgrx - self.netSpeed["avgrx"]) / self.netSpeed["diff"])
                self.netSpeed["nettx"] = int((avgtx - self.netSpeed["avgtx"]) / self.netSpeed["diff"])
                self.netSpeed["avgrx"] = avgrx
                self.netSpeed["avgtx"] = avgtx
            time.sleep(self.interval)

    def get_realtime_date(self):
        t1 = threading.Thread(
            target=self._ping_thread,
            kwargs={
                'host': self.cu,
                'mark': '10010',
                'port': self.probeport
            },
            daemon=True,
        )
        t2 = threading.Thread(
            target=self._ping_thread,
            kwargs={
                'host': self.ct,
                'mark': '189',
                'port': self.probeport
            },
            daemon=True,
        )
        t3 = threading.Thread(
            target=self._ping_thread,
            kwargs={
                'host': self.cm,
                'mark': '10086',
                'port': self.probeport,
            },
            daemon=True,
        )
        t5 = threading.Thread(
            target=self._ping_thread,
            kwargs={
                'host': self.edu,
                'mark': 'edu',
                'port': self.probeport
            },
            daemon=True,
        )
        t4 = threading.Thread(
            target=self._net_speed,
        )
        t1.start()
        t2.start()
        t3.start()
        t4.start()
        t5.start()

    def byte_str(self, object):
        '''
        bytes to str, str to bytes
        '''
        if isinstance(object, str):
            return object.encode(encoding="utf-8")
        elif isinstance(object, bytes):
            return bytes.decode(object)
        else:
            print(type(object))

    def run(self):
        socket.setdefaulttimeout(30)
        self.get_realtime_date()
        while True:
            try:
                print("Connecting...")
                s = socket.create_connection((self.server, self.port))
                data = self.byte_str(s.recv(1024))
                if data.find("Authentication required") > -1:
                    s.send(self.byte_str(self.user + ':' + self.password + '\n'))
                    data = self.byte_str(s.recv(1024))
                    if data.find("Authentication successful") < 0:
                        print(data)
                        raise socket.error
                else:
                    print(data)
                    raise socket.error

                print(data)
                if data.find("You are connecting via") < 0:
                    data = self.byte_str(s.recv(1024))
                    print(data)

                timer = 0
                check_ip = 0
                if data.find("IPv4") > -1:
                    check_ip = 6
                elif data.find("IPv6") > -1:
                    check_ip = 4
                else:
                    print(data)
                    raise socket.error

                while True:
                    CPU = self.get_cpu()
                    NET_IN, NET_OUT = self.traffic()
                    Uptime = self.get_uptime()
                    Load_1, Load_5, Load_15 = os.getloadavg()
                    MemoryTotal, MemoryUsed, SwapTotal, SwapFree = self.get_memory()
                    HDDTotal, HDDUsed = self.get_hdd()
                    IP_STATUS = self.ip_status()

                    array = {}
                    if not timer:
                        array['online' + str(check_ip)] = self.get_network(check_ip)
                        timer = 10
                    else:
                        timer -= 1*self.interval

                    array['uptime'] = Uptime
                    array['load_1'] = Load_1
                    array['load_5'] = Load_5
                    array['load_15'] = Load_15
                    array['memory_total'] = MemoryTotal
                    array['memory_used'] = MemoryUsed
                    array['swap_total'] = SwapTotal
                    array['swap_used'] = SwapTotal - SwapFree
                    array['hdd_total'] = HDDTotal
                    array['hdd_used'] = HDDUsed
                    array['cpu'] = CPU
                    array['network_rx'] = self.netSpeed.get("netrx")
                    array['network_tx'] = self.netSpeed.get("nettx")
                    array['network_in'] = NET_IN
                    array['network_out'] = NET_OUT
                    array['ip_status'] = IP_STATUS
                    array['ping_10010'] = self.lostRate.get('10010') * 100
                    array['ping_189'] = self.lostRate.get('189') * 100
                    array['ping_10086'] = self.lostRate.get('10086') * 100
                    array['ping_edu'] = self.lostRate.get('edu') * 100
                    array['time_10010'] = self.pingTime.get('10010')
                    array['time_189'] = self.pingTime.get('189')
                    array['time_10086'] = self.pingTime.get('10086')
                    array['time_edu'] = self.pingTime.get('edu')
                    array['tcp'], array['udp'], array['process'], array['thread'] = self.tupd()

                    s.send(self.byte_str("update " + json.dumps(array) + "\n"))
            except KeyboardInterrupt:
                raise
            except socket.error:
                print("Disconnected...")
                if 's' in locals().keys():
                    del s
                time.sleep(3)
            except Exception as e:
                print("Caught Exception:", e)
                if 's' in locals().keys():
                    del s
                time.sleep(3)


if __name__ == '__main__':
    StatusClient().run()
