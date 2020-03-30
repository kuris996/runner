import os

from flask import Flask, jsonify, request
from flask import render_template, Blueprint, jsonify, request, current_app
from multiprocessing import Process
from threading import Lock
from runner.process_watcher import ProcessWatcher

import config
from run_wh import main
import traceback
import sys
import sqlite3
import datetime
import time

app = Flask(__name__)

def set_config(config_dict):
    for parameter, value in config_dict.items():
        if parameter == 'PATH':
            for key, val in config_dict[parameter].items():
                if key == 'wh_prefix' or key == 'wh_file':
                    config.__dict__[parameter][key] = config_dict[parameter][key].format(config_dict['PRODUCT'].replace(" ", "_"))
                elif key == 'wh_add_name':
                    config.__dict__[parameter][key] = config_dict[parameter][key].format(config_dict['PRODUCT'].replace(" ", "_"),
                                                                                     str(config_dict['CORRECTION_FLAG']),
                                                                                     str(config_dict['DELTAS_STORAGE']),
                                                                                     str(config_dict['STORAGES_BUY_ON_MARKET']))
        else:
            config.__dict__[parameter] = value
            
    config.__dict__['STATIONS'] = list(config.__dict__['DCT_FACTORIES_STATIONS'][config_dict['PRODUCT']].keys())
    config.__dict__['FACTORIES'] = list(config.__dict__['DCT_FACTORIES_STATIONS'][config_dict['PRODUCT']].values())
    config.__dict__['REPLACEMENT'] = config.__dict__['REPLACEMENT'][config_dict['PRODUCT']]

process_watchers = {}
process_watchers_lock = Lock()
process_watchers_running_count = 0
process_watchers_running_max_count = 1
default_config = config.__dict__.copy()

def restore_config_from_default():
    for key in [key for key in config.__dict__ if key not in default_config]:
        del config.__dict__[key]
    for key, value in default_config.items():
        try:
            config.__dict__[key] = value
        except AttributeError as e:
            print(e)

def process_watcher_finished(pw):
    global process_watchers_running_count
    try:
        process_watchers_lock.acquire()
        exitcode = pw.exitcode()
        print('process_watcher_finished id:{} with code: {}'.format(pw.id, exitcode))
        if pw.id not in process_watchers:
            return
        value = process_watchers[pw.id]
        value['finishedAt'] = datetime.datetime.now()
        value['check_count'] = 0
        if exitcode == 0:
            value['status'] = "finished"
        else:
            value['status'] = "error"
        process_watchers[pw.id] = value
        process_watchers_running_count -= 1
        if process_watchers_running_count < 0:
            process_watchers_running_count = 0
        # start next process watcher
        start_next_main_process()
    finally:
        process_watchers_lock.release()

def start_next_main_process():
    global process_watchers_running_count
    global process_watchers_running_max_count
    if process_watchers_running_count >= process_watchers_running_max_count:
        return
    for id, value in process_watchers.items():
        if value['status'] != 'idle':
            continue
        pw = value['pw']
        process_watchers[pw.id] = {
            "pw": pw,
            "startedAt": datetime.datetime.now(), 
            "finishedAt": None,
            "status" : "running", 
            "check_count": 0 
        }
        pw.start_watch()
        process_watchers_running_count += 1
        return

def create_main_process(id):
    p = Process(target=main)
    pw = ProcessWatcher(p, process_watcher_finished)
    pw.id = id
    return pw

@app.route('/run', methods=['POST'])
def run():
    status_code = 500
    try:
        data = request.json
        id = data['ID']
        process_watchers_lock.acquire()
        if id not in process_watchers:
            restore_config_from_default()
            set_config(data['Config'])
            pw = create_main_process(id)
            process_watchers[pw.id] = {
                "pw": pw,
                "startedAt": None, 
                "finishedAt": None,
                "status" : "idle", 
                "check_count": 0 
            }
            start_next_main_process()
            status_code = 200
    except Exception as e:
        print(traceback.format_exc())
    finally:
        process_watchers_lock.release()
    response = jsonify({})
    response.status_code = status_code
    return response

@app.route('/check_results', methods=['POST'])
def check_results():
    status_code = 500
    result = {}
    try:
        process_watchers_lock.acquire()
        removed = []
        for id, value in process_watchers.items():
            status = value['status']
            startedAt = None
            finishedAt = None
            if value['startedAt'] != None:
                startedAt = value['startedAt'].isoformat()
            if value['finishedAt'] != None:
                finishedAt = value['finishedAt'].isoformat()
            check_count = value['check_count']
            check_count += 1
            if check_count <= 3:
                value['check_count'] = check_count
                process_watchers[id] = value
                result[id] = {
                    "startedAt" : startedAt,
                    "finishedAt" : finishedAt,
                    "status": status
                }
            elif status == 'error' or status == 'finished':
                removed.append(id)
                
        for id in removed:
            del process_watchers[id]
        status_code = 200
    except Exception as e:
        print(traceback.format_exc())
    finally:
        process_watchers_lock.release()
    response = jsonify(result)
    response.status_code = status_code
    return response

if __name__ == "__main__":
    ENVIRONMENT_DEBUG = os.environ.get("DEBUG", False)
    app.run(host='0.0.0.0', port=5000, debug=ENVIRONMENT_DEBUG)
