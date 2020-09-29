# -*- coding: utf-8 -*-
#
# stack_set_resource.py
#
# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
##################################################################################################
"""
StackSet via CloudFormation
"""

# Next ToDo:
# Allow for stack Retention

import os
from time import sleep

import boto3
from botocore.exceptions import ClientError

import crhelper

# initialise logger
logger = crhelper.log_config({"RequestId": "CONTAINER_INIT"})
logger.info('Logging configured')
# set global to track init failures
init_failed = False

try:
    # Place initialization code here
    logger.info("Container initialization completed")
except Exception as exception:
    logger.error(exception, exc_info=True)
    init_failed = exception


def get_stack_from_arn(arn):
    # Given the ARN of a CloudFormation stack, return the stack name
    (arn, partion, service, region, account, resourcepart) = arn.split(':', 5)
    if ':' in resourcepart:
        (resourcetype, resource) = resourcepart.split(':')
    elif '/' in resourcepart:
        resourceparts = resourcepart.split('/')
        resource = resourceparts[1]
    else:
        resource = resourcepart
    return resource


def change_requires_update(attributes, old_values, current_values):
    # Given a list of attributes, compare the old and new values to see if
    # there's been a change.
    for attribute in attributes:
        if (attribute not in old_values) and (attribute in current_values):
            logger.debug("New value for {}: {}".format(attribute, current_values[attribute]))
            return True
        if (attribute in old_values) and (attribute not in current_values):
            logger.debug("Value removed for {}: {}".format(attribute, old_values[attribute]))
            return True
        if (attribute in old_values) and (attribute in current_values):
            logger.debug("Evaluating {}: {} vs. {}".format(attribute, current_values[attribute], old_values[attribute]))
            if current_values[attribute] != old_values[attribute]:
                return True
    return False


def convert_ops_prefs(ops_prefs):
    # CloudFormation parameters are all strings.  We need to convert numeric
    # values in the ops_prefs JSON object to ints before we can call the API
    logger.info("Converting Operation Preferences values")
    converted_ops_prefs = {}
    needs_conversion = set(
        ['FailureToleranceCount', 'FailureTolerancePercentage', 'MaxConcurrentCount', 'MaxConcurrentPercentage'])
    for key, value in ops_prefs.items():
        logger.debug("Evaluating {} : {}".format(key, value))
        if key in needs_conversion:
            logger.debug("Converting {}".format(key))
            converted_ops_prefs[key] = int(value)
        elif key == 'RegionOrder':
            converted_ops_prefs['RegionOrder'] = value
        else:
            logger.warning("Warning: Skipping unknown key: {} in Operation Preferences".format(key))
    return converted_ops_prefs


def expand_tags(tags):
    # We get the Tags as a list of key, value pairs, but CloudFormation needs
    # them exploded out to Key: key, Value: value.
    tags_array = []
    for tag in tags:
        logger.debug(tag)
        key, value = list(tag.items())[0]
        tags_array.append({'Key': key, 'Value': value})
    return tags_array


def expand_parameters(params):
    # We get the Parameters as a list of key, value pairs, but CloudFormation
    # needs them exploded out to ParameterKey: key, ParameterValue: value.
    params_array = []
    for param in params:
        logger.debug(param)
        key, value = list(param.items())[0]
        params_array.append({'ParameterKey': key, 'ParameterValue': value})
    return params_array


def flatten_stacks(stack_instances):
    # Stack instances are defined across accounts and regions + parameter
    # overrides.  We want to expand all combinations before we take action.
    flat_stacks = {}
    for instance in stack_instances:
        for account in instance['Accounts']:
            for region in instance['Regions']:
                account_region = "{}/{}".format(account, region)
                if account_region in flat_stacks:
                    raise Exception("{} / {} is defined multiple times".format(account, region))
                if 'ParameterOverrides' in instance:
                    flat_stacks[account_region] = instance['ParameterOverrides']
                else:
                    flat_stacks[account_region] = []
    return flat_stacks


def group_by_account(instance_set, flat_stacks):
    # Group regions by account and overrides
    grouped_accounts = {}
    for instance in instance_set:
        account, region = instance.split('/')
        if account in grouped_accounts:
            if flat_stacks[instance] == grouped_accounts[account]['overrides']:
                grouped_accounts[account]['regions'].append(region)
            else:
                raise Exception("The overrides didn't match account group for {}".format(instance))
        else:
            grouped_accounts[account] = {'regions': [region],
                                         'overrides': flat_stacks[instance]}
    return grouped_accounts


