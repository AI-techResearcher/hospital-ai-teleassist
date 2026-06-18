# Terraform configuration for AWS infrastructure
terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  
  backend "s3" {
    bucket = "hospital-ai-terraform-state"
    key    = "infrastructure/terraform.tfstate"
    region = "us-east-1"
  }
}

provider "aws" {
  region = var.aws_region
  
  default_tags {
    tags = {
      Project     = "Hospital-AI-System"
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

# Variables
variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "production"
}

variable "domain_name" {
  description = "Domain name for the application"
  type        = string
}

variable "certificate_arn" {
  description = "ACM certificate ARN for HTTPS"
  type        = string
}

# VPC Configuration
resource "aws_vpc" "hospital_vpc" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  
  tags = {
    Name = "hospital-ai-vpc"
  }
}

resource "aws_internet_gateway" "hospital_igw" {
  vpc_id = aws_vpc.hospital_vpc.id
  
  tags = {
    Name = "hospital-ai-igw"
  }
}

# Public Subnets
resource "aws_subnet" "public_subnet_1" {
  vpc_id                  = aws_vpc.hospital_vpc.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true
  
  tags = {
    Name = "hospital-ai-public-1"
  }
}

resource "aws_subnet" "public_subnet_2" {
  vpc_id                  = aws_vpc.hospital_vpc.id
  cidr_block              = "10.0.2.0/24"
  availability_zone       = data.aws_availability_zones.available.names[1]
  map_public_ip_on_launch = true
  
  tags = {
    Name = "hospital-ai-public-2"
  }
}

# Private Subnets
resource "aws_subnet" "private_subnet_1" {
  vpc_id            = aws_vpc.hospital_vpc.id
  cidr_block        = "10.0.3.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
  
  tags = {
    Name = "hospital-ai-private-1"
  }
}

resource "aws_subnet" "private_subnet_2" {
  vpc_id            = aws_vpc.hospital_vpc.id
  cidr_block        = "10.0.4.0/24"
  availability_zone = data.aws_availability_zones.available.names[1]
  
  tags = {
    Name = "hospital-ai-private-2"
  }
}

# Route Tables
resource "aws_route_table" "public_rt" {
  vpc_id = aws_vpc.hospital_vpc.id
  
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.hospital_igw.id
  }
  
  tags = {
    Name = "hospital-ai-public-rt"
  }
}

resource "aws_route_table_association" "public_rta_1" {
  subnet_id      = aws_subnet.public_subnet_1.id
  route_table_id = aws_route_table.public_rt.id
}

resource "aws_route_table_association" "public_rta_2" {
  subnet_id      = aws_subnet.public_subnet_2.id
  route_table_id = aws_route_table.public_rt.id
}

# Security Groups
resource "aws_security_group" "alb_sg" {
  name_prefix = "hospital-alb-"
  vpc_id      = aws_vpc.hospital_vpc.id
  
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  tags = {
    Name = "hospital-ai-alb-sg"
  }
}

resource "aws_security_group" "ecs_sg" {
  name_prefix = "hospital-ecs-"
  vpc_id      = aws_vpc.hospital_vpc.id
  
  ingress {
    from_port       = 5050
    to_port         = 5050
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }
  
  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }
  
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  tags = {
    Name = "hospital-ai-ecs-sg"
  }
}

# Application Load Balancer
resource "aws_lb" "hospital_alb" {
  name               = "hospital-ai-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg.id]
  subnets           = [aws_subnet.public_subnet_1.id, aws_subnet.public_subnet_2.id]
  
  enable_deletion_protection = false
  
  tags = {
    Name = "hospital-ai-alb"
  }
}

# Target Groups
resource "aws_lb_target_group" "twilio_tg" {
  name     = "hospital-twilio-tg"
  port     = 5050
  protocol = "HTTP"
  vpc_id   = aws_vpc.hospital_vpc.id
  
  health_check {
    enabled             = true
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    path                = "/health"
    matcher             = "200"
  }
  
  tags = {
    Name = "hospital-twilio-tg"
  }
}

resource "aws_lb_target_group" "orchestrator_tg" {
  name     = "hospital-orchestrator-tg"
  port     = 8000
  protocol = "HTTP"
  vpc_id   = aws_vpc.hospital_vpc.id
  
  health_check {
    enabled             = true
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 10
    interval            = 30
    path                = "/health"
    matcher             = "200"
  }
  
  tags = {
    Name = "hospital-orchestrator-tg"
  }
}

# ALB Listeners
resource "aws_lb_listener" "hospital_https" {
  load_balancer_arn = aws_lb.hospital_alb.arn
  port              = "443"
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS-1-2-2017-01"
  certificate_arn   = var.certificate_arn
  
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.orchestrator_tg.arn
  }
}

