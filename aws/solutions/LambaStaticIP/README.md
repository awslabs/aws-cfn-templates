# Join a Lambda Function to a VPC to obtain a Static IP

Cloudformation template that will create and join a Lambda function to a newly created VPC in order to obtain a fixed outgoing (Egress) IP address.

Template will invoke the following:

- Create a new VPC
- Create 2x Public Subnets
- Create 2x Private Subnets
- Create 2x Elastic IP Addresses
- Create 2x NAT Gateways
- Create an Internet Gateway
- Create 2x public subnet routing tables
- Create 2x private subnet routing tables
- Create a new lambda function
- Attach the lambda function to the newly created VPC