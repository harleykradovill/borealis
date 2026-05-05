"""
Load environment variables for host and port, creates the Flask app instance,
and starts the development server.

Environment Variables
---------------------
HOST: The interface/IP the server should bind to. Defaults to "127.0.0.1".
PORT: The port number the server should listen on. Defaults to "2929".
"""

from os import getenv
from app import create_app


def main() -> None:
    """
    Resolve host and port from env variables, instantiate app via
    create_app(), and start the server.
    """
    host = getenv("HOST", "127.0.0.1")
    port = int(getenv("PORT", "2929"))

    app = create_app()
    app.run(host=host, port=port)


if __name__ == "__main__":
    main()
