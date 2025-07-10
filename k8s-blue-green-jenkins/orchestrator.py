import subprocess
import time
import os
import sys
import argparse
import jenkins # python-jenkins library
import re
import base64

# --- Configuration ---
MINIKUBE_PROFILE = "minikube"
K8S_NAMESPACE = "blue-green-demo"
JENKINS_HELM_RELEASE_NAME = "jenkins"
JENKINS_JOB_NAME = "blue-green-pipeline"
APP_FILE_PATH = "app/app.js"

# --- Helper Functions (No changes here) ---

def print_color(text, color="cyan"):
    """Prints text in a given color."""
    colors = {
        "header": "\033[95m", "blue": "\033[94m", "cyan": "\033[96m",
        "green": "\033[92m", "yellow": "\033[93m", "red": "\033[91m",
        "endc": "\033[0m", "bold": "\033[1m", "underline": "\033[4m"
    }
    print(f"{colors.get(color, colors['cyan'])}{text}{colors['endc']}")

def run_command(command, check=True, capture_output=False, text=False, env=None):
    """Runs a shell command and streams its output, or captures it."""
    print_color(f"\n> Executing: {' '.join(command)}", "yellow")
    try:
        if not capture_output:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env
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
                env=env
            )
            return result.stdout.strip()
    except FileNotFoundError:
        print_color(f"Error: Command '{command[0]}' not found. Is it installed and in your PATH?", "red")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print_color(f"Error executing command: {' '.join(e.cmd)}", "red")
        print_color(f"Return code: {e.returncode}", "red")
        if e.stdout:
            print(e.stdout)
        if e.stderr:
            print(e.stderr)
        # Don't exit here if check=False was intended
        if check:
            sys.exit(1)
        else: # If check=False, we want to return the error info instead of exiting
            raise

def get_minikube_docker_env():
    """Gets the Docker environment variables from Minikube."""
    print_color("--- Getting Minikube Docker environment ---")
    output = subprocess.check_output(
        f'minikube -p {MINIKUBE_PROFILE} docker-env',
        shell=True,
        text=True
    )
    env = os.environ.copy()
    for line in output.strip().split('\n'):
        if line.startswith('export '):
            key, value = line.replace('export ', '').split('=', 1)
            env[key] = value.strip('"')
    print_color("Docker environment configured to use Minikube's daemon.", "green")
    return env


# --- Main Logic Functions ---

