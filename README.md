# _For LINE_ :smile: 

by Surender Singh Lamba [Github](https://github.com/surender7522)

---
# Overview

I really enjoyed working on this over the weekend, deploying devstack instance on GCP compute and figuring out things. I have used stable/queens for assignment 2 as the requested feature has been __deprecated__ in later releases and have used the master branch for assignment 1.

This document also shows what code changes I have made and solved specific problems. I have glossed over unit testing part because unfortunately I dont have time on weekdays due to my current job.

I have attached this document, patch files for assignment 1 and assignment 2, server files in the zip.

------------

# Nova Assignment 1

Q1. _Read and understand Nova VM creation life-cycle, from the point that Nova API receives a VM create request (POST /servers) until VM is created by libvirt, network is attached and finally VM is booted and running on one of the nova-compute. Give a brief step by step explanation of a VM creation life-cycle._

Ans: 
Steps to create a vm:
![image](https://user-images.githubusercontent.com/10762179/121834800-a2d27280-cd0a-11eb-96a2-d4748a686f8a.png)

1. Keystone authenticates user through cli or horizon, sends back X-Subject-Token in header to be used as X-Auth-Token for all requests
```sh
POST /identity/v3/auth/tokens
{"auth":{"identity":{"methods":["password"],"password":{"user":{"id":"10434be3e560454d862d9bb911b86762","password":"secret"}}},"scope":{"system":{"all":true}}}}
Response Headers
{'Date': 'Sun, 13 Jun 2021 18:40:20 GMT', 'Server': 'Apache/2.4.18 (Ubuntu)', 'X-Subject-Token': 'gAAAAABgxlEUnLRs3oFU04281kFw_mVQy86kVeaHwe5uAFiP9Ari1mYTNGuQCi442ggFvVu_HMyRv7QWbqVILrmNQ7eb5_Y8YZggDqvC2mVa9wP0yyIVdIxybZoNlX6sxFbdWftkVr0uVMu-6Zx5T_S9qkAt2QjttfNnvmI6hluZbwdVkp15clU', 'Vary': 'X-Auth-Token', 'Content-Type': 'application/json', 'Content-Length': '3387', 'x-openstack-request-id': 'req-ba6e7179-cbee-4acb-94f5-967466df92a3', 'Connection': 'close'}
```
2. Nova API service receives server create request, sends it to keystone service for auth token validation.
```sh
POST /compute/v2.1/servers
{"server":{"name":"sfda","imageRef":"c1e434a1-40c9-4859-81d5-a865ff9f1a79","availability_zone":"nova","flavorRef":"42","OS-DCF:diskConfig":"AUTO","max_count":2,"min_count":1}}
Response
{'server': {'security_groups': [{'name': 'default'}], 'OS-DCF:diskConfig': 'AUTO', 'id': '1e256d68-126a-42a2-a623-5800124db5a3', 'links': [{'href': 'http://35.192.0.7/compute/v2.1/servers/1e256d68-126a-42a2-a623-5800124db5a3', 'rel': 'self'}, {'href': 'http://35.192.0.7/compute/servers/1e256d68-126a-42a2-a623-5800124db5a3', 'rel': 'bookmark'}], 'adminPass': 'WcPh365eVC3H'}}
```
3. Keystone service validates, sends back roles, permissions for this token to enable policy enforcement in nova.
4. Nova checks for policies applying to these requests, checks for conflicts in the database, creates an entry for this instance.
5. Nova api calls scheduler using rpc to get updated instance entry.
6. Scheduler takes the request from the queue and with the help of nova db to locate appropriate host/hypervisor where this instance can be created using placement algorithms and sends back instance entry host id.
7. Scheduler sends a request to compute service to launch the instance using rpc.
8. Nova compute picks the request from the queue and calls nova conductor to get instance information such as host id, flavor, resource information such as cpu, ram, disk etc using rpc call.
9. Nova conductor picks the request from queue, calls nova db and gets information which is sent back to compute.
10. Nova compute calls glance api with auth token to get the image URI from image information and loads it from image storage.
11. Glance api authenticates the token using keystone and sends back the image metadata.
12. Nova compute calls neutron api with auth token to place network provision request based on available instance information.
13. Neutron api authenticates the token using keystone and starts the provisioning of network, return back metadata.
14. Nova compute calls volume/cinder api using auth token to allocate storage according to instance information.
15. Cinder authenticates the request using keystone and sends back block storage information.
16. Nova compute creates the full information combining the above things and makes a request to hypervisor, like libvirt to provision the instance. A lot of these calls are async using os-server-external-events api to communicate when things are provisioned. **The wait\_for\_instance function maintains greenlet threads to yield and respond when the messages arrive or some timeout happens**
17. Libvirt/hypervisor creates the instance on host, providing appropriate event updates based on which the VM is moved to running state or error state.
**VM lifecycle FSM**
![](https://docs.openstack.org/nova/latest/_images/graphviz-fa8a74bb135d06ccb43a311b6e3dcbaaf9041e3c.png)
Q2. _Implement changes in Nova API and/or Nova Compute code (by extending /os-server-external-events and other features), in order that VM creation life-cycle will support reporting and checking result notifications to/from an external third-party API system, before VM can be successfully created._

Ans: 
**Assumptions: The question mentions making the third part call and waiting in the "PAUSED" state on the hypervisor, also called power-state of VM. But from the below diagram taken from [libvirt's website](https://wiki.libvirt.org/page/VM_lifecycle), it starts from Undefined / "No State" and directly goes to "Running", I assume, you want me to do this in this "No State".
It is also assumed that we are implementing for libvirt hypervisor, logic can be extended to other implementations**
![](https://wiki.libvirt.org/images/d/da/Vm_lifecycle_graph.png)

Solution:
1. Added custom-event to enum for server\_external\_events model
```py
--- a/nova/api/openstack/compute/schemas/server_external_events.py
+++ b/nova/api/openstack/compute/schemas/server_external_events.py
@@ -32,7 +32,8 @@ create = {
                             'network-changed',
                             'network-vif-plugged',
                             'network-vif-unplugged',
-                            'network-vif-deleted'
+                            'network-vif-deleted',
+                            'custom-event'
                         ],
                     },
                     'status': {

--- a/nova/objects/external_event.py
+++ b/nova/objects/external_event.py
@@ -23,6 +23,7 @@ EVENT_NAMES = [
     'network-vif-plugged',
     'network-vif-unplugged',
     'network-vif-deleted',
+    'custom-event',

     # Volume was extended for this instance, tag is volume_id
     'volume-extended',
```
2. Added conf option for third\_party\_timeout to specify wait time for our api after which timeout exception is raised
```py
--- a/nova/conf/compute.py
+++ b/nova/conf/compute.py
@@ -176,6 +176,7 @@ Related options:
   ``vif_plugging_is_fatal`` is False, events should not be expected to
   arrive at all.
 """),
+    cfg.IntOpt('third_party_timeout',default=15, min=0, help=""),
     cfg.IntOpt('arq_binding_timeout',
         default=300,
         min=1,
```
3. Added support for calling the third party API, assuming the server is running on localhost:8000 here, we are sending it the instance uuid, event tag, so third party API can trigger it back on /os-server-external-events.
Also note, we are using Openstack's wait\_for\_instance\_event to create greenlet Event object to wait on, and pass a custom\_failed\_fallback function which will raise VirtualInterfaceCreateException to abort VM creation and cleanup resources. 
```py
--- a/nova/virt/libvirt/driver.py
+++ b/nova/virt/libvirt/driver.py
@@ -7134,6 +7134,13 @@ class LibvirtDriver(driver.ComputeDriver):
             if libvirt_secret is not None:
                 libvirt_secret.undefine()

+    def _custom_failed_callback(self, event_name, instance):
+        LOG.error('Third Party Reported failure on event '
+                  '%(event)s for instance %(uuid)s',
+                  {'event': event_name, 'uuid': instance.uuid},
+                  instance=instance)
+        raise exception.VirtualInterfaceCreateException()
+
     def _neutron_failed_callback(self, event_name, instance):
         LOG.error('Neutron Reported failure on event '
                   '%(event)s for instance %(uuid)s',
@@ -7177,8 +7184,15 @@ class LibvirtDriver(driver.ComputeDriver):
         else:
             events = []

+        event_custom=[('custom-event',events[-1][1])]
         pause = bool(events)
         try:
+            with self.virtapi.wait_for_instance_event(
+                instance, event_custom, deadline=CONF.third_party_timeout,
+                error_callback=self._custom_failed_callback,
+            ):
+                import requests
+                requests.get('http://localhost:8000/{0}/{1}'.format(instance.uuid,event_custom[-1][1]))
             with self.virtapi.wait_for_instance_event(
                 instance, events, deadline=timeout,
                 error_callback=self._neutron_failed_callback,

```
4. We add hook to handle the custom-event depending on the tag, so that we can raise exception or report success to our waiting thread.
```py
--- a/nova/compute/manager.py
+++ b/nova/compute/manager.py
@@ -10416,6 +10417,17 @@ class ComputeManager(manager.Manager):
                 return
         do_power_update()

+    def handle_custom_event(self, instance, event):
+        _event = self.instance_events.pop_instance_event(instance, event)
+        if _event and event.status == "finished":
+            LOG.debug('Processing success event %(event)s',
+                      {'event': event.key}, instance=instance)
+            _event.send(event)
+        elif _event and event.status == "failed":
+            LOG.debug('Processing failed event %(event)s',
+                      {'event': event.key}, instance=instance)
+            _event.send_exception(exception.VirtualInterfaceCreateException())
+
     @wrap_exception()
     def external_instance_event(self, context, instances, events):
         # NOTE(danms): Some event types are handled by the manager, such
@@ -10453,6 +10465,8 @@ class ComputeManager(manager.Manager):
                 self.extend_volume(context, instance, event.tag)
             elif event.name == 'power-update':
                 self.power_update(context, instance, event.tag)
+            elif event.name == 'custom-event':
+                self.handle_custom_event(instance,event)
             else:
                 self._process_instance_event(instance, event)
```
5. Finally, we handle tag 'finished' as it is not in the enum and wait\_for\_instance_event's logic as a successful tag
```py
--- a/nova/compute/manager.py
+++ b/nova/compute/manager.py
@@ -477,7 +477,7 @@ class ComputeVirtAPI(virtapi.VirtAPI):
                     continue
                 else:
                     actual_event = event.wait()
-                    if actual_event.status == 'completed':
+                    if actual_event.status == 'completed' or actual_event.status == 'finished':
                         continue
                 # If we get here, we have an event that was not completed,
                 # nor skipped via exit_wait_early(). Decide whether to
--- a/nova/objects/external_event.py
+++ b/nova/objects/external_event.py
@@ -35,7 +36,7 @@ EVENT_NAMES = [
     'accelerator-request-bound',
 ]

-EVENT_STATUSES = ['failed', 'completed', 'in-progress']
+EVENT_STATUSES = ['failed', 'completed', 'in-progress', 'finished']

 # Possible tag values for the power-update event.
 POWER_ON = 'POWER_ON'


```
6. Note that cleanup of all resources is automatically done on the exception, and VM state is set to ERROR. We also use a simple server which receives the get request with uuid, tag and authenticates using the keystone server, and sends a post request.
**We need to set url, userid, password, status we want to send, sleep time appropriately to test various scenarios, please also set this in server code to send request**
A start .sh file is provided to install dependencies for the server, the run command is
```sh
#! /bin/bash
curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python3
$HOME/.poetry/bin/poetry install
$HOME/.poetry/bin/poetry shell
hypercorn main:app --bind "[::]:8000"
```
```py
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

```
--------
# Nova Assignment 2

Q1. _Implement additional boolean configuration parameter, force\_multi\_instance\_display\_name, so that
multi\_instance\_display\_name\_template is applied for single instances as well_

Ans: 
1. To extend the template option for single instance, we add a boolean option in conf
```py
--- a/nova/conf/compute.py
+++ b/nova/conf/compute.py
@@ -75,8 +75,9 @@ Possible values:
                 img_signature_certificate_uuid
 
 """),
+    cfg.BoolOpt('force_multi_instance_display_name', default=True, help=""),
```
2. We add it to if condition calling the name change function
```py
--- a/nova/compute/api.py
+++ b/nova/compute/api.py
@@ -1568,14 +1569,60 @@ class API(base.Base):

-        if num_instances > 1 and self.cell_type != 'api':
+        if (num_instances > 1 or CONF.force_multi_instance_display_name) and self.cell_type != 'api':
             instance = self._apply_instance_name_template(context, instance,
-                                                          index)
+                                                          (int(instance.metadata["vm_count_no"])-1))

```

Q2. _Study the behaviour of the code that handles multi\_instance\_display\_name\_template parameter and extend it so that an additional template key, "project-name" can be specified in the template_

Ans:
1. We add the example pattern for multi_instance_display_name_template to test out scenarios
```py
--- a/nova/conf/compute.py
+++ b/nova/conf/compute.py
@@ -75,8 +75,9 @@ Possible values:
                 img_signature_certificate_uuid
 
 """),
+    cfg.BoolOpt('force_multi_instance_display_name', default=True, help=""),
     cfg.StrOpt('multi_instance_display_name_template',
-        default='%(name)s-%(count)d',
+        default='%(name)s-%(count)d-%(project-name)s',
         deprecated_for_removal=True,
         deprecated_since='15.0.0',
         deprecated_reason="""
```
2. We extend the renaming function to use project-name in pattern substitution
```py
--- a/nova/compute/api.py
+++ b/nova/compute/api.py
@@ -515,11 +515,12 @@ class API(base.Base):
             'auto_disk_config': auto_disk_config
         }
 
-    def _new_instance_name_from_template(self, uuid, display_name, index):
+    def _new_instance_name_from_template(self, uuid, display_name, index, project_name):
         params = {
             'uuid': uuid,
             'name': display_name,
             'count': index + 1,
+            'project-name': project_name
         }
         try:
             new_name = (CONF.multi_instance_display_name_template %
@@ -533,7 +534,7 @@ class API(base.Base):
     def _apply_instance_name_template(self, context, instance, index):
         original_name = instance.display_name
         new_name = self._new_instance_name_from_template(instance.uuid,
-                instance.display_name, index)
+                instance.display_name, index, context.project_name)
         instance.display_name = new_name
         if not instance.get('hostname', None):
             if utils.sanitize_hostname(original_name) == "":
```

Q3. _Extend the code checks around "count" template key, so that the latest VM with a count index is considered for the further VM assignments, so that VMs having same requested name can always have unique display name e.g. create "test" VM → test1, create "sample" → sample1, create "test" VM again → test2_

Ans:
We achieve this functionality by adding the current vm's number to its metadata, as its difficult to parse back substituted values in python2's templating format '%(name)s' and python parse function only works on format strings of type " '{0} {}'.format(name, 1) ".
So for this reason, we use metadata to store the value, and when a new server create request comes, we query for existing vms containing the full name, the access metadata to increment current vm's number.
**Note 1: The functionality is not foolproof as vm names can be substrings of each other and can give wrong results, so its better to switch to new python string templating format and use parse library to extract count from hostname directly, we are not changing that as it affects nova config fundamentally. My implementation works in standard cases.**

**Note 2: A function level listing would have been better but seems that route will also need authorization, so I went with the simplest path**

1. Get vm count and add it to metadata., use api call to get existing vms with similar name
```py
--- a/nova/compute/api.py
+++ b/nova/compute/api.py
@@ -24,7 +24,8 @@ import copy
 import functools
 import re
 import string
-
+import json
+import requests
 from castellan import key_manager
 from oslo_log import log as logging
 from oslo_messaging import exceptions as oslo_exceptions
@@ -84,7 +85,6 @@ from nova import servicegroup
 from nova import utils
 from nova.virt import hardware
 from nova.volume import cinder
-
 LOG = logging.getLogger(__name__)
 
 get_notifier = functools.partial(rpc.get_notifier, service='compute')

@@ -1568,14 +1569,60 @@ class API(base.Base):
             instance.security_groups = objects.SecurityGroupList()
         else:
             instance.security_groups = security_groups
-
+        instance.metadata["vm_count_no"] = str( 1  + self.get_latest_vm_count(instance.display_name))
         self._populate_instance_names(instance, num_instances)
         instance.shutdown_terminate = shutdown_terminate
-        if num_instances > 1 and self.cell_type != 'api':
+        if (num_instances > 1 or CONF.force_multi_instance_display_name) and self.cell_type != 'api':
             instance = self._apply_instance_name_template(context, instance,
-                                                          index)
+                                                          (int(instance.metadata["vm_count_no"])-1))
 
         return instance
+    
+    def authorize(self, url, user, passw):
+        js = {
+            "auth": {
+                "identity": {
+                    "methods": ["password"],
+                    "password": {
+                        "user": {
+                            "name": user,
+                            "domain": { "id": "default" },
+                            "password": passw
+                        }
+                    },
+
+                },
+                "scope": {
+                    "project": {
+                        "name": "demo",
+                        "domain": { "id": "default" }
+                    }
+                }
+            }
+        }
+        r = requests.post(
+            "http://{0}/identity/v3/auth/tokens".format(url), data=json.dumps(js)
+        )
+        return r.headers.get("X-Subject-Token", "")
+
+
+    def get_latest_vm_count(self, name):
+        url = "localhost"
+        token = self.authorize(url, "admin", "secret")
+        headers = {"X-Auth-Token": token}
+        r = requests.get("http://{0}/compute/v2.1/servers?sort_key=hostname&name={1}".format(url,name), headers=headers)
+        if r.status_code < 300:
+            ret_json = r.json()
+            if not ret_json["servers"]:
+                return 0
+            r = requests.get("http://{0}/compute/v2.1/servers/{1}".format(url,ret_json["servers"][0]["id"]), headers=headers)
+            if r.status_code < 300:
+                ret_json = r.json()
+                return int(ret_json["server"]["metadata"]["vm_count_no"])
+            else:
+                return 0
+        else:
+            return 0
 
     def _create_tag_list_obj(self, context, tags):
         """Create TagList objects from simple string tags.


```

---------
Made with :heart: by Surender Singh Lamba. [Github](https://github.com/surender7522)
