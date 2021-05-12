# How to install and use the Boto3 macro in your AWS account

The `Boto3` macro adds the ability to create CloudFormation resources that represent operations performed by [boto3](http://boto3.readthedocs.io/). Each `Boto3` resource represents one function call.

A typical use case for this macro might be, for example, to provide some basic configuration of resources.

## Deploying

1. You will need an S3 bucket to store the CloudFormation artifacts:
    * If you don't have one already, create one with `aws s3 mb s3://<bucket name>`

2. Package the CloudFormation template. The provided template uses [the AWS Serverless Application Model](https://aws.amazon.com/about-aws/whats-new/2016/11/introducing-the-aws-serverless-application-model/) so must be transformed before you can deploy it.

    ```shell
    aws cloudformation package \
        --template-file macro.template \
        --s3-bucket <your bucket name here> \
        --output-template-file packaged.template
    ```

3. Deploy the packaged CloudFormation template to a CloudFormation stack:

    ```shell
    aws cloudformation deploy \
        --stack-name boto3-macro \
        --template-file packaged.template \
        --capabilities CAPABILITY_IAM
    ```

4. To test out the macro's capabilities, try launching the provided example template:

    ```shell
    aws cloudformation deploy \
        --stack-name boto3-macro-example \
        --template-file example.template
    ```

## Usage

To make use of the macro, add `Transform: Boto3` to the top level of your CloudFormation template.

Here is a trivial example template that adds a readme file to a new CodeCommit repository:

```yaml
Transform: Boto3
Resources:
  Repo:
    Type: AWS::CodeCommit::Repository
    Properties:
      RepositoryName: my-repo

  AddReadme:
    Type: Boto3::CodeCommit.put_file
    Mode: Create
    Properties:
      repositoryName: !GetAtt Repo.Name
      branchName: master
      fileContent: "Hello, world!"
      filePath: README.md
      commitMessage: Add a readme file
      name: CloudFormation
```

## Features

### Resource type

The resource `Type` is used to identify a [boto3 client](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/clients.html) and the method of that client to execute.

The `Type` must start with `Boto3::` and be followed by the name of a client, a `.` and finally the name of a method.

The client name will be converted to lower case so that you can use resource names that look similar to other CloudFormation resource types.

Examples:
* `Boto3::CodeCommit.put_file`
* `Boto3::IAM.put_user_permissions_boundary`
* `Boto3::EC2.create_snapshot`

### Resource mode

The resource may contain a `Mode` property which specifies whether the boto3 call should be made on `Create`, `Update`, `Delete` or any combination of those.

The `Mode` may either be a string or a list of strings. For example:

* `Mode: Create`
* `Mode: Delete`
* `Mode: [Create, Update]`

If not supplied this property will default to `[Create, Update]`.

### Resource properties

The `Properties` of the resource will be passed to the specified boto3 method as arguments. The name of each property needs to match those defined in the `Boto3` library, they are therefore case sensitive.

#### Special properties

Some properties enable special functionality when used. They are designed to enhance the capabilties of the Macro to mimic standard CloudFormation resources. The use of these enables resources to the be created by CloudFormation that are not yet supported within CloudFormation itself but are supported in `Boto3`

* _CustomName - `String` (optional)

  This property is used to mimic the automatic naming capability of supported CloudFormation resources. The value supplied is the name of the `Boto3` property that you wish to be populated with a unique randomly generated name. If used the corresponding property must not be supplied. The name generated will be of the form:

  `<StackName>-<LogicalResourceId>-<A random 12 alphumermic string>`

* _Ref - `String` (optional*)

  This property is used to set the value of the `PhysicalResourceId` of the created resource. It therefore allows the `Ref` function be used on the resource to retrieve it.

  This property takes a [jmespath](https://jmespath.org/) string expression which is applied to the response of the `Boto3` function to extract the required value.

  &ast;This property becomes mandatory if either of the `_UpdateAction` or `_DeleteAction` special properties are supplied.

  If using this in conjunction with either `_UpdateAction` or `_DeleteAction` special properties then the property defined by this property will be populated with the value of the `PhysicalResourceId` so that Update and Delete actions on the resource can be carrried out.

* _GetAtt - `Dict` (optional)

  This property is used in a similar way to the `_Ref` property but intead of populating the value of the `Ref` CloudFormation function call it allows the setting of the values returned by the `Fn::GetAtt` function.

  This property takes a dict of string and [jmespath](https://jmespath.org/) string expression key pairs, which are applied to the response of the `Boto3` function to extract the required value.

* _UpdateAction - `Dict` (optional)

  * Method - `String` (mandatory)
  * _Ref - `String` (optional)

  This property is used to override the `Boto3` function that will be called in case of an `Update` action on the stack. Using this means it it possible to define a single resource, with different actions, in the CloudFormation template for multiple actions (Create, Update and Delete).

  This property is useful since `Boto3` has different function names for Create, Update (if possible) and Delete actions on an AWS resource. Without this property you would previously have had to define multple resources using different `Mode` property values.
  
  The `Method` sub-property value is the name of the `Boto3` function to be called on Update actions. It is therefore mandatory if the parent `_UpdateAction` property is used. The `_Ref` property is optional. It is used to define which field, in the `Boto3` call, the macro will populate with the `PhysicalResourceId` supplied by the `Update` request.

* _DeleteAction - `Dict` (optional)

  * Method - `String` (mandatory)
  * _Ref - `String` (optional)

  This property is used to override the `Boto3` function that will be called in case of a `Delete` action on the stack. Using this means it it possible to define a single resource, with different actions, in the CloudFormation template for multiple actions (Create, Update and Delete).

  This property is useful since `Boto3` has different function names for Create, Update (if possible) and Delete actions on an AWS resource. Without this property you would previously have had to define multple resources using different `Mode` property values.
  
  The `Method` sub-property value is the name of the `Boto3` function to be called on Delete actions. It is therefore mandatory if the parent `_DeleteAction` property is used. The `_Ref` property is optional. It is used to define which field, in the `Boto3` call, the macro will populate with the `PhysicalResourceId` supplied by the `Delete` request.

  Supplying the `_DeleteAction` property and not supplying a `Mode` property value will change the default value of `Mode` to be `[Create,Update,Delete]` since by using the `_DeleteAction` property implies you wish to use the Delete `Mode`.

There are examples in the section below of how each of these special properties can be used.

### Controlling the order of execution

You can use the standard CloudFormation property `DependsOn` when you need to ensure that your `Boto3` resources are executed in the correct order.

## Examples


The following resource:

```yaml
ChangeBinaryTypes:
  Type: Boto3::CloudFormation.execute_change_set
  Mode: [Create, Update]
  Properties:
    ChangeSetName: !Ref ChangeSet
    StackName: !Ref Stack
```

will result in running the equivalent of the following:

```python
boto3.client("cloudformation").execute_change_set(ChangeSetName=<value of ChangeSet>, StackName=<value of StackName>)
```

when the stack is created or updated.


The next example show how to use the special properties to create a CloudFormation resource that is not currenntly (at time of writing) possible to be created using standard CloudFormation. This resource is an ECS Blue/Green Code Deploy Deployment Group. Please note this is a code snippet since this resource would not normally exist on it's own in a CloudFormation template but none the less this below example should show you how the `Boto3` macro could greatly simplify the process of creating resources that are not currently supported in native CloudFormation.

***Stack Name: SampleStack***
```yaml
...
  CodeDeployDeploymentGroup:
    Type: Boto3::codedeploy.create_deployment_group
    Mode: [Create, Update, Delete]
    Properties:
      #Special Properties
      _CustomName: deploymentGroupName
      _Ref: deploymentGroupName
      _GetAtt:
        Id: deploymentGroupId
      _UpdateAction:
        Method: update_deployment_group
        _Ref: currentDeploymentGroupName
      _DeleteAction:
        Method: delete_deployment_group
      #Standard properties as defined by the Boto3 definition of the create_deployment_group method
      applicationName: !Ref CodeDeployApplication
      deploymentConfigName: CodeDeployDefault.ECSAllAtOnce
      serviceRoleArn: !GetAtt CodeDeployRole.Arn
      autoRollbackConfiguration:
        enabled: True
        events:
          - DEPLOYMENT_FAILURE
          - DEPLOYMENT_STOP_ON_REQUEST
      deploymentStyle:
        deploymentType: BLUE_GREEN
        deploymentOption: WITH_TRAFFIC_CONTROL
      blueGreenDeploymentConfiguration:
        terminateBlueInstancesOnDeploymentSuccess:
          action: TERMINATE
          terminationWaitTimeInMinutes: 60
        deploymentReadyOption:
          actionOnTimeout: CONTINUE_DEPLOYMENT
          waitTimeInMinutes: 0
      loadBalancerInfo:
        targetGroupPairInfoList:
          - targetGroups:
              - name: !GetAtt TargetGroupBlue.TargetGroupName
              - name: !GetAtt TargetGroupGreen.TargetGroupName
            prodTrafficRoute:
              listenerArns:
                - !Ref Listener
      ecsServices:
        - clusterName: !Ref EcsCluster
          serviceName: !GetAtt EcsService.Name
...
```

the result will be an ECS Blue/Green CodeDeploy Deployment Group that can referenced further within the CloduFormation template in the following ways:

* `!Ref CodeDeployDeploymentGroup` will return the name that was generated automatically (`SampleStack-`<u>CodeDeployDeploymentGroup</u>`-A1B2C3D4E5F6`).
* `!GetAtt CodeDeployDeploymentGroup.Id` will return the deploymentGroupId value from the `boto3.client('codedeploy').create_deployment_group(...)` function call.

It can also be updated/deleted with a stack just like any other CloudFormation resource and the corresponding `Boto3` methods will be called to handle the required result.

## Author

[Steve Engledow](https://linkedin.com/in/stilvoid)  
Senior Solutions Builder  
Amazon Web Services