def setup_infrastructure():
    """Starts Minikube, creates namespace, and installs Jenkins."""
    print_color("=== PHASE 1: INFRASTRUCTURE SETUP ===", "header")
    run_command(["minikube", "start", "--profile", MINIKUBE_PROFILE, "--memory", "4096", "--cpus", "2"])
    run_command(["kubectl", "apply", "-f", "k8s/namespace.yaml"])
    run_command(["helm", "repo", "add", "jenkins", "https://charts.jenkins.io"])
    run_command(["helm", "repo", "update"])
    run_command([
        "helm", "install", JENKINS_HELM_RELEASE_NAME, "jenkins/jenkins",
        "--namespace", K8S_NAMESPACE,
        "--values", "jenkins_config/jenkins-values.yaml"
    ])
    
    # Automatically patch the service to NodePort if it was deployed as ClusterIP.
    print_color("\n--- Verifying Jenkins Service Type ---", "cyan")
    time.sleep(5) # Give the service a moment to be created
    try:
        get_service_type_cmd = [
            "kubectl", "get", "service", JENKINS_HELM_RELEASE_NAME,
            "-n", K8S_NAMESPACE,
            "-o", "jsonpath={.spec.type}"
        ]
        service_type = run_command(get_service_type_cmd, capture_output=True, text=True, check=False)

        if service_type == "ClusterIP":
            print_color(f"Jenkins service is of type 'ClusterIP'. Patching to 'NodePort'...", "yellow")
            patch_cmd = [
                "kubectl", "patch", "service", JENKINS_HELM_RELEASE_NAME,
                "-n", K8S_NAMESPACE,
                "-p", '{"spec": {"type": "NodePort"}}'
            ]
            run_command(patch_cmd)
            print_color("Service patched successfully to NodePort.", "green")
        else:
            print_color(f"Jenkins service is already of type '{service_type}'. No patch needed.", "green")
    except subprocess.CalledProcessError:
        print_color("Could not verify Jenkins service type. The service might not exist yet. Continuing...", "red")

    ### --- [NEW] ---
    # Intelligent polling loop to check for pod readiness.
    print_color("\n--- Polling for Jenkins pod to be ready (10s interval, 7min timeout) ---", "yellow")
    timeout_seconds = 420  # 7 minutes
    start_time = time.time()
    pod_is_ready = False
    pod_name = ""

    while time.time() - start_time < timeout_seconds:
        try:
            # First, get the dynamic name of the Jenkins pod
            get_pod_name_cmd = [
                "kubectl", "get", "pods",
                "-n", K8S_NAMESPACE,
                "-l", "app.kubernetes.io/component=jenkins-controller",
                "-o", "jsonpath={.items[0].metadata.name}"
            ]
            pod_name = run_command(get_pod_name_cmd, capture_output=True, text=True, check=False)

            if not pod_name:
                print_color("Jenkins pod not found yet, waiting...", "yellow")
                time.sleep(10)
                continue

            # Second, check if the pod's main container is ready
            get_readiness_cmd = [
                "kubectl", "get", "pod", pod_name,
                "-n", K8S_NAMESPACE,
                "-o", "jsonpath={.status.containerStatuses[0].ready}"
            ]
            is_ready_str = run_command(get_readiness_cmd, capture_output=True, text=True, check=False)

            if is_ready_str == 'true':
                print_color(f"Success! Pod '{pod_name}' is ready.", "green")
                pod_is_ready = True
                break  # Exit the loop on success
            else:
                get_phase_cmd = ["kubectl", "get", "pod", pod_name, "-n", K8S_NAMESPACE, "-o", "jsonpath={.status.phase}"]
                phase = run_command(get_phase_cmd, capture_output=True, text=True, check=False)
                print_color(f"Pod '{pod_name}' found in phase '{phase}', but not ready. Retrying in 10s...", "yellow")

        except (subprocess.CalledProcessError, IndexError):
            # This can happen if the pod exists but its status fields aren't populated yet.
            print_color("Jenkins pod found, but its status is not yet available. Retrying in 10s...", "yellow")

        time.sleep(10) # The 10-second polling interval

    # After the loop, check if we timed out
    if not pod_is_ready:
        print_color("\nError: Timed out waiting for Jenkins pod to become ready.", "red")
        print_color("Displaying final pod status for debugging:", "red")
        run_command(["kubectl", "get", "pods", "-n", K8S_NAMESPACE], check=False)
        if pod_name:
            run_command(["kubectl", "describe", "pod", pod_name, "-n", K8S_NAMESPACE], check=False)
        sys.exit(1)
    ### --- [END NEW] ---

    print_color("\nJenkins setup is complete!", "green")


