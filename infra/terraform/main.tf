# ---------------------------------------------------------------------------
# Data Sources
# ---------------------------------------------------------------------------

# Resolves AZ names at plan time from the configured region,
# so we never hardcode "ca-central-1a" etc. into the config.
data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, var.az_count)

  # Carve /24 blocks out of the VPC CIDR.
  # private: 10.0.1.0/24, 10.0.2.0/24, ...
  # public:  10.0.101.0/24, 10.0.102.0/24, ...
  private_subnets = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, i + 1)]
  public_subnets  = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, i + 101)]
}

# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${var.cluster_name}-vpc"
  cidr = var.vpc_cidr

  azs             = local.azs
  private_subnets = local.private_subnets
  public_subnets  = local.public_subnets

  enable_nat_gateway   = true
  single_nat_gateway   = true  # one NAT GW instead of per-AZ; ~$30/day saving; fine for demo
  enable_dns_hostnames = true

  # Required by EKS for external and internal load balancer discovery.
  public_subnet_tags = {
    "kubernetes.io/role/elb" = "1"
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = "1"
  }

  tags = var.tags
}

# ---------------------------------------------------------------------------
# EKS Cluster
# ---------------------------------------------------------------------------

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = var.cluster_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets # nodes live in private subnets

  # Allows kubectl access from a local machine.
  # In production, restrict cluster_endpoint_public_access_cidrs to a VPN CIDR.
  cluster_endpoint_public_access = true

  # Grants the IAM identity running Terraform cluster-admin via EKS access entry.
  # Required in module v20+ (access entries replace the legacy aws-auth ConfigMap).
  enable_cluster_creator_admin_permissions = true

  eks_managed_node_groups = {
    runway-workers = {
      instance_types = [var.node_instance_type]
      min_size       = var.node_min_count
      max_size       = var.node_max_count
      desired_size   = var.node_desired_count

      labels = {
        role = "worker"
      }
    }
  }

  tags = var.tags
}
