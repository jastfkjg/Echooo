"""Create the first owner interactively without exposing a public setup endpoint."""
from getpass import getpass

from echooo.auth import Auth
from echooo.config import Settings
from echooo.contracts import Credentials
from echooo.database import Store


def main():
    store = Store(Settings.load().database_url)
    try:
        auth = Auth(store)
        if not auth.needs_setup():
            raise SystemExit("This workspace is already set up.")
        name = input("Owner name: ").strip()
        password = getpass("Password: ")
        if len(password) < 16:
            raise SystemExit("Use a password of at least 16 characters.")
        if password != getpass("Confirm password: "):
            raise SystemExit("Passwords do not match.")
        credentials = Credentials(name=name, password=password)
        _, token = auth.setup(credentials.name, credentials.password)
        auth.revoke(token)
        print("Owner created. Sign in through the configured website.")
    finally:
        store.close()


if __name__ == "__main__":
    main()
