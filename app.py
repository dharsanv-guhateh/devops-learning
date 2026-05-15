from flask import Flask, render_template_string, request
import docker
import boto3
import os

app = Flask(__name__)

active_deployments = {}

def get_temp_creds(role_arn):
    """Fetches temporary 1-hour session tokens using your host's credentials"""
    sts_client = boto3.client('sts')
    assumed = sts_client.assume_role(
        RoleArn=role_arn,
        RoleSessionName="SRE_Portal_Session"
    )
    creds = assumed['Credentials']
    return {
        'AWS_ACCESS_KEY_ID': creds['AccessKeyId'],
        'AWS_SECRET_ACCESS_KEY': creds['SecretAccessKey'],
        'AWS_SESSION_TOKEN': creds['SessionToken']
    }

HTML_FORM = '''
<!DOCTYPE html>
<html>
<head>
    <title>SRE Cloud Portal</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 40px; background-color: #f4f7f6; }
        .container { background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); max-width: 500px; }
        .form-group { margin-bottom: 15px; }
        label { font-weight: bold; display: block; margin-bottom: 5px; }
        input, select { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }
        .btn { width: 100%; padding: 12px; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; font-weight: bold; }
        .btn-deploy { background-color: #28a745; color: white; margin-bottom: 10px; }
        .btn-destroy { background-color: #dc3545; color: white; }
    </style>
</head>
<body>
    <div class="container">
        <h2>Infrastructure Manager (Secure Mode)</h2>
        <form method="POST" action="/manage">
            <div class="form-group">
                <label>Cloud Provider:</label>
                <select name="provider">
                    <option value="aws">AWS</option>
                </select>
            </div>
            <div class="form-group">
                <label>Environment:</label>
                <select name="env">
                    <option value="dev">Development</option>
                    <option value="staging">Staging</option>
                    <option value="prod">Production</option>
                </select>
            </div>
            <div class="form-group">
                <label>AMI ID:</label>
                <input type="text" name="ami" placeholder="ami-xxxxxxxx" required>
            </div>
            <div class="form-group">
                <label>Region:</label>
                <input type="text" name="region" placeholder="us-east-1" required>
            </div>
            <div class="form-group">
                <label>Instance Type:</label>
                <input type="text" name="instance_type" value="t3.micro">
            </div>
            <hr>
            <label>Select Action:</label>
            <button type="submit" name="action" value="apply" class="btn btn-deploy">PROVISION (Apply)</button>
            <button type="submit" name="action" value="destroy" class="btn btn-destroy">CLEANUP (Destroy)</button>
        </form>
    </div>
</body>
</html>
'''

@app.route('/')
def home():
    return render_template_string(HTML_FORM)

@app.route('/manage', methods=['POST'])
def manage():
    action = request.form.get('action')
    ROLE_ARN = "arn:aws:iam::537124942936:role/Docker-Project"
    
    try:
        temp_aws_env = get_temp_creds(ROLE_ARN)
    except Exception as e:
        return f"<h3>IAM Error:</h3><p>{str(e)}</p><a href='/'>Back</a>"

    data = {
        "TF_VAR_provider": request.form.get('provider'),
        "TF_VAR_env": request.form.get('env'),
        "TF_VAR_ami_id": request.form.get('ami'),
        "TF_VAR_region": request.form.get('region'),
        "TF_VAR_instance_type": request.form.get('instance_type'),
    }
    
    full_env = {**data, **temp_aws_env}

    # CHANGE: We now assume the mounted folder is at /infra
    command_to_run = f"cd /infra/{data['TF_VAR_provider']}/{data['TF_VAR_env']} && /usr/local/bin/terragrunt {action} --terragrunt-non-interactive -auto-approve"

    client = docker.from_env()
    
    # NEW: Get the path of your host infra folder automatically
    host_infra_path = "/home/dharsanv/my-infra" 

    try:
        container = client.containers.run(
            image="my-custom-runner:v1",
            command=["/bin/bash", "-c", command_to_run],
            environment=full_env,
            # NEW: This mounts your actual files into the runner
            volumes={
                host_infra_path: {'bind': '/infra', 'mode': 'rw'}
            },
            detach=True
        )
        
        active_deployments[container.short_id] = container.id
        return f'''
            <div style="font-family: sans-serif; margin: 40px;">
                <h3 style="color: {'#28a745' if action == 'apply' else '#dc3545'};">Action Triggered!</h3>
                <p>Container ID: {container.short_id}</p>
                <a href="/logs/{container.short_id}">View Logs</a> | <a href="/">Home</a>
            </div>
        '''
    except Exception as e:
        return f"<h3>Docker Error:</h3><p>{str(e)}</p>"

@app.route('/logs/<short_id>')
def stream_logs(short_id):
    client = docker.from_env()
    container_id = active_deployments.get(short_id)
    if not container_id: return "Container not found."
    try:
        container = client.containers.get(container_id)
        logs = container.logs().decode("utf-8")
        return f'<html><head><meta http-equiv="refresh" content="5"></head><body style="background:#1e1e1e;color:#d4d4d4;"><pre>{logs}</pre></body></html>'
    except Exception as e:
        return f"Finished: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
