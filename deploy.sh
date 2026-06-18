#!/bin/bash

# Production Deployment Script for Hospital AI System
# This script handles the complete deployment process to AWS

set -e

# Configuration
AWS_REGION=${AWS_REGION:-"us-east-1"}
ENVIRONMENT=${ENVIRONMENT:-"production"}
PROJECT_NAME="hospital-ai-system"
DOMAIN_NAME=${DOMAIN_NAME:-"api.hospital-ai.com"}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}"
    exit 1
}

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."
    
    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        error "AWS CLI is not installed"
    fi
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        error "Docker is not installed"
    fi
    
    # Check Terraform
    if ! command -v terraform &> /dev/null; then
        error "Terraform is not installed"
    fi
    
    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        error "AWS credentials not configured"
    fi
    
    log "Prerequisites check passed ✓"
}

# Build and push Docker images
build_and_push_images() {
    log "Building and pushing Docker images..."
    
    # Get AWS account ID
    AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    
    # Login to ECR
    aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
    
    # Build Twilio agent image
    log "Building Twilio agent image..."
    docker build -f Dockerfile.twilio -t hospital-twilio-agent:latest .
    docker tag hospital-twilio-agent:latest $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/hospital-twilio-agent:latest
    docker tag hospital-twilio-agent:latest $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/hospital-twilio-agent:$(git rev-parse --short HEAD)
    
    # Push Twilio agent image
    docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/hospital-twilio-agent:latest
    docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/hospital-twilio-agent:$(git rev-parse --short HEAD)
    
    # Build orchestrator image
    log "Building hospital orchestrator image..."
    docker build -f Dockerfile.orchestrator -t hospital-orchestrator:latest .
    docker tag hospital-orchestrator:latest $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/hospital-orchestrator:latest
    docker tag hospital-orchestrator:latest $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/hospital-orchestrator:$(git rev-parse --short HEAD)
    
    # Push orchestrator image
    docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/hospital-orchestrator:latest
    docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/hospital-orchestrator:$(git rev-parse --short HEAD)
    
    log "Docker images built and pushed ✓"
}

# Deploy infrastructure with Terraform
deploy_infrastructure() {
    log "Deploying infrastructure with Terraform..."
    
    cd terraform
    
    # Initialize Terraform
    terraform init
    
    # Plan deployment
    terraform plan \
        -var="aws_region=$AWS_REGION" \
        -var="environment=$ENVIRONMENT" \
        -var="domain_name=$DOMAIN_NAME" \
        -out=tfplan
    
    # Apply if approved
    read -p "Do you want to apply the Terraform plan? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        terraform apply tfplan
        log "Infrastructure deployed ✓"
    else
        warn "Infrastructure deployment skipped"
        return 1
    fi
    
    cd ..
}

# Deploy ECS services
deploy_ecs_services() {
    log "Deploying ECS services..."
    
    # Get AWS account ID and commit hash
    AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    IMAGE_TAG=$(git rev-parse --short HEAD)
    
    # Create or update ECS task definitions
    log "Creating ECS task definitions..."
    
    # Twilio Agent Task Definition
    cat > twilio-agent-task-def.json << EOF
{
    "family": "hospital-twilio-agent",
    "networkMode": "awsvpc",
    "requiresCompatibilities": ["FARGATE"],
    "cpu": "512",
    "memory": "1024",
    "executionRoleArn": "arn:aws:iam::$AWS_ACCOUNT_ID:role/ecsTaskExecutionRole",
    "taskRoleArn": "arn:aws:iam::$AWS_ACCOUNT_ID:role/ecsTaskRole",
    "containerDefinitions": [
        {
            "name": "twilio-agent",
            "image": "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/hospital-twilio-agent:$IMAGE_TAG",
            "essential": true,
            "portMappings": [
                {
                    "containerPort": 5050,
                    "protocol": "tcp"
                }
            ],
            "environment": [
                {
                    "name": "HOSPITAL_ORCHESTRATOR_URL",
                    "value": "http://hospital-orchestrator.hospital-ai.local:8000"
                },
                {
                    "name": "PUBLIC_URL",
                    "value": "https://$DOMAIN_NAME"
                },
                {
                    "name": "AWS_REGION",
                    "value": "$AWS_REGION"
                }
            ],
            "secrets": [
                {
                    "name": "OPENAI_KEY",
                    "valueFrom": "arn:aws:secretsmanager:$AWS_REGION:$AWS_ACCOUNT_ID:secret:hospital/openai-key"
                },
                {
                    "name": "TWILIO_ACCOUNT_SID",
                    "valueFrom": "arn:aws:secretsmanager:$AWS_REGION:$AWS_ACCOUNT_ID:secret:hospital/twilio-credentials:TWILIO_ACCOUNT_SID::"
                },
                {
                    "name": "TWILIO_AUTH_TOKEN",
                    "valueFrom": "arn:aws:secretsmanager:$AWS_REGION:$AWS_ACCOUNT_ID:secret:hospital/twilio-credentials:TWILIO_AUTH_TOKEN::"
                }
            ],
            "logConfiguration": {
                "logDriver": "awslogs",
                "options": {
                    "awslogs-group": "/hospital-ai/twilio-agent",
                    "awslogs-region": "$AWS_REGION",
                    "awslogs-stream-prefix": "ecs"
                }
            },
            "healthCheck": {
                "command": ["CMD-SHELL", "curl -f http://localhost:5050/health || exit 1"],
                "interval": 30,
                "timeout": 10,
                "retries": 3,
                "startPeriod": 60
            }
        }
    ]
}
EOF

    # Register task definition
    aws ecs register-task-definition --cli-input-json file://twilio-agent-task-def.json
    
    # Create or update ECS service
    log "Creating/updating ECS services..."
    
    # Check if service exists
    if aws ecs describe-services --cluster hospital-ai-cluster --services hospital-twilio-agent &>/dev/null; then
        # Update existing service
        aws ecs update-service \
            --cluster hospital-ai-cluster \
            --service hospital-twilio-agent \
            --task-definition hospital-twilio-agent \
            --desired-count 2
    else
        # Create new service
        aws ecs create-service \
            --cluster hospital-ai-cluster \
            --service-name hospital-twilio-agent \
            --task-definition hospital-twilio-agent \
            --desired-count 2 \
            --launch-type FARGATE \
            --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx,subnet-yyy],securityGroups=[sg-xxx],assignPublicIp=ENABLED}" \
            --load-balancers "targetGroupArn=arn:aws:elasticloadbalancing:$AWS_REGION:$AWS_ACCOUNT_ID:targetgroup/hospital-twilio-tg/xxx,containerName=twilio-agent,containerPort=5050"
    fi
    
    log "ECS services deployed ✓"
}