def aggregate_instances(account_list, flat_stacks):
    # First group regions by account and overrides
    accounts = group_by_account(account_list, flat_stacks)

    # Aggregate accounts into instances with similar regions to reduce number
    # of API calls
    instances = []
    while accounts.keys():
        aggregated_accounts = []
        (source_account, values) = accounts.popitem()
        for account in accounts:
            if accounts[account] == values:
                aggregated_accounts.append(account)
        for account in aggregated_accounts:
            accounts.pop(account)
        aggregated_accounts.append(source_account)
        instance = {'accounts': aggregated_accounts,
                    'regions': values['regions'],
                    'overrides': values['overrides']}
        instances.append(instance)
    logger.debug(instances)
    return instances


def create_stacks(set_region, set_name, accts, regions, param_overrides,
                  ops_prefs):
    # Wrapper for create_stack_instances
    sleep_time = 15
    retries = 60
    this_try = 0

    logger.info("Creating stack instances with op prefs {}".format(ops_prefs))
    logger.debug("StackSetName: {}, Accounts: {}, Regions: {}, ParameterOverrides: {}".format(
        set_name, accts, regions, param_overrides))

    while True:
        try:
            client = boto3.client('cloudformation', region_name=set_region)
            response = client.create_stack_instances(
                StackSetName=set_name,
                Accounts=accts,
                Regions=regions,
                ParameterOverrides=param_overrides,
                OperationPreferences=ops_prefs,
                # OperationId='string'
            )
            return response
        except ClientError as e:
            if e.response['Error']['Code'] == 'OperationInProgressException':
                this_try += 1
                if this_try == retries:
                    logger.warning("Failed to create stack instances after {} tries".format(this_try))
                    raise Exception("Error creating stack instances: {}".format(e))
                else:
                    logger.warning(
                        "Create stack instances operation in progress for {} in {}. Sleeping for {} seconds.".format(
                            set_name, set_region, sleep_time))
                    sleep(sleep_time)
                    continue
            elif e.response['Error']['Code'] == 'Throttling':
                this_try += 1
                if this_try == retries:
                    logger.warning("Failed to create stack instances after {} tries".format(this_try))
                    raise Exception("Error creating stack instances: {}".format(e))
                else:
                    logger.warning(
                        "Throttling exception encountered while creating stack instances. Backing off and retyring. " 
                        "Sleeping for {} seconds.".format(sleep_time))
                    sleep(sleep_time)
                    continue
            elif e.response['Error']['Code'] == 'StackSetNotFoundException':
                raise Exception(
                    "No StackSet matching {} found in {}. You must create before creating stack instances.".format(
                        set_name, set_region))
            else:
                raise Exception("Error creating stack instances: {}".format(e))


def update_stacks(set_region, set_name, accts, regions, param_overrides, ops_prefs):
    # Wrapper for update_stack_instances
    sleep_time = 15
    retries = 60
    this_try = 0

    logger.info("Updating stack instances with op prefs {}".format(ops_prefs))

    # UpdateStackInstance only allows stackSetName, not stackSetId,
    # so we need to truncate.
    (set_name, uid) = set_name.split(':')
    logger.debug("StackSetName: {}, Accounts: {}, Regions: {}, ParameterOverrides: {}".format(
        set_name, accts, regions, param_overrides))

    while True:
        try:
            client = boto3.client('cloudformation', region_name=set_region)
            response = client.update_stack_instances(
                StackSetName=set_name,
                Accounts=accts,
                Regions=regions,
                ParameterOverrides=param_overrides,
                OperationPreferences=ops_prefs,
                # OperationId='string'
            )
            return response
        except ClientError as e:
            if e.response['Error']['Code'] == 'OperationInProgressException':
                this_try += 1
                if this_try == retries:
                    logger.warning("Failed to update stack instances after {} tries".format(this_try))
                    raise Exception("Error updating stack instances: {}".format(e))
                else:
                    logger.warning(
                        "Update stack instances operation in progress for {} in {}. Sleeping for {} seconds.".format(
                            set_name, set_region, sleep_time))
                    sleep(sleep_time)
                    continue
            elif e.response['Error']['Code'] == 'Throttling':
                this_try += 1
                if this_try == retries:
                    logger.warning("Failed to update stack instances after {} tries".format(this_try))
                    raise Exception("Error updating stack instances: {}".format(e))
                else:
                    logger.warning(
                        "Throttling exception encountered while updating stack instances. Backing off and retyring. " 
                        "Sleeping for {} seconds.".format(sleep_time))
                    sleep(sleep_time)
                    continue
            elif e.response['Error']['Code'] == 'StackSetNotFoundException':
                raise Exception(
                    "No StackSet matching {} found in {}. You must create before updating stack instances.".format(
                        set_name, set_region))
            else:
                raise Exception("Unexpected error: {}".format(e))


