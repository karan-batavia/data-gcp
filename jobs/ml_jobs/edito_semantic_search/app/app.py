from loguru import logger
from quart import Quart
from quart_cors import cors

from app.routes import api

app = Quart(__name__)
app = cors(app, allow_origin="*")

app.register_blueprint(api)


if __name__ == "__main__":
    logger.info("startup", extra={"event": "startup", "response": "ready"})
    app.run()