resource "aws_lb_listener" "hospital_http" {
  load_balancer_arn = aws_lb.hospital_alb.arn
  port              = "80"
  protocol          = "HTTP"
  
  default_action {
    type = "redirect"
    
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# ALB Listener Rules for Twilio webhooks
resource "aws_lb_listener_rule" "twilio_webhooks" {
  listener_arn = aws_lb_listener.hospital_https.arn
  priority     = 100
  
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.twilio_tg.arn
  }
  
  condition {
    path_pattern {
      values = [
        "/incoming-call",
        "/outgoing-call",
        "/process-speech",
        "/no-input",
        "/end-call",
        "/hangup",
        "/media-stream",
        "/make-call"
      ]
    }
  }
}

# ECS Cluster
resource "aws_ecs_cluster" "hospital_cluster" {
  name = "hospital-ai-cluster"
  
  configuration {
    execute_command_configuration {
      logging = "OVERRIDE"
      
      log_configuration {
        cloud_watch_log_group_name = aws_cloudwatch_log_group.ecs_logs.name
      }
    }
  }
  
  tags = {
    Name = "hospital-ai-cluster"
  }
}

# CloudWatch Log Groups
resource "aws_cloudwatch_log_group" "ecs_logs" {
  name              = "/hospital-ai/ecs"
  retention_in_days = 14
  
  tags = {
    Name = "hospital-ai-logs"
  }
}

resource "aws_cloudwatch_log_group" "twilio_logs" {
  name              = "/hospital-ai/twilio-agent"
  retention_in_days = 14
  
  tags = {
    Name = "hospital-ai-twilio-logs"
  }
}

resource "aws_cloudwatch_log_group" "orchestrator_logs" {
  name              = "/hospital-ai/orchestrator"
  retention_in_days = 14
  
  tags = {
    Name = "hospital-ai-orchestrator-logs"
  }
}

# RDS PostgreSQL Database
resource "aws_db_subnet_group" "hospital_db_subnet_group" {
  name       = "hospital-ai-db-subnet-group"
  subnet_ids = [aws_subnet.private_subnet_1.id, aws_subnet.private_subnet_2.id]
  
  tags = {
    Name = "hospital-ai-db-subnet-group"
  }
}

resource "aws_security_group" "rds_sg" {
  name_prefix = "hospital-rds-"
  vpc_id      = aws_vpc.hospital_vpc.id
  
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_sg.id]
  }
  
  tags = {
    Name = "hospital-ai-rds-sg"
  }
}

resource "aws_db_instance" "hospital_db" {
  identifier     = "hospital-ai-db"
  engine         = "postgres"
  engine_version = "15.4"
  instance_class = "db.t3.micro"
  
  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp2"
  storage_encrypted     = true
  
  db_name  = "hospital_db"
  username = "postgres"
  password = random_password.db_password.result
  
  vpc_security_group_ids = [aws_security_group.rds_sg.id]
  db_subnet_group_name   = aws_db_subnet_group.hospital_db_subnet_group.name
  
  backup_retention_period = 7
  backup_window          = "03:00-04:00"
  maintenance_window     = "sun:04:00-sun:05:00"
  
  skip_final_snapshot = true
  deletion_protection = false
  
  tags = {
    Name = "hospital-ai-db"
  }
}

resource "random_password" "db_password" {
  length  = 32
  special = true
}

# ElastiCache Redis
resource "aws_elasticache_subnet_group" "hospital_redis_subnet_group" {
  name       = "hospital-ai-redis-subnet-group"
  subnet_ids = [aws_subnet.private_subnet_1.id, aws_subnet.private_subnet_2.id]
}

resource "aws_security_group" "redis_sg" {
  name_prefix = "hospital-redis-"
  vpc_id      = aws_vpc.hospital_vpc.id
  
  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_sg.id]
  }
  
  tags = {
    Name = "hospital-ai-redis-sg"
  }
}

resource "aws_elasticache_cluster" "hospital_redis" {
  cluster_id           = "hospital-ai-redis"
  engine               = "redis"
  node_type            = "cache.t3.micro"
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.hospital_redis_subnet_group.name
  security_group_ids   = [aws_security_group.redis_sg.id]
  
  tags = {
    Name = "hospital-ai-redis"
  }
}

# Secrets Manager for sensitive data
resource "aws_secretsmanager_secret" "openai_key" {
  name = "hospital/openai-key"
  
  tags = {
    Name = "hospital-ai-openai-key"
  }
}

resource "aws_secretsmanager_secret" "twilio_credentials" {
  name = "hospital/twilio-credentials"
  
  tags = {
    Name = "hospital-ai-twilio-creds"
  }
}

resource "aws_secretsmanager_secret" "database_url" {
  name = "hospital/database-url"
  
  tags = {
    Name = "hospital-ai-database-url"
  }
}

# ECR Repositories
resource "aws_ecr_repository" "twilio_agent" {
  name                 = "hospital-twilio-agent"
  image_tag_mutability = "MUTABLE"
  
  image_scanning_configuration {
    scan_on_push = true
  }
  
  tags = {
    Name = "hospital-twilio-agent"
  }
}

resource "aws_ecr_repository" "orchestrator" {
  name                 = "hospital-orchestrator"
  image_tag_mutability = "MUTABLE"
  
  image_scanning_configuration {
    scan_on_push = true
  }
  
  tags = {
    Name = "hospital-orchestrator"
  }
}

# Data sources
data "aws_availability_zones" "available" {
  state = "available"
}

# Outputs
output "alb_dns_name" {
  description = "DNS name of the load balancer"
  value       = aws_lb.hospital_alb.dns_name
}

output "database_endpoint" {
  description = "Database endpoint"
  value       = aws_db_instance.hospital_db.endpoint
  sensitive   = true
}

output "redis_endpoint" {
  description = "Redis endpoint"
  value       = aws_elasticache_cluster.hospital_redis.cache_nodes[0].address
  sensitive   = true
}