def delete_stacks(set_region, set_id, accts, regions, ops_prefs):
    # Wrapper for delete_stack_instances
    sleep_time = 15
    retries = 60
    this_try = 0

    logger.info("Deleting stack instances with op prefs {}".format(ops_prefs))
    logger.debug("StackSetName: {}, Accounts: {}, Regions: {}".format(set_id, accts, regions))

    while True:
        try:
            client = boto3.client('cloudformation', region_name=set_region)
            response = client.delete_stack_instances(
                StackSetName=set_id,
                Accounts=accts,
                Regions=regions,
                OperationPreferences=ops_prefs,
                RetainStacks=False,
                # OperationId='string'
            )
            return response
        except ClientError as e:
            if e.response['Error']['Code'] == 'OperationInProgressException':
                this_try += 1
                if this_try == retries:
                    logger.warning("Failed to delete stack instances after {} tries".format(this_try))
                    raise Exception("Error deleting stack instances: {}".format(e))
                else:
                    logger.warning(
                        "Delete stack instances operation in progress for {} in {}. Sleeping for {} seconds.".format(
                            set_id, set_region, sleep_time))
                    sleep(sleep_time)
                    continue
            elif e.response['Error']['Code'] == 'Throttling':
                this_try += 1
                if this_try == retries:
                    logger.warning("Failed to delete stack instances after {} tries".format(this_try))
                    raise Exception("Error deleting stack instances: {}".format(e))
                else:
                    logger.warning(
                        "Throttling exception encountered while deleting stack instances. Backing off and retyring. " 
                        "Sleeping for {} seconds.".format(sleep_time))
                    sleep(sleep_time)
                    continue
            elif e.response['Error']['Code'] == 'StackSetNotFoundException':
                return "No StackSet matching {} found in {}. You must create before deleting stack instances.".format(
                    set_id, set_region)
            else:
                return "Unexpected error: {}".format(e)


def update_stack_set(set_region, set_id, set_description, set_template,
                     set_parameters, set_capabilities, set_tags, ops_prefs,
                     set_admin_role_arn, set_exec_role_name):
    # Set up for retries
    sleep_time = 15
    retries = 60
    this_try = 0

    client = boto3.client('cloudformation', region_name=set_region)

    # Retry loop
    while True:
        try:
            response = client.update_stack_set(
                StackSetName=set_id,
                Description=set_description,
                TemplateURL=set_template,
                # TemplateBody='string',
                # UsePreviousTemplate=True|False,
                Parameters=set_parameters,
                Capabilities=set_capabilities,
                Tags=set_tags,
                OperationPreferences=ops_prefs,
                # OperationId='string'
                AdministrationRoleARN=set_admin_role_arn,
                ExecutionRoleName=set_exec_role_name
            )
            if response['ResponseMetadata']['HTTPStatusCode'] == 200:
                return set_id
            else:
                raise Exception("HTTP Error: {}".format(response))
        except ClientError as e:
            if e.response['Error']['Code'] == 'OperationInProgressException':
                this_try += 1
                if this_try == retries:
                    raise Exception("Failed to update StackSet after {} tries.".format(this_try))
                else:
                    logger.warning(
                        "Update StackSet operation in progress for {}. Sleeping for {} seconds.".format(
                            set_id, sleep_time))
                    sleep(sleep_time)
                    continue
            elif e.response['Error']['Code'] == 'StackSetNotEmptyException':
                raise Exception("There are still stacks in set {}. You must delete these first.".format(set_id))
            else:
                raise Exception("Unexpected error: {}".format(e))


