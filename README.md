## Architecture
I designed the architecture to mirror modern cloud-native best practices, ensuring a clean separation of concerns between the infrastructure layer and the application layer.

<img width="579" alt="image" src="https://github.com/user-attachments/assets/28f7c14d-ba6e-4d74-9893-4240dfc7f9a9" />

# Key Features & Highlights:

* End-to-End Automation: A single Python script orchestrates the entire process. No manual clicking in the AWS console is required.
* Infrastructure as Code (IaC): The entire cloud environment (VPC, EKS Cluster, IAM Roles, ECR Repository) is defined declaratively using Terraform, ensuring a repeatable, version-controlled, and transparent setup.
* Secure Cloud Integration: I have implemented IAM Roles for Service Accounts (IRSA) to provide Jenkins pods with secure, temporary AWS credentials, eliminating the need for static access keys.
* Zero-Downtime Deployment Strategy: The core of the project demonstrates a robust blue-green deployment, allowing for new application versions to be verified in a production-like environment before receiving live traffic.
* Publicly Accessible Endpoints: Jenkins and the application services are exposed to the internet via AWS Network Load Balancers, making the demo easy to access and verify from anywhere.

**Pre-Requisites**  To replicate this environment, you will need the following tools installed and configured:
* An AWS Account with administrative privileges.
* AWS CLI (aws configure completed)
* Terraform (v1.0+)
* kubectl
* Helm
* Python 3.11

The Automated Workflow
I have designed the workflow to be as simple as possible, driven by a master orchestrator script.
⚠️ This process will incur AWS costs. Please ensure you run the cleanup command after your demo.

**Step 1:** Environment Setup
1. Prepare your local environment.
2. Clone this repository.
3. Create and activate a Python virtual environment to ensure dependency isolation:
``` 
python3.11 -m venv venv
source venv/bin/activate
```

4. Install the required Python packages:
```
pip install -r requirements.txt
```

**Step 2:** Deploy Everything
Execute the orchestrator script from the project root. This single command will provision the infrastructure and deploy the application stack. The process takes ~25 minutes.
```
python3 orchestrator.py \
  --aws-account-id <YOUR_AWS_ACCOUNT_ID> \
  --git-repo-url <YOUR_GIT_REPO_URL>
```

The script will now:
1. Execute terraform init and terraform apply to build the AWS infrastructure.
2. Deploy Jenkins with Helm, injecting the secure IAM Role ARN provided by the Terraform output.
3. Poll AWS until the public Jenkins Load Balancer is active.
4. Connect to Jenkins, create the necessary credentials, and configure the pipeline job.
5. Trigger the first pipeline run to deploy the "BLUE" version of the application.
6. Prompt you to update the application code and git push, which then triggers the "GREEN" deployment and completes the blue-green switch.

**Step 3:** Cleanup
To prevent ongoing AWS charges, run the orchestrator with the --cleanup-only flag. This is the most critical step.
```
python3 orchestrator.py --cleanup-only
```

**This command invokes terraform destroy, which will tear down all the AWS resources that were created.**

