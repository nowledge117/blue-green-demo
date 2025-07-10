import subprocess
import time
import os
import sys
import argparse
import json
import re
import jenkins 
import base64


K8S_NAMESPACE = "blue-green-demo"
JENKINS_HELM_RELEASE_NAME = "jenkins"
JENKINS_JOB_NAME = "blue-green-pipeline"
APP_FILE_PATH = "app/app.js"


def print_color(text, color="cyan"):
    """Prints text in a given color."""
    colors = {
        "header": "\033[95m", "blue": "\033[94m", "cyan": "\033[96m",
        "green": "\033[92m", "yellow": "\033[93m", "red": "\033[91m",
        "endc": "\033[0m", "bold": "\033[1m", "underline": "\033[4m"
    }
    print(f"{colors.get(color, colors['cyan'])}{text}{colors['endc']}")


def run_command(command, check=True, capture_output=False, text=False, env=None, cwd=None):
    """
    Runs a shell command, accepting an optional 'cwd' argument to set the working directory.
    """
    print_color(f"\n> Executing: {' '.join(command)} (in directory: {cwd or os.getcwd()})", "yellow")
    try:
        if not capture_output:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                cwd=cwd  
            )
            for line in iter(process.stdout.readline, ''):
                sys.stdout.write(line)
            process.stdout.close()
            return_code = process.wait()
            if check and return_code != 0:
                raise subprocess.CalledProcessError(return_code, command)
            return ""
        else:
            result = subprocess.run(
                command,
                capture_output=True,
                text=text,
                check=check,
                env=env,
                cwd=cwd  
            )
            return result.stdout.strip()
    except FileNotFoundError:
        print_color(f"Error: Command '{command[0]}' not found. Is it installed and in your PATH?", "red")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print_color(f"Error executing command: {' '.join(e.cmd)}", "red")
        print_color(f"Return code: {e.returncode}", "red")
        if hasattr(e, 'stdout') and e.stdout:
            print(e.stdout)
        if hasattr(e, 'stderr') and e.stderr:
            print(e.stderr)
        if check:
            sys.exit(1)
        else:
            raise



def run_terraform(args, aws_region="ap-south-1"):
    """Runs a terraform command in the terraform/ directory."""
    terraform_dir = os.path.join(os.path.dirname(__file__), "terraform")
    full_command = ["terraform"] + args
    
    if args[0] in ["apply", "destroy"]:
        full_command.append("-auto-approve")
        full_command.extend(["-var", f"aws_region={aws_region}"])
        
    try:
        run_command(full_command, cwd=terraform_dir)
    except subprocess.CalledProcessError as e:
        print_color(f"Terraform command failed: {' '.join(full_command)}", "red")
        sys.exit(1)

def get_terraform_outputs():
    """Reads the terraform output variables."""
    print_color("\n--- Reading outputs from Terraform state ---", "cyan")
    terraform_dir = os.path.join(os.path.dirname(__file__), "terraform")
    try:
        outputs_json = run_command(["terraform", "output", "-json"], capture_output=True, text=True, cwd=terraform_dir)
        return json.loads(outputs_json)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print_color(f"Error reading Terraform outputs: {e}", "red")
        print_color("Please ensure 'terraform apply' has run successfully.", "red")
        sys.exit(1)


def provision_infrastructure(aws_region):
    """Provisions all cloud infrastructure using Terraform."""
    print_color("=== PHASE 1: PROVISIONING INFRASTRUCTURE (TAKES ~20 MINS) ===", "header")
    print_color("--- Initializing Terraform ---", "cyan")
    run_terraform(["init"])
    print_color("\n--- Applying Terraform configuration ---", "cyan")
    print_color("This will create the VPC, EKS Cluster, IAM Roles, and ECR Repo.", "yellow")
    run_terraform(["apply"], aws_region=aws_region)
    print_color("\nInfrastructure provisioning complete!", "green")

