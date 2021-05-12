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

import json
import os

PREFIX = 'Boto3::'

LAMBDA_ARN = os.environ['LAMBDA_ARN']

def handle_template(request_id, template):
    for name, resource in template.get('Resources', {}).items():
        if resource['Type'].startswith(PREFIX):
            default_mode = ['Create', 'Update']
            if resource.get('Properties', {}).get('_DeleteAction', '') != '':
                default_mode.append('Delete')
            resource.update({
                'Type': 'Custom::Boto3',
                'Version': '1.0',
                'Properties': {
                    'ServiceToken': LAMBDA_ARN,
                    'Mode': resource.get('Mode', default_mode),
                    'Action': resource['Type'][len(PREFIX):],
                    'Properties': resource.get('Properties', {})
                }
            })

            if 'Mode' in resource:
                del resource['Mode']

    return template

def handler(event, context):
    print(json.dumps(event))

    fragment = event['fragment']
    status = 'success'

    try:
        fragment = handle_template(event['requestId'], event['fragment'])
    except Exception:
        status = 'failure'

    return {
        'requestId': event['requestId'],
        'status': status,
        'fragment': fragment
    }
