import json
import os
import time
import requests
from fastapi import BackgroundTasks, FastAPI

app = FastAPI()
url = "10.128.0.17"


def authorize():
    js = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {
                        "id": "10434be3e560454d862d9bb911b86762",
                        "password": "secret",
                    }
                },

            },
            "scope": {
                "system": {
                    "all": True
                }
            }
        }
    }
    r = requests.post(
        "http://{0}/identity/v3/auth/tokens".format(url), data=json.dumps(js)
    )
    print(r.status_code)
    print(r.headers)
    print(type(r.headers))
    print(r.json())
    return r.headers.get("X-Subject-Token", "")


def write_notification(uid: str, tag: str):
    token = authorize()
    x = {
        "events": [
            {
                "name": "custom-event",
                "server_uuid": uid,
                "tag": tag,
                "status": "finished",
            }
        ]
    }
    print(x)
    print("uuid {0}".format(uid))
    time.sleep(3)
    headers = {"X-Auth-Token": token}
    r = requests.post(
        "http://{0}/compute/v2.1/os-server-external-events".format(url),
        data=json.dumps(x),
        headers=headers,
    )
    # r = requests.get("http://{0}/compute/v2.1/servers".format(url), headers=headers)
    print(r.status_code)
    print(r.json())


@app.get("/{uid}/{tag}")
async def root(uid: str, tag: str,  background_tasks: BackgroundTasks):
    background_tasks.add_task(write_notification, uid=uid,tag=tag)
    return {"message": "token", "uid": uid}


@app.post("/{uid}/{tag}")
async def root(uid: str,tag: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(write_notification, uid=uid,tag=tag)
