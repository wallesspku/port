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

from walless_utils import wait_for_network, cfg, setup_everything, whoami
setup_everything()

node = whoami()
monitor_cfg = cfg.get('status', {'password': '123', 'server': 'google.com'})
USER = node.uuid
PASSWORD = monitor_cfg.get('password', '123')
SERVER = monitor_cfg.get('server', "google.com")

# Last success; patience
ERR_CNT = [time.time(), 2048]
PORT = 35601
INTERVAL = 1
PROBEPORT = 80
EDU = cfg.get('edu', 'cernet.191110.xyz')
CU = cfg.get('cu', "111.205.231.10")
CT = cfg.get('ct', "ct.tz.cloudcpp.com")
CM = cfg.get('cm', "bj.10086.cn")
ERROR_STATE = 0

print('status server', SERVER)
print('user', USER)
print('password', PASSWORD)
print('edu server', EDU)
print('cu server', CU)
print('ct server', CT)
print('cM server', CM)

def get_uptime():
    with open('/proc/uptime', 'r') as f:
        uptime = f.readline().split('.', 2)
        return int(uptime[0])

def get_memory():
    re_parser = re.compile(r'^(?P<key>\S*):\s*(?P<value>\d*)\s*kB')
    result = dict()
    for line in open('/proc/meminfo'):
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

def get_hdd():
    p = subprocess.check_output(['df', '-Tlm', '--total', '-t', 'ext4', '-t', 'ext3', '-t', 'ext2', '-t', 'reiserfs', '-t', 'jfs', '-t', 'ntfs', '-t', 'fat32', '-t', 'btrfs', '-t', 'fuseblk', '-t', 'zfs', '-t', 'simfs', '-t', 'xfs']).decode("Utf-8")
    total = p.splitlines()[-1]
    used = total.split()[3]
    size = total.split()[2]
    return int(size), int(used)

def get_time():
    with open("/proc/stat", "r") as f:
        time_list = f.readline().split(' ')[2:6]
        for i in range(len(time_list))  :
            time_list[i] = int(time_list[i])
        return time_list

def delta_time():
    x = get_time()
    time.sleep(INTERVAL)
    y = get_time()
    for i in range(len(x)):
        y[i]-=x[i]
    return y

def get_cpu():
    t = delta_time()
    st = sum(t)
    if st == 0:
        st = 1
    result = 100-(t[len(t)-1]*100.00/st)
    return round(result, 1)

def traffic():
    global ERROR_STATE
    NET_IN = 0
    NET_OUT = 0
    try:
        data_stats = json.loads(subprocess.getoutput('vnstat --json'))
        if os.path.exists('/root/.traffic'):
            # Format: (First line) day-of-month <SPACE> traffic (GiB) <SPACE> uni/bidirectional (u/unidirectional)
            # Other lines: %Y%M (e.g. 202203) <SPACE> adjustment-to-the-traffic (GiB) (e.g. -200)
            traffic_file = open('/root/.traffic').read().strip().split('\n')
            traffic_rc = traffic_file[0].split()
            refresh_day = int(traffic_rc[0])
            assert refresh_day <= 31
            date_from = now = datetime.datetime.today()
            if refresh_day > now.day:
                while date_from.month >= now.month:
                    date_from -= datetime.timedelta(days=1)
            date_from = datetime.datetime(year=date_from.year, month=date_from.month, day=refresh_day)
            for inti_stats in data_stats['interfaces']:
                for line in inti_stats['traffic']['day']:
                    if datetime.datetime(**line['date']) >= date_from:
                        NET_IN += line['rx']
                        NET_OUT += line['tx']
            if len(traffic_rc) > 2:
                adjustment = 0
                for line in traffic_file[1:]:
                    line = line.split()
                    if len(line) == 2 and line[0] == date_from.strftime('%Y%m'):
                        adjustment = int(line[1])
                traffic_limit, is_unidirectional = int(traffic_rc[1]), traffic_rc[2] in ['unidirectional', 'u']
                # adjustment is added to traffic used, not to the limit; so we deduct adjustment from limit.
                cur_data = NET_OUT if is_unidirectional else NET_IN + NET_OUT
                traffic_limit -= adjustment
                traffic_limit *= 1024 * 1024 * 1024
                alert_path = '/tmp/stop_walless'
                if cur_data > traffic_limit * 0.999:
                    if not os.path.exists(alert_path):
                        print('current traffic:', cur_data/1024**3, '; quota:', traffic_limit/1024**3)
                        print('Trying to stop walless')
                        os.system('touch ' + alert_path)
                    ERROR_STATE = -2
                else:
                    if os.path.exists(alert_path):
                        os.system('rm ' + alert_path)
                        print('Resume')
                    if ERROR_STATE == -2:
                        ERROR_STATE = 0
        else:
            for inti_stats in data_stats['interfaces']:
                NET_IN += inti_stats['traffic']['total']['rx']
                NET_OUT += inti_stats['traffic']['total']['tx']
        if NET_IN == NET_OUT == 0:
            raise Exception
    except:
        with open('/proc/net/dev') as f:
            for line in f.readlines():
                netinfo = re.findall('([^\s]+):[\s]{0,}(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)', line)
                if netinfo:
                    if netinfo[0][0] == 'lo' or 'tun' in netinfo[0][0] \
                            or 'docker' in netinfo[0][0] or 'veth' in netinfo[0][0] \
                            or 'br-' in netinfo[0][0] or 'vmbr' in netinfo[0][0] \
                            or 'vnet' in netinfo[0][0] or 'kube' in netinfo[0][0] \
                            or netinfo[0][1]=='0' or netinfo[0][9]=='0':
                        continue
                    else:
                        NET_IN += int(netinfo[0][1])
                        NET_OUT += int(netinfo[0][9])
    return NET_IN, NET_OUT