def deploy_and_configure_jenkins(tf_outputs):
    """Deploys Jenkins, waits for its public URL, and returns the server object."""
    print_color("\n=== PHASE 2: DEPLOYING & CONFIGURING JENKINS ===", "header")
    
    jenkins_role_arn = tf_outputs["jenkins_iam_role_arn"]["value"]
    

    print_color("--- Rendering Jenkins Helm values with IAM Role ARN ---", "cyan")
    with open("jenkins_config/jenkins-values.yaml", "r") as f:
        values_content = f.read()
    values_content = values_content.replace("{{JENKINS_IAM_ROLE_ARN}}", jenkins_role_arn.strip())
    rendered_values_path = "jenkins_config/jenkins-values-rendered.yaml"
    with open(rendered_values_path, "w") as f:
        f.write(values_content)


    print_color("\n--- Deploying Jenkins via Helm ---", "cyan")
    run_command(["kubectl", "create", "namespace", K8S_NAMESPACE], check=False)
    run_command([
        "helm", "install", JENKINS_HELM_RELEASE_NAME, "jenkins/jenkins",
        "--namespace", K8S_NAMESPACE, "--values", rendered_values_path
    ])

    print_color("\n--- Waiting for Jenkins Load Balancer public hostname... ---", "yellow")
    return server 

def configure_jenkins_job(server, aws_account_id, aws_region, git_repo_url, git_branch):
    """Creates credentials and the pipeline job in Jenkins."""
    print_color("\n=== PHASE 3: CONFIGURING JENKINS JOB & CREDENTIALS ===", "header")
    

    from jenkins import STRING_CREDENTIAL
    print_color("--- Creating Jenkins credentials for AWS Account and Region ---", "cyan")
    server.create_credential(
        'jenkins',
        STRING_CREDENTIAL,
        dict(id='aws-account-id', scope='GLOBAL', description='AWS Account ID', secret=aws_account_id)
    )
    server.create_credential(
        'jenkins',
        STRING_CREDENTIAL,
        dict(id='aws-region', scope='GLOBAL', description='AWS Region', secret=aws_region)
    )
    

def cleanup_infrastructure():
    """Destroys all cloud infrastructure using Terraform."""
    print_color("=== CLEANUP: DESTROYING ALL AWS INFRASTRUCTURE ===", "header")
    print_color("This will remove the EKS cluster, VPC, and all related resources.", "yellow")
    run_terraform(["destroy"])
    print_color("\nCleanup complete.", "green")

def main():
    parser = argparse.ArgumentParser(description="Full Lifecycle Blue-Green Demo Orchestrator for AWS EKS.")
    parser.add_argument("--aws-account-id", required=True, help="Your AWS Account ID.")
    parser.add_argument("--aws-region", default="ap-south-1", help="AWS Region to deploy to.")
    parser.add_argument("--git-repo-url", required=True, help="Git repository URL for the pipeline.")
    parser.add_argument("--git-branch", default="main", help="Git branch to use.")
    parser.add_argument("--cleanup-only", action="store_true", help="Only run the cleanup step.")
    args = parser.parse_args()


    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    if args.cleanup_only:
        cleanup_infrastructure()
        sys.exit(0)

    try:

        provision_infrastructure(args.aws_region)
        

        tf_outputs = get_terraform_outputs()
        server = deploy_and_configure_jenkins(tf_outputs)
        

        configure_jenkins_job(server, args.aws_account_id, args.aws_region, args.git_repo_url, args.git_branch)


        orchestrate_blue_green_flow(server) 

        print_color("\n🎉🎉🎉 Demo Completed Successfully! 🎉🎉🎉", "bold")

    except Exception as e:
        print_color(f"\nAn error occurred: {e}", "red")
        traceback.print_exc()
    finally:
        if input("\nDo you want to run cleanup and destroy all AWS infrastructure? (y/n): ").lower() == 'y':
            cleanup_infrastructure()

if __name__ == "__main__":
    main()