# ... (The rest of the file: configure_jenkins, orchestrate_blue_green_flow, cleanup, main, etc. remains exactly the same) ...
def configure_jenkins(git_repo_url, git_branch):
    """Connects to Jenkins and creates the pipeline job."""
    print_color("=== PHASE 2: JENKINS CONFIGURATION ===", "header")

    ### --- [NEW AND ROBUST URL LOGIC] ---
    # We construct the URL manually to avoid the potentially blocking `minikube service --url` command.
    
    print_color("\n--- Getting Jenkins connection details ---", "cyan")
    try:
        # 1. Get the Minikube IP address (non-blocking)
        minikube_ip = run_command(["minikube", "ip", "-p", MINIKUBE_PROFILE], capture_output=True, text=True)
        if not minikube_ip:
            raise ValueError("Minikube IP address could not be retrieved.")
        print_color(f"Minikube IP found: {minikube_ip}", "green")

        # 2. Get the service's NodePort number (non-blocking)
        get_node_port_cmd = [
            "kubectl", "get", "service", JENKINS_HELM_RELEASE_NAME,
            "-n", K8S_NAMESPACE,
            "-o", "jsonpath={.spec.ports[0].nodePort}"
        ]
        node_port = run_command(get_node_port_cmd, capture_output=True, text=True)
        if not node_port:
            raise ValueError("Jenkins NodePort could not be retrieved. Is the service a NodePort?")
        print_color(f"Jenkins NodePort found: {node_port}", "green")

        # 3. Construct the final URL
        jenkins_url = f"http://{minikube_ip}:{node_port}"

    except (subprocess.CalledProcessError, ValueError) as e:
        print_color(f"Error: Could not determine Jenkins URL. {e}", "red")
        print_color("Please ensure Minikube is running and the Jenkins service is deployed and exposed as a NodePort.", "red")
        sys.exit(1)
    ### --- [END NEW LOGIC] ---

    
    # Get Admin Password (this logic is fine)
    admin_password_cmd = [
        "kubectl", "get", "secret", "--namespace", K8S_NAMESPACE, JENKINS_HELM_RELEASE_NAME,
        "-o", "jsonpath={.data.jenkins-admin-password}"
    ]
    password_b64 = run_command(admin_password_cmd, capture_output=True, text=True)
    admin_password = base64.b64decode(password_b64).decode('utf-8')

    print_color(f"Jenkins URL: {jenkins_url}")
    print_color(f"Jenkins Admin User: admin")
    
    # Connect to Jenkins (no changes from here down in this function)
    server = jenkins.Jenkins(jenkins_url, username='admin', password=admin_password)
    
    # Add a retry loop for the initial connection, as Jenkins might still be starting up internally
    print_color("--- Attempting to connect to Jenkins API... ---", "yellow")
    max_retries = 10
    for i in range(max_retries):
        try:
            version = server.get_version()
            print_color(f"Successfully connected to Jenkins version {version}", "green")
            break
        except jenkins.JenkinsException as e:
            if i < max_retries - 1:
                print_color(f"Connection failed, retrying in 10s... ({i+1}/{max_retries})", "yellow")
                time.sleep(10)
            else:
                print_color(f"Fatal Error: Could not connect to Jenkins API after {max_retries} attempts.", "red")
                print_color(f"Error details: {e}", "red")
                sys.exit(1)

    # Create job from XML template
    with open("jenkins_config/job_config.xml", "r") as f:
        job_config_xml = f.read()
    
    job_config_xml = job_config_xml.replace("{{GIT_REPO_URL}}", git_repo_url)
    job_config_xml = job_config_xml.replace("{{GIT_BRANCH}}", git_branch)

    if server.job_exists(JENKINS_JOB_NAME):
        print_color(f"Job '{JENKINS_JOB_NAME}' already exists. Reconfiguring.", "yellow")
        server.reconfig_job(JENKINS_JOB_NAME, job_config_xml)
    else:
        print_color(f"Creating job '{JENKINS_JOB_NAME}'.", "cyan")
        server.create_job(JENKINS_JOB_NAME, job_config_xml)
        
    print_color(f"Jenkins pipeline '{JENKINS_JOB_NAME}' is configured.", "green")
    return server

def wait_for_build(server, job_name, queue_item_number):
    """Waits for a queued Jenkins build to start and finish."""
    print_color(f"--- Waiting for build to start (Queue item: {queue_item_number}) ---", "yellow")
    build_info = None
    start_time = time.time()
    
    while time.time() - start_time < 300: # 5 min timeout to start
        try:
            queue_item_info = server.get_queue_item(queue_item_number)
            if queue_item_info.get('executable'):
                build_info = queue_item_info['executable']
                break
        except jenkins.NotFoundException:
            time.sleep(2)
            try:
                last_build_number = server.get_job_info(job_name)['lastBuild']['number']
                build_info = {'number': last_build_number}
                break
            except (KeyError, TypeError):
                pass
        time.sleep(5)
    
    if not build_info:
        print_color(f"Error: Build did not start from queue item {queue_item_number} within 5 minutes.", "red")
        sys.exit(1)

    build_number = build_info['number']
    print_color(f"Build #{build_number} started. Waiting for completion...", "cyan")

    while server.get_build_info(job_name, build_number)['building']:
        time.sleep(10)
        print_color(f"Build #{build_number} is still running...", "yellow")

    final_build_info = server.get_build_info(job_name, build_number)
    print_color(f"Build #{build_number} finished with result: {final_build_info['result']}", "green" if final_build_info['result'] == 'SUCCESS' else 'red')
    if final_build_info['result'] != 'SUCCESS':
        print_color("Build failed. Check Jenkins logs for details.", "red")
        sys.exit(1)