def tupd():
    '''
    tcp, udp, process, thread count: for view ddcc attack , then send warning
    :return:
    '''
    global ERROR_STATE
    s = subprocess.check_output("ss -nt|wc -l", shell=True)
    u = int(s[:-1])-1
    # active user count
    n_active = -1
    if ERROR_STATE == -2:
        n_active = -2
    elif os.path.exists('/root/.active_user'):
        ts, n = open('/root/.active_user').read().split()
        delta = abs(time.time() - int(ts))
        if delta < 1024:
            n_active = int(n)
        else:
            print('The active user was recorded {} sec ago. I don\' trust it.'.format(delta))
    if n_active != -1:
        ERR_CNT[0] = time.time()
    if ERR_CNT[0] + ERR_CNT[1] < time.time() and not os.path.exists('.no_restart'):
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

def ip_status():
    ip_check = 0
    for i in [EDU, CU, CT, CM]:
        try:
            socket.create_connection((i, PROBEPORT), timeout=1).close()
        except:
            ip_check += 1
    if ip_check >= 3:
        return False
    else:
        return True

def get_network(ip_version):
    if(ip_version == 4):
        HOST = "ipv4.google.com"
    elif(ip_version == 6):
        HOST = "ipv6.google.com"
    try:
        socket.create_connection((HOST, 80), 2).close()
        return True
    except:
        return False

lostRate = {
    '10010': 0.0,
    '189': 0.0,
    '10086': 0.0,
    'edu': 0.0,
}
pingTime = {
    '10010': 0,
    '189': 0,
    '10086': 0,
    'edu': 0,
}
netSpeed = {
    'netrx': 0.0,
    'nettx': 0.0,
    'clock': 0.0,
    'diff': 0.0,
    'avgrx': 0,
    'avgtx': 0
}

def _ping_thread(host, mark, port):
    lostPacket = 0
    allPacket = 0
    startTime = time.time()

    while True:
        try:
            b = timeit.default_timer()
            socket.create_connection((host, port), timeout=1).close()
            pingTime[mark] = int((timeit.default_timer()-b)*1000)
        except:
            lostPacket += 1
        finally:
            allPacket += 1

        if allPacket > 100:
            lostRate[mark] = float(lostPacket) / allPacket

        endTime = time.time()
        if endTime - startTime > 3600:
            lostPacket = 0
            allPacket = 0
            startTime = endTime

        time.sleep(INTERVAL)

