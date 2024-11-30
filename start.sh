#!/usr/bin/bash

if [ -z "$WALLESS_ROOT" ]; then
    export WALLESS_ROOT=$HOME
fi
cd $WALLESS_ROOT

if [ ! -z "$WALLESS_VENV" ]; then
    source $WALLESS_VENV/bin/activate
fi

for i in $(seq 10);
do
    if ping -c 1 1.1.1.1; then
        break
    fi
    sleep 2
done
# echo "connected to the internet"

git -C port pull
git -C .config/port_config pull
git -C ca pull
pip3 install --force-reinstall git+https://github.com/wallesspku/utils.git

tmux new-session -d -s port -n service
sleep 3
if [ ! -z "$WALLESS_VENV" ]; then
    tmux send-keys -t port:service "source $WALLESS_VENV/bin/activate" C-m
fi
sleep 1
tmux send-keys -t port:service "cd port" C-m
sleep 1
tmux send-keys -t port:service "python3 run_server.py $WALLESS_ARGS" C-m
