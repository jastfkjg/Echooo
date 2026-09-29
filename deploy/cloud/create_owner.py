"""Provision owner workspaces interactively through trusted server access."""
import argparse
from getpass import getpass

from pydantic import ValidationError

from echooo.auth import Auth, AuthError
from echooo.config import Settings
from echooo.contracts import Credentials
from echooo.database import Store


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--additional', action='store_true',
        help='Create an independent account without changing existing workspaces.')
    args = parser.parse_args(argv)
    store = Store(Settings.load().database_url)
    try:
        auth = Auth(store)
        if not args.additional and not auth.needs_setup():
            raise SystemExit("This workspace is already set up. Use --additional to create another account.")
        name = input("Owner name: ").strip()
        password = getpass("Password: ")
        if len(password) < 16:
            raise SystemExit("Use a password of at least 16 characters.")
        if password != getpass("Confirm password: "):
            raise SystemExit("Passwords do not match.")
        try:
            credentials = Credentials(name=name, password=password)
            auth.create_owner(credentials.name, credentials.password, first_only=not args.additional)
        except ValidationError:
            raise SystemExit("Use a name of 2–60 characters and a password of 16–200 characters.") from None
        except AuthError as exc:
            raise SystemExit(str(exc)) from None
        print("Owner created. Sign in through the configured website.")
    finally:
        store.close()


if __name__ == "__main__":
    main()
