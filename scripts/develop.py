import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*arguments: str) -> None:
    executable = shutil.which(arguments[0])
    if executable is None:
        raise RuntimeError(f"Required command is not installed: {arguments[0]}")
    subprocess.run([executable, *arguments[1:]], cwd=ROOT, check=True)


def main(command: str) -> None:
    match command:
        case "setup":
            for tool in ("poetry", "npm", "node", "docker"):
                run(tool, "--version")
            run("poetry", "sync")
            run("npm", "ci")
            run("poetry", "run", "pre-commit", "install")
            if not (ROOT / ".env").exists():
                shutil.copyfile(ROOT / ".env.example", ROOT / ".env")
        case "run":
            run("docker", "compose", "build")
            run("docker", "compose", "up", "-d", "--wait", "postgres", "rabbitmq")
            run("docker", "compose", "run", "--rm", "api", "alembic", "upgrade", "head")
            run("docker", "compose", "up", "-d", "--wait", "api", "consumer", "outbox")
        case "check":
            run("poetry", "check", "--lock")
            run("poetry", "run", "pre-commit", "run", "--all-files")
        case "test":
            run("poetry", "run", "pytest", "-m", "not integration and not e2e")
        case "test-integration":
            run("docker", "compose", "up", "-d", "--wait", "postgres", "rabbitmq")
            run("poetry", "run", "pytest", "-m", "integration")
        case "migrate":
            run("poetry", "run", "alembic", "upgrade", "head")
        case "build":
            run("poetry", "build")
        case "logs":
            run("docker", "compose", "logs", "-f", "--tail", "100")
        case "down":
            run("docker", "compose", "down")
        case _:
            raise ValueError(f"Unknown command: {command}")


if __name__ == "__main__":
    main(sys.argv[1])
