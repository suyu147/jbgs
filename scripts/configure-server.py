"""Create private Docker settings once; existing deployments are never overwritten."""
from pathlib import Path
import secrets


def main() -> None:
    target = Path(__file__).resolve().parents[1] / ".env"
    if target.exists():
        print("Existing .env preserved. Edit it to update deployment settings.")
        return
    settings = {
        "WEB_PORT": "5175",
        "FRONTEND_ORIGIN": "http://localhost:5175",
        "MYSQL_ROOT_PASSWORD": secrets.token_hex(24),
        "MYSQL_PASSWORD": secrets.token_hex(24),
        "NEO4J_PASSWORD": secrets.token_hex(24),
        "AUTH_SECRET": secrets.token_hex(48),
        "PERSONAL_USERNAME": "demo_user",
        "PERSONAL_PASSWORD": "Career2026",
        "ENTERPRISE_USERNAME": "demo_enterprise",
        "ENTERPRISE_PASSWORD": "Enterprise2026",
        "ADMIN_USERNAME": "demo_admin",
        "ADMIN_PASSWORD": "Admin2026",
        "AGENT_PROVIDER": "rules",
        "AGENT_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
        "INTERVIEW_ASR_API_KEY": "",
    }
    with target.open("x", encoding="utf-8", newline="\n") as file:
        file.write("\n".join(f"{key}={value}" for key, value in settings.items()) + "\n")
    try:
        target.chmod(0o600)
    except OSError:
        pass
    print("Created private .env. Next: docker compose up -d --build")


if __name__ == "__main__":
    main()