def create(event, context):
    """
    Handle StackSetResource CREATE events.

    Create StackSet resource and any stack instances specified in the template.
    """
    # pylint: disable=unused-argument
    # Collect everything we need to create the stack set

    # optional
    if 'StackSetName' in event['ResourceProperties']:
        set_name = event['ResourceProperties']['StackSetName']
    else:
        set_name = "{}-{}".format(get_stack_from_arn(event['StackId']), event['LogicalResourceId'])

    if 'StackSetDescription' in event['ResourceProperties']:
        set_description = event['ResourceProperties']['StackSetDescription']
    else:
        set_description = "This StackSet belongs to the CloudFormation stack {}.".format(
            get_stack_from_arn(event['StackId']))

    if 'OperationPreferences' in event['ResourceProperties']:
        set_ops_prefs = convert_ops_prefs(event['ResourceProperties']['OperationPreferences'])
    else:
        set_ops_prefs = {}

    if 'Tags' in event['ResourceProperties']:
        set_tags = expand_tags(event['ResourceProperties']['Tags'])
    else:
        set_tags = []

    if 'Capabilities' in event['ResourceProperties']:
        set_capabilities = event['ResourceProperties']['Capabilities']
    else:
        set_capabilities = ''

    if 'AdministrationRoleARN' in event['ResourceProperties']:
        set_admin_role_arn = event['ResourceProperties']['AdministrationRoleARN']
    else:
        set_admin_role_arn = ''

    if 'ExecutionRoleName' in event['ResourceProperties']:
        set_exec_role_name = event['ResourceProperties']['ExecutionRoleName']
    else:
        set_exec_role_name = ''

    if 'Parameters' in event['ResourceProperties']:
        set_parameters = expand_parameters(event['ResourceProperties']['Parameters'])
    else:
        set_parameters = []

    # Required
    set_template = event['ResourceProperties']['TemplateURL']

    # Create the StackSet
    try:
        client = boto3.client('cloudformation',
                              region_name=os.environ['AWS_REGION'])
        response = client.create_stack_set(
            StackSetName=set_name,
            Description=set_description,
            TemplateURL=set_template,
            # TemplateBody='string',
            Parameters=set_parameters,
            Capabilities=set_capabilities,
            Tags=set_tags,
            AdministrationRoleARN=set_admin_role_arn,
            ExecutionRoleName=set_exec_role_name
            # ClientRequestToken='string'
        )
        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            set_id = response['StackSetId']
        else:
            raise Exception("HTTP Error: {}".format(response))
    except ClientError as e:
        if e.response['Error']['Code'] == 'NameAlreadyExistsException':
            raise Exception("A StackSet called {} already exists.".format(set_name))
        else:
            raise Exception("Unexpected error: {}".format(e))
    logger.info("Created StackSet: {}".format(set_id))
    physical_resource_id = set_id

    # Deploy stack to accounts and regions if defined.
    # We're going to switch from a single stack instance definition to an array
    # of stack instance objects.  This will allow more complex stack structures
    # across accounts and regions, including parameter overrides

    # Iterate over stack instances
    for instance in event['ResourceProperties']['StackInstances']:
        if 'ParameterOverrides' in instance:
            param_overrides = expand_parameters(instance['ParameterOverrides'])
        else:
            param_overrides = []
        logger.debug("Stack Instance: Regions: {} : Accounts: {} : Parameters: {}".format(
            instance['Regions'], instance['Accounts'], param_overrides))

        # Make sure every stack instance defines both a list of accounts and
        # a list of regions
        if instance['Regions'][0] != '' and instance['Accounts'][0] == '':
            raise Exception("You must specify at least one account with a list of regions.")
        elif instance['Regions'][0] == '' and instance['Accounts'][0] != '':
            raise Exception("You must specify at least one region with a list of accounts.")
        elif instance['Regions'][0] != '' and instance['Accounts'][0] != '':
            logger.info("Creating stacks in accounts: %s and regions: {}".format(
                instance['Accounts'], instance['Regions']))
            response = create_stacks(
                os.environ['AWS_REGION'],
                set_id,
                instance['Accounts'],
                instance['Regions'],
                param_overrides,
                set_ops_prefs
            )
            logger.debug(response)
    response_data = {}
    return physical_resource_id, response_data


