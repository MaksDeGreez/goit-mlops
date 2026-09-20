# Module `vpc`

Wraps `terraform-aws-modules/vpc/aws` (~> 6.0) with the settings this project
needs: two availability zones, one public and one private subnet in each, and a
**single** NAT gateway to keep the cost down.

Nodes run in the private subnets. The public subnets only hold the NAT gateway.

Outputs: `vpc_id`, `vpc_cidr_block`, `private_subnets`, `public_subnets`, `azs`.
