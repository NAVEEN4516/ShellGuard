"""
Test safety classification matrix across dangerous vs safe commands.
"""

import pytest
from daemon.engine import ShellGuardEngine


@pytest.fixture(scope="module")
def engine():
    eng = ShellGuardEngine()
    eng.initialize()
    return eng


DANGEROUS_COMMANDS = [
    ("kubectl delete namespace ingress-nginx", "INC-402"),
    ("kubectl delete deployment ingress-nginx-controller -n ingress-nginx", "INC-402"),
    ("terraform destroy -target=aws_db_instance.primary", "INC-105"),
    ("terraform apply -destroy -auto-approve", "INC-105"),
    ("docker system prune -a --volumes", "INC-308"),
    ("docker volume rm my_volume", "INC-308"),
    ("aws s3api put-bucket-acl --bucket prod --acl public-read", "INC-512"),
    ("git push --force origin main", "INC-770"),
    ("rm -rf /", "INC-204"),
    ("rm -rf /*", "INC-204"),
    ("rm -rf --no-preserve-root /", "INC-204"),
    ("sudo rm -rf /", "INC-204"),
    ('FOO="destructive test" rm -rf /', "INC-204"),
]

SAFE_COMMANDS = [
    "ls -la",
    "pwd",
    "git status",
    "git diff",
    "git log -n 5",
    "git commit -m 'feat: next-level safety'",
    "kubectl get pods -n production",
    "kubectl describe service web-gateway",
    "kubectl apply -f ingress-deployment.yaml",
    "kubectl delete pod test-worker-pod",
    "terraform plan",
    "terraform show",
    "terraform init",
    "docker ps",
    "docker logs container_123",
    "docker run -it ubuntu bash",
    "docker rm stopped_container",
    "rm file.txt",
    "rm -f ./test.log",
    "rm -rf ./build",
    "aws s3 ls",
    "helm list",
    "gcloud compute instances list",
    "az vm list",
]


@pytest.mark.parametrize("cmd,expected_incident", DANGEROUS_COMMANDS)
def test_dangerous_commands_are_blocked(engine, cmd, expected_incident):
    res = engine.evaluate(cmd)
    assert res.status == "BLOCKED", f"Expected '{cmd}' to be BLOCKED, got {res.status}"
    assert res.is_intercepted is True
    assert res.matched_incident_id == expected_incident
    assert res.safe_alternative is not None


@pytest.mark.parametrize("cmd", SAFE_COMMANDS)
def test_safe_commands_are_allowed(engine, cmd):
    res = engine.evaluate(cmd)
    assert res.status == "PASSED", f"Expected '{cmd}' to PASS, got {res.status} ({res.recommendation})"
    assert res.is_intercepted is False
