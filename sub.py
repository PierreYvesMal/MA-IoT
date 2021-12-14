#!/usr/bin/env python

# Copyright 2019 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import argparse
import requests
import os
from google.cloud import pubsub_v1


def sub(project_id: str, subscription_id: str,url: str = "192.168.1.160:5000", timeout: float = None) -> None:
    """Receives messages from a Pub/Sub subscription."""
    # Initialize a Subscriber client
    subscriber_client = pubsub_v1.SubscriberClient()
    # Create a fully qualified identifier in the form of
    # `projects/{project_id}/subscriptions/{subscription_id}`
    subscription_path = subscriber_client.subscription_path(project_id, subscription_id)

    def callback(message: pubsub_v1.subscriber.message.Message) -> None:
        #print(f"Received {message}.")
        # Acknowledge the message. Unack'ed messages will be redelivered.
        message.ack()
        
        #parserf(message)
        #Need a try/catch around that btw
        #payload = requests.get('http://192.168.1.160:5000/dimmer/2/level').text
        payload=parserf(message,url)
        print(f"Acknowledged {message.message_id}." + payload)

    streaming_pull_future = subscriber_client.subscribe(
        subscription_path, callback=callback
    )
    print(f"Listening for messages on {subscription_path}..\n")

    try:
        # Calling result() on StreamingPullFuture keeps the main thread from
        # exiting while messages get processed in the callbacks.
        streaming_pull_future.result(timeout=timeout)
    except:  # noqa
        streaming_pull_future.cancel()  # Trigger the shutdown.
        streaming_pull_future.result()  # Block until the shutdown is complete.

    subscriber_client.close()

def parserf(message,url):
    payload = "EmptyPayload"
    msg=bytes.decode(message.data)
    sliced=msg[6:len(msg)-2] #Removing trash : {msg:\"
    splitted=sliced.split(".")

    if splitted[0]=="Rad":
        print("")
        cmd = "./knx/knx_client_script.py raw "+splitted[1]
        os.system(cmd)
        cmd2 = "./knx/knx_client_script.py raw "+splitted[2]
        os.system(cmd2)
        print("Rad")
        payload="Rad"
    elif splitted[0]=="Light":
        print("")
        print("Light")
        try:
            #Level should be splitted[2] but rly i don't remember how that exactly works and since raspy is broken...
            #arg="http://"+url+"/dimmer/"+splitted[1]+"/level"
            #arg="http://"+url+"/dimmer/"+5+"/level"
            #payload = requests.get(arg).text

            http_headers = {'Content-Type' : 'application/json'}
            dataz={"node_id": 5, "value": splitted[2]}
            #urlz=url+'/dimmer/set_level'
            urlz='http://10.128.31.42:5000/dimmer/set_level'
            payload = requests.post(urlz, data=json.dumps(dataz),headers=http_headers)
            
            payload="Light"
        except:
            payload = "Light, Request never reached. Is the ipv4 set correctly ?"
    elif splitted[0]=="Store":
        print("")
        # x/y/z : function/floor/block
        #Everything is probably gonna be dtm in app 
        cmd = "./knx/knx_client_script.py raw "+splitted[1]
        os.system(cmd)
        cmd2 = "./knx/knx_client_script.py raw "+splitted[2]
        os.system(cmd2)
        print("Store")
        payload="Store"
    else:
        print("")
        print("Unrecognized command")

    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("project_id", help="Google Cloud project ID")
    parser.add_argument("subscription_id", help="Pub/Sub subscription ID")
    parser.add_argument(
        "timeout", default=None, nargs="?", const=1, help="Pub/Sub subscription ID"
    )

    args = parser.parse_args()

    sub(args.project_id, args.subscription_id, args.timeout)


