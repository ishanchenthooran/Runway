variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "ca-central-1" # Toronto; better locality than us-east-1
}

variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
  default     = "runway"
}

variable "cluster_version" {
  description = <<-EOT
    Kubernetes version for the EKS cluster.
    Check supported versions before applying:
    https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions.html
    ca-central-1 generally tracks the same release cadence as us-east-1.
  EOT
  type        = string
  default     = "1.29"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "az_count" {
  description = "Number of availability zones to use (resolved from the region at plan time via data source)"
  type        = number
  default     = 2
}

variable "node_instance_type" {
  description = "EC2 instance type for worker nodes. CPU-only; GPU nodes are out of scope for v1."
  type        = string
  default     = "t3.medium"
}

variable "node_desired_count" {
  description = "Desired number of worker nodes"
  type        = number
  default     = 2
}

variable "node_min_count" {
  description = "Minimum number of worker nodes"
  type        = number
  default     = 1
}

variable "node_max_count" {
  description = "Maximum number of worker nodes"
  type        = number
  default     = 3
}

variable "tags" {
  description = "Tags applied to all resources via provider default_tags"
  type        = map(string)
  default = {
    Project = "runway"
  }
}
