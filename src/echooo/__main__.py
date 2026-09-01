from __future__ import annotations

import uvicorn

from echooo.config import Settings


def main() -> None:
    settings = Settings.load()
    uvicorn.run(
        "echooo.app:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
