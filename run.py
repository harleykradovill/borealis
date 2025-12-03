from os import getenv

from app import create_app


def main() -> None:
    host = getenv("HOST", "127.0.0.1")
    port = int(getenv("PORT", "2929"))

    app = create_app()
    app.run(host=host, port=port)


if __name__ == "__main__":
    main()