# Configure Twilio webhooks
configure_twilio_webhooks() {
    log "Configuring Twilio webhooks..."
    
    # Get ALB DNS name from Terraform output
    ALB_DNS=$(cd terraform && terraform output -raw alb_dns_name)
    
    if [ -z "$ALB_DNS" ]; then
        warn "Could not get ALB DNS name. Skipping Twilio webhook configuration."
        return
    fi
    
    log "Setting up Twilio webhooks to point to https://$DOMAIN_NAME"
    
    # Note: In production, you would use Twilio CLI or API to configure webhooks
    # twilio phone-numbers:update $TWILIO_PHONE_NUMBER --voice-url="https://$DOMAIN_NAME/incoming-call"
    
    warn "Please manually configure Twilio webhooks:"
    echo "  Voice URL: https://$DOMAIN_NAME/incoming-call"
    echo "  Voice Method: POST"
    echo "  Status Callback URL: https://$DOMAIN_NAME/call-status"
}

# Health check
perform_health_check() {
    log "Performing health checks..."
    
    # Wait for services to be healthy
    max_attempts=30
    attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        log "Health check attempt $attempt/$max_attempts"
        
        # Check Twilio agent health
        if curl -f https://$DOMAIN_NAME/health &>/dev/null; then
            log "Twilio agent is healthy ✓"
            break
        fi
        
        sleep 30
        ((attempt++))
    done
    
    if [ $attempt -gt $max_attempts ]; then
        error "Health check failed after $max_attempts attempts"
    fi
    
    log "All services are healthy ✓"
}

# Main deployment function
main() {
    log "Starting Hospital AI System deployment to AWS..."
    log "Environment: $ENVIRONMENT"
    log "Region: $AWS_REGION"
    log "Domain: $DOMAIN_NAME"
    
    check_prerequisites
    
    # Build and push images
    if [ "${SKIP_BUILD:-false}" != "true" ]; then
        build_and_push_images
    else
        log "Skipping image build (SKIP_BUILD=true)"
    fi
    
    # Deploy infrastructure
    if [ "${SKIP_INFRASTRUCTURE:-false}" != "true" ]; then
        deploy_infrastructure
    else
        log "Skipping infrastructure deployment (SKIP_INFRASTRUCTURE=true)"
    fi
    
    # Deploy ECS services
    deploy_ecs_services
    
    # Configure Twilio
    configure_twilio_webhooks
    
    # Health check
    perform_health_check
    
    log "🎉 Deployment completed successfully!"
    log "Application URL: https://$DOMAIN_NAME"
    log "Monitoring: Access CloudWatch logs for detailed monitoring"
    
    # Cleanup
    rm -f twilio-agent-task-def.json
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --region)
            AWS_REGION="$2"
            shift 2
            ;;
        --domain)
            DOMAIN_NAME="$2"
            shift 2
            ;;
        --environment)
            ENVIRONMENT="$2"
            shift 2
            ;;
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --skip-infrastructure)
            SKIP_INFRASTRUCTURE=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  --region REGION          AWS region (default: us-east-1)"
            echo "  --domain DOMAIN          Domain name (default: api.hospital-ai.com)"
            echo "  --environment ENV        Environment (default: production)"
            echo "  --skip-build            Skip Docker image build"
            echo "  --skip-infrastructure   Skip Terraform infrastructure deployment"
            echo "  --help                  Show this help message"
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            ;;
    esac
done

# Run main function
main