def update(event, context):
    """
    Handle StackSetResource UPDATE events.

    Update StackSet resource and/or any stack instances specified in the template.
    """
    # Collect everything we need to update the stack set
    set_id = event['PhysicalResourceId']

    # Process the Operational Preferences (if any)
    if 'OperationPreferences' in event['ResourceProperties']:
        set_ops_prefs = convert_ops_prefs(event['ResourceProperties']['OperationPreferences'])
    else:
        set_ops_prefs = {}
    logger.debug("OperationPreferences: {}".format(set_ops_prefs))

    # Circumstances under which we update the StackSet itself
    stack_set_attributes = [
        'TemplateURL',
        'Parameters',
        'Tags',
        'Capabilities',
        'StackSetDescription'
    ]
    stack_set_needs_update = change_requires_update(stack_set_attributes,
                                                    event['OldResourceProperties'],
                                                    event['ResourceProperties'])

    if stack_set_needs_update:
        logger.info("Changes impacting StackSet detected")

        # Optional properties
        logger.info("Evaluating optional properties")
        if 'StackSetDescription' in event['ResourceProperties']:
            set_description = event['ResourceProperties']['StackSetDescription']
        elif 'StackSetDescription' in event['OldResourceProperties']:
            set_description = event['OldResourceProperties']['StackSetDescription']
        else:
            set_description = "This StackSet belongs to the CloudFormation stack {}.".format(
                get_stack_from_arn(event['StackId']))
        logger.debug("StackSetDescription: {}".format(set_description))

        if 'Capabilities' in event['ResourceProperties']:
            set_capabilities = event['ResourceProperties']['Capabilities']
        elif 'Capabilities' in event['OldResourceProperties']:
            set_capabilities = event['OldResourceProperties']['Capabilities']
        else:
            set_capabilities = []
        logger.debug("Capabilities: {}".format(set_capabilities))

        if 'Tags' in event['ResourceProperties']:
            set_tags = expand_tags(event['ResourceProperties']['Tags'])
        elif 'Tags' in event['OldResourceProperties']:
            set_tags = expand_tags(event['OldResourceProperties']['Tags'])
        else:
            set_tags = []
        logger.debug("Tags: {}".format(set_tags))

        if 'Parameters' in event['ResourceProperties']:
            set_parameters = expand_parameters(event['ResourceProperties']['Parameters'])
        elif 'Parameters' in event['OldResourceProperties']:
            set_parameters = expand_parameters(event['OldResourceProperties']['Parameters'])
        else:
            set_parameters = []
        logger.debug("Parameters: {}".format(set_parameters))

        # Required properties
        logger.info("Evaluating required properties")
        if 'TemplateURL' in event['ResourceProperties']:
            set_template = event['ResourceProperties']['TemplateURL']
        elif 'TemplateURL' in event['OldResourceProperties']:
            set_template = event['OldResourceProperties']['TemplateURL']
        else:
            raise Exception('Template URL not found during update event')
        logger.debug("TemplateURL: {}".format(set_template))

        if 'AdministrationRoleARN' in event['ResourceProperties']:
            set_admin_role_arn = event['ResourceProperties']['AdministrationRoleARN']
        else:
            set_admin_role_arn = ''

        if 'ExecutionRoleName' in event['ResourceProperties']:
            set_exec_role_name = event['ResourceProperties']['ExecutionRoleName']
        else:
            set_exec_role_name = ''

        # Update the StackSet
        logger.info("Updating StackSet resource {}".format(set_id))
        update_stack_set(os.environ['AWS_REGION'], set_id, set_description,
                         set_template, set_parameters, set_capabilities,
                         set_tags, set_ops_prefs, set_admin_role_arn, set_exec_role_name)

    # Now, look for changes to stack instances
    logger.info("Evaluating stack instances")

    # Flatten all the account/region tuples to compare differences
    if 'StackInstances' in event['ResourceProperties']:
        new_stacks = flatten_stacks(event['ResourceProperties']['StackInstances'])
    else:
        new_stacks = []

    if 'StackInstances' in event['OldResourceProperties']:
        old_stacks = flatten_stacks(event['OldResourceProperties']['StackInstances'])
    else:
        old_stacks = []

    # Evaluate all differences we need to handle
    to_add = list(set(new_stacks) - set(old_stacks))
    to_delete = list(set(old_stacks) - set(new_stacks))
    to_compare = list(set(old_stacks).intersection(new_stacks))

    # Launch all new stack instances
    if to_add:
        logger.info("Adding stack instances:  {}".format(to_add))

        # Aggregate accounts with similar regions to reduce number of API calls
        add_instances = aggregate_instances(to_add, new_stacks)

        # Add stack instances
        for instance in add_instances:
            logger.debug("Add aggregated accounts: {} and regions: {} and overrides: {}".format(
                instance['accounts'], instance['regions'], instance['overrides']))
            if 'overrides' in instance:
                param_overrides = expand_parameters(instance['overrides'])
            else:
                param_overrides = []

            response = create_stacks(
                os.environ['AWS_REGION'],
                set_id,
                instance['accounts'],
                instance['regions'],
                param_overrides,
                set_ops_prefs
            )
            logger.debug(response)

    # Delete all old stack instances
    if to_delete:
        logger.info("Deleting stack instances: {}".format(to_delete))

        # Aggregate accounts with similar regions to reduce number of API calls
        delete_instances = aggregate_instances(to_delete, old_stacks)

        # Add stack instances
        for instance in delete_instances:
            logger.debug("Delete aggregated accounts: {} and regions: {}".format(
                instance['accounts'], instance['regions']))
            response = delete_stacks(
                os.environ['AWS_REGION'],
                set_id,
                instance['accounts'],
                instance['regions'],
                set_ops_prefs
            )
            logger.debug(response)

    # Determine if any existing instances need to be updated
    if to_compare:
        logger.info("Examining stack instances: {}".format(to_compare))

        # Update any stacks in both lists, but with new overrides
        to_update = []
        for instance in to_compare:
            if old_stacks[instance] == new_stacks[instance]:
                logger.debug("{}: SAME!".format(instance))
            else:
                logger.debug("{}: DIFFERENT!".format(instance))
                to_update.append(instance)

        # Aggregate accounts with similar regions to reduce number of API calls
        update_instances = aggregate_instances(to_update, new_stacks)
        for instance in update_instances:
            logger.debug("Update aggregated accounts: {} and regions: {} with overrides {}".format(
                instance['accounts'], instance['regions'], instance['overrides']))
            if 'overrides' in instance:
                param_overrides = expand_parameters(instance['overrides'])
            else:
                param_overrides = []

            response = update_stacks(
                os.environ['AWS_REGION'],
                set_id,
                instance['accounts'],
                instance['regions'],
                param_overrides,
                set_ops_prefs
            )
            logger.debug(response)

    physical_resource_id = set_id
    response_data = {}
    return physical_resource_id, response_data