def _net_speed():
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
            netSpeed["diff"] = now_clock - netSpeed["clock"]
            netSpeed["clock"] = now_clock
            netSpeed["netrx"] = int((avgrx - netSpeed["avgrx"]) / netSpeed["diff"])
            netSpeed["nettx"] = int((avgtx - netSpeed["avgtx"]) / netSpeed["diff"])
            netSpeed["avgrx"] = avgrx
            netSpeed["avgtx"] = avgtx
        time.sleep(INTERVAL)

def get_realtime_date():
    t1 = threading.Thread(
        target=_ping_thread,
        kwargs={
            'host': CU,
            'mark': '10010',
            'port': PROBEPORT
        }
    )
    t2 = threading.Thread(
        target=_ping_thread,
        kwargs={
            'host': CT,
            'mark': '189',
            'port': PROBEPORT
        }
    )
    t3 = threading.Thread(
        target=_ping_thread,
        kwargs={
            'host': CM,
            'mark': '10086',
            'port': PROBEPORT
        }
    )
    t5 = threading.Thread(
        target=_ping_thread,
        kwargs={
            'host': EDU,
            'mark': 'edu',
            'port': PROBEPORT
        }
    )
    t4 = threading.Thread(
        target=_net_speed,
    )
    t1.setDaemon(True)
    t2.setDaemon(True)
    t3.setDaemon(True)
    t4.setDaemon(True)
    t5.setDaemon(True)
    t1.start()
    t2.start()
    t3.start()
    t4.start()
    t5.start()

def byte_str(object):
    '''
    bytes to str, str to bytes
    :param object:
    :return:
    '''
    if isinstance(object, str):
        return object.encode(encoding="utf-8")
    elif isinstance(object, bytes):
        return bytes.decode(object)
    else:
        print(type(object))

if __name__ == '__main__':
    wait_for_network()
    for argc in sys.argv:
        if 'SERVER' in argc:
            SERVER = argc.split('SERVER=')[-1]
        elif 'PORT' in argc:
            PORT = int(argc.split('PORT=')[-1])
        elif 'USER' in argc:
            USER = argc.split('USER=')[-1]
        elif 'PASSWORD' in argc:
            PASSWORD = argc.split('PASSWORD=')[-1]
        elif 'INTERVAL' in argc:
            INTERVAL = int(argc.split('INTERVAL=')[-1])
    socket.setdefaulttimeout(30)
    get_realtime_date()
    while True:
        try:
            print("Connecting...")
            s = socket.create_connection((SERVER, PORT))
            data = byte_str(s.recv(1024))
            if data.find("Authentication required") > -1:
                s.send(byte_str(USER + ':' + PASSWORD + '\n'))
                data = byte_str(s.recv(1024))
                if data.find("Authentication successful") < 0:
                    print(data)
                    raise socket.error
            else:
                print(data)
                raise socket.error

            print(data)
            if data.find("You are connecting via") < 0:
                data = byte_str(s.recv(1024))
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
                CPU = get_cpu()
                NET_IN, NET_OUT = traffic()
                Uptime = get_uptime()
                Load_1, Load_5, Load_15 = os.getloadavg()
                MemoryTotal, MemoryUsed, SwapTotal, SwapFree = get_memory()
                HDDTotal, HDDUsed = get_hdd()
                IP_STATUS = ip_status()

                array = {}
                if not timer:
                    array['online' + str(check_ip)] = get_network(check_ip)
                    timer = 10
                else:
                    timer -= 1*INTERVAL

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
                array['network_rx'] = netSpeed.get("netrx")
                array['network_tx'] = netSpeed.get("nettx")
                array['network_in'] = NET_IN
                array['network_out'] = NET_OUT
                array['ip_status'] = IP_STATUS
                array['ping_10010'] = lostRate.get('10010') * 100
                array['ping_189'] = lostRate.get('189') * 100
                array['ping_10086'] = lostRate.get('10086') * 100
                array['ping_edu'] = lostRate.get('edu') * 100
                array['time_10010'] = pingTime.get('10010')
                array['time_189'] = pingTime.get('189')
                array['time_10086'] = pingTime.get('10086')
                array['time_edu'] = pingTime.get('edu')
                array['tcp'], array['udp'], array['process'], array['thread'] = tupd()

                s.send(byte_str("update " + json.dumps(array) + "\n"))
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