# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
#     http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.

from urllib.request import HTTPHandler, Request, build_opener
import boto3
import json
import jmespath
from botocore.exceptions import ParamValidationError
import re
import random
import string

def sendResponse(event, context, status, message, data=None, resourceid=None):
    body = json.dumps({
        'Status': status,
        'Reason': message,
        'StackId': event['StackId'],
        'RequestId': event['RequestId'],
        'LogicalResourceId': event['LogicalResourceId'],
        'PhysicalResourceId': event['ResourceProperties']['Action'] if resourceid is None else resourceid,
        'Data': {} if data is None else data
    })

    request = Request(event['ResponseURL'], data=str.encode(body))
    request.add_header('Content-Type', '')
    request.add_header('Content-Length', len(body))
    request.get_method = lambda: 'PUT'

    opener = build_opener(HTTPHandler)
    opener.open(request)

def execute(action, properties):
    action = action.split('.')

    if len(action) != 2:
        return 'FAILED', f"Invalid boto3 call: {'.'.join(action)}", None, None

    client, function = action[0], action[1]

    resource_id = None
    response_data = {}
    response_ref = properties.pop('_Ref', None)
    response_getatt = properties.pop('_GetAtt', None)

    client = boto3.client(client.lower())
    function = getattr(client, function)
    type_conversions = []
    drop_fields = []
    for r in range(2):
        try:
            for tc in type_conversions:
                if tc['valid_type'] == 'bool':
                    Set(properties, tc['jmespath'].split('.'), bool(jmespath.search(tc['jmespath'], properties)))
                elif tc['valid_type'] == 'int':
                    Set(properties, tc['jmespath'].split('.'), int(jmespath.search(tc['jmespath'], properties)))
                elif tc['valid_type'] == 'str':
                    if tc['bad_type'] == 'dict':
                        Set(properties, tc['jmespath'].split('.'), json.dumps(jmespath.search(tc['jmespath'], properties)))
                    else:
                        Set(properties, tc['jmespath'].split('.'), str(jmespath.search(tc['jmespath'], properties)))
            for df in drop_fields:
                del properties[df]

            response = function(**properties)

            if response_ref:
                resource_id = jmespath.search(response_ref, response)
                if resource_id is None:
                    resource_id = jmespath.search(response_ref, properties)
            if response_getatt:
                for k, v in response_getatt.items():
                    response_data[k] = jmespath.search(v, response)

        except ParamValidationError as pve:
            print('Invalid parameter type(s) found:')
            for e in pve.args[0].split('\n')[1:]:
                if e.startswith('Invalid type for parameter'):
                    match = re.search(r"^Invalid type for parameter ([^,]+), .*, type: <class '([^']+)'>, valid types: <class '([^']+)'>$", e)
                    type_conversions.append({'jmespath': match.group(1), 'bad_type': match.group(2), 'valid_type': match.group(3)})
                elif e.startswith('Unknown parameter in input'):
                    match = re.search(r'^Unknown parameter in input: "([^"]+)",.*$',e)
                    drop_fields.append(match.group(1))
                else:
                    print(e)
            if (len(type_conversions) + len(drop_fields)) == 0:
                print('No alterations possible.')
                return 'FAILED', f'boto3 error: {pve}', None, None
            print('Type conversions: ', json.dumps(type_conversions))
            print('Fields to drop: ', json.dumps(drop_fields))
        except Exception as e:
            print(e)
            return 'FAILED', f'boto3 error: {e}', None, None
        else:
            break
    else:
        return 'FAILED', 'Retries exhausted', None, None

    return 'SUCCESS', 'Completed successfully', resource_id, response_data

def handler(event, context):
    print(json.dumps(event))

    request = event['RequestType']
    properties = event['ResourceProperties']

    if any(prop not in properties for prop in ('Action', 'Properties')):
        print('Bad properties', properties)
        return sendResponse(event, context, 'FAILED', 'Missing required parameters')

    if '_CustomName' in properties['Properties']:
        stack_name = event['StackId'].split('/')[1]
        logical_resource_id = event['LogicalResourceId']
        if properties['Properties']['_CustomName'] not in properties['Properties']:
            properties['Properties'][properties['Properties']['_CustomName']] = f'{stack_name}-{logical_resource_id}-{CloudFormationRandomName()}'

        del properties['Properties']['_CustomName']

    mode = properties['Mode']

    if request == mode or request in mode:
        action = properties['Action']
        if request == 'Update':
            properties['Properties'][properties['Properties']['_Ref']] = event['PhysicalResourceId']
            if '_UpdateAction' in properties['Properties']:
                action = '.'.join([action.split('.')[0], properties['Properties']['_UpdateAction']['Method']])
                if '_Ref' in properties['Properties']['_UpdateAction']:
                    properties['Properties'][properties['Properties']['_UpdateAction']['_Ref']] = event['PhysicalResourceId']
        elif request =='Delete':
            properties['Properties'][properties['Properties']['_Ref']] = event['PhysicalResourceId']
            if '_DeleteAction' in properties['Properties']:
                action = '.'.join([action.split('.')[0], properties['Properties']['_DeleteAction']['Method']])
                if '_Ref' in properties['Properties']['_DeleteAction']:
                    properties['Properties'][properties['Properties']['_DeleteAction']['_Ref']] = event['PhysicalResourceId']
        properties['Properties'].pop('_UpdateAction', None)
        properties['Properties'].pop('_DeleteAction', None)
        print(f'Action determined: {action}')        
        status, message, resourceid, data = execute(action, properties['Properties'])
        if resourceid is None and 'PhysicalResourceId' in event:
            resourceid = event['PhysicalResourceId']
        print(status, message, resourceid, data)
        return sendResponse(event, context, status, message, data, resourceid)

    return sendResponse(event, context, 'SUCCESS', 'No action taken')

def Set(d, a, v):
    if len(a) == 1:
        if a[0] in d.keys():
            d[a[0]] = v
    else:
        if a[0] in d.keys():
            return Set(d[a[0]], a[1:], v)

def CloudFormationRandomName():
    return ''.join(random.choice(string.ascii_uppercase + string.ascii_lowercase + string.digits) for x in range(12))
