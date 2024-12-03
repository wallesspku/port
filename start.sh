#!/usr/bin/bash

# Process:
# 1. if WALLESS_ROOT is not set, set it to $HOME. cd to this directory.
# 2. if WALLESS_VENV is set, activate it
# 3. wait for internet connection
# 4. source env_setup.sh if it exists
# 5. try to pull the latest version of the code for each git repo
# 6. if venv is set, install the latest version of utils
# 7. if PYTHONEXEC is not set, set it to the python3 in the venv or the system
# 8. create a new tmux session named port with a window named service, run the service

if [ -z "$WALLESS_ROOT" ]; then
    export WALLESS_ROOT=$HOME
fi
cd $WALLESS_ROOT

for i in $(seq 10);
do
    if ping -c 1 1.1.1.1; then
        break
    fi
    sleep 2
done
# echo "connected to the internet"

if [ -f ./env_setup.sh ]; then
    source ./env_setup.sh
fi

# pull 
for GITPATH in "./port" "./.config/port_config" "./.config/main_config" "./ca" "./utils" "port_config" "main_config"; 
do
    if [ -d $GITPATH ]; then
        git -C $GITPATH pull
    fi
done

if [ ! -z "$WALLESS_VENV" ]; then
    source $WALLESS_VENV/bin/activate
    if [ ! -z "USE_GIT" ]; then
        pip3 install --force-reinstall git+https://github.com/wallesspku/utils.git
    else
        pip3 install --force-reinstall $WALLESS_ROOT/utils
    fi
fi

if [ -z $PYTHONEXEC ]; then
    if [ $WALLESS_VENV ]; then
        export PYTHONEXEC=$WALLESS_VENV/bin/python3
    else
        export PYTHONEXEC=$(which python3)
    fi
fi

tmux new-session -d -s port -n service
sleep 3
if [ ! -z "$WALLESS_VENV" ]; then
    tmux send-keys -t port:service "source $WALLESS_VENV/bin/activate" C-m
fi
sleep 1
tmux send-keys -t port:service "cd port" C-m
sleep 1
tmux send-keys -t port:service "$PYTHONEXEC run_server.py $WALLESS_ARGS" C-m