def delete(event, context):
    """
    Handle StackSetResource DELETE events.

    Delete StackSet resource and any stack instances specified in the template.
    """
    # Set up for retries
    sleep_time = 15
    retries = 60
    this_try = 0

    # Collect everything we need to delete the stack set
    set_id = event['PhysicalResourceId']

    if set_id == 'NONE':
        # This is a rollback from a failed create.  Nothing to do.
        return

    # First, we need to tear down all of the stacks associated with this
    # stack set
    if 'StackInstances' in event['ResourceProperties']:
        # Check for Operation Preferences
        if 'OperationPreferences' in event['ResourceProperties']:
            set_ops_prefs = convert_ops_prefs(event['ResourceProperties']['OperationPreferences'])
        else:
            set_ops_prefs = {}

        # Iterate over stack instances
        for instance in event['ResourceProperties']['StackInstances']:
            logger.debug("Stack Instance: Regions: {} : Accounts: {}".format(instance['Regions'], instance['Accounts']))

            logger.info("Removing existing stacks from stack set {}".format(set_id))

            response = delete_stacks(
                os.environ['AWS_REGION'],
                set_id,
                instance['Accounts'],
                instance['Regions'],
                set_ops_prefs
            )
            logger.debug(response)

    client = boto3.client('cloudformation', region_name=os.environ['AWS_REGION'])

    # Retry loop
    logger.info('Deleting stack set')
    while True:
        try:
            response = client.delete_stack_set(
                StackSetName=set_id
            )
            if response['ResponseMetadata']['HTTPStatusCode'] == 200:
                return
            else:
                raise Exception("HTTP Error: {}".format(response))
        except ClientError as e:
            if e.response['Error']['Code'] == 'OperationInProgressException':
                this_try += 1
                if this_try == retries:
                    raise Exception("Failed to delete StackSet after {} tries.".format(this_try))
                else:
                    logger.warning(
                        "Delete StackSet operation in progress for {}. Sleeping for {} seconds.".format(
                            set_id, sleep_time))
                    sleep(sleep_time)
                    continue
            elif e.response['Error']['Code'] == 'StackSetNotEmptyException':
                raise Exception("There are still stacks in set {}. You must delete these first.".format(set_id))
            else:
                raise Exception("Unexpected error: {}".format(e))


def handler(event, context):
    """
    Main handler function, passes off it's work to crhelper's cfn_handler
    """
    # update the logger with event info
    global logger
    logger = crhelper.log_config(event)
    return crhelper.cfn_handler(event, context, create, update, delete, logger, init_failed)