def orchestrate_blue_green_flow(server):
    """Triggers and manages the two-stage blue-green deployment."""
    print_color("=== PHASE 3: CI/CD ORCHESTRATION ===", "header")
    
    print_color("\n--- Triggering BLUE deployment (Build #1) ---", "blue")
    queue_item = server.build_job(JENKINS_JOB_NAME)
    wait_for_build(server, JENKINS_JOB_NAME, queue_item)
    
    active_url = run_command(["minikube", "service", "active-service", "--url", "-n", K8S_NAMESPACE], capture_output=True, text=True)
    print_color(f"\nBLUE deployment complete. Access it at: {active_url}", "green")
    print_color("Check the output, it should be 'Version: 1.0 (BLUE)'", "cyan")
    
    print_color("\n--- Preparing for GREEN deployment ---", "green")
    print_color("Updating app.js to version 2.0 (GREEN)...", "cyan")
    with open(APP_FILE_PATH, 'r') as f:
        content = f.read()
    new_content = re.sub(r'const APP_VERSION = ".*"', 'const APP_VERSION = "2.0 (GREEN)";', content)
    with open(APP_FILE_PATH, 'w') as f:
        f.write(new_content)
    
    print_color(f"{APP_FILE_PATH} has been updated.", "green")
    print_color("Please commit and push this change to your Git repository now.", "bold")
    input("Press Enter after you have pushed the change to Git...")
    
    print_color("\n--- Triggering GREEN deployment (Build #2) ---", "green")
    queue_item = server.build_job(JENKINS_JOB_NAME)
    
    print_color("Waiting for the pipeline to pause for approval...", "yellow")
    time.sleep(30)
    build_number = server.get_job_info(JENKINS_JOB_NAME)['lastBuild']['number']
    while True:
        build_info = server.get_build_info(JENKINS_JOB_NAME, build_number)
        if not build_info['building']:
            break
        
        input_action = next((action for action in build_info.get('actions', []) if action and '_class' in action and action['_class'] == 'org.jenkinsci.plugins.workflow.support.steps.input.InputStepAction'), None)
        if input_action:
            print_color(f"Build #{build_number} is paused. Automatically proceeding.", "cyan")
            server.handle_input(build_info, input_action['id'], 'Proceed')
            break
        time.sleep(5)

    wait_for_build(server, JENKINS_JOB_NAME, queue_item)

    print_color(f"\nGREEN deployment and traffic switch complete!", "green")
    print_color(f"Refresh the active service URL: {active_url}", "bold")
    print_color("The output should now be 'Version: 2.0 (GREEN)'", "cyan")

def cleanup():
    """Deletes the minikube cluster."""
    print_color("=== PHASE 4: CLEANUP ===", "header")
    run_command(["minikube", "delete", "--profile", MINIKUBE_PROFILE], check=False)
    print_color("Cleanup complete.", "green")

def main():
    parser = argparse.ArgumentParser(description="Automated Blue-Green Deployment Orchestrator.")
    # The definition of the argument is correct, it uses a hyphen
    parser.add_argument("--git-repo-url", required=True, help="Git repository URL for the Jenkins pipeline.")
    parser.add_argument("--git-branch", default="main", help="Git branch to use in the pipeline.")
    parser.add_argument("--skip-setup", action="store_true", help="Skip Minikube and Jenkins setup.")
    parser.add_argument("--cleanup-only", action="store_true", help="Only run the cleanup step.")
    args = parser.parse_args()

    if args.cleanup_only:
        cleanup()
        sys.exit(0)

    try:
        # --- [CORRECTED LINE] ---
        # The variable in Python uses an underscore, not a hyphen.
        if not args.skip_setup:
            setup_infrastructure()
        
        # --- [CORRECTED LINE] ---
        # Same correction here for the Git URL argument.
        server = configure_jenkins(args.git_repo_url, args.git_branch)
        orchestrate_blue_green_flow(server)
        
        print_color("\n🎉🎉🎉 Demo Completed Successfully! 🎉🎉🎉", "bold")

    except Exception as e:
        print_color(f"\nAn error occurred: {e}", "red")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if input("\nDo you want to run cleanup and delete the minikube cluster? (y/n): ").lower() == 'y':
            cleanup()

if __name__ == "__main__":
    if not os.path.exists('k8s') or not os.path.exists('jenkins'):
        print_color("Error: Please run this script from the root of the project directory.", "red")
        sys.exit(1)
    main()