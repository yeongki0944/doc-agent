terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Region is set here; profile is injected via AWS_PROFILE env var at runtime.
provider "aws" {
  region  = "ap-northeast-2"
  profile = "mzadmin"
}
