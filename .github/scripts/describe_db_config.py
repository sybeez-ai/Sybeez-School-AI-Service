"""Print non-secret database settings from an ECS task definition."""

import json
import sys
from urllib.parse import parse_qs, unquote, urlsplit

SAFE_VALUES = ("APP_ENV", "AWS_REGION", "AI_PORT", "LOG_LEVEL", "DB_IAM_AUTH", "DB_SSL_CA")


def summarize_url(url: str) -> None:
    parts = urlsplit(url)
    userinfo, separator, _host = parts.netloc.rpartition("@")
    if separator:
        username, _colon, password = userinfo.partition(":")
    else:
        username, password = "", ""
    query = parse_qs(parts.query)
    tls = []
    for key in ("sslmode", "ssl"):
        values = query.get(key) or []
        if values:
            tls.append(f"{key}={values[0]}")
    print(f"database driver={parts.scheme}")
    print(f"database user={unquote(username)}")
    print(f"database has_password={bool(password)}")
    print(f"database has_percent={'%' in url}")
    print("database tls_query=" + (",".join(tls) if tls else "none"))


def main(path: str) -> None:
    document = json.loads(open(path, encoding="utf-8").read())
    containers = document.get("containerDefinitions") or []
    for container in containers:
        print(f"container {container.get('name')}")
        for item in container.get("environment") or []:
            name = str(item.get("name") or "")
            if name == "DATABASE_URL":
                summarize_url(str(item.get("value") or ""))
            elif name in SAFE_VALUES:
                print(f"{name}={item.get('value')}")
            elif name:
                print(f"env {name}")
        for item in container.get("secrets") or []:
            name = str(item.get("name") or "")
            if name:
                print(f"secret {name}")


if __name__ == "__main__":
    main(sys.argv[1])
