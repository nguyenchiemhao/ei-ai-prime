from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from ei_ai.api.validation import install_validation_handler


class Credentials(BaseModel):
    email: str
    password: str


def test_validation_error_does_not_echo_input() -> None:
    app = FastAPI()
    install_validation_handler(app)

    @app.post("/probe")
    def probe(body: Credentials) -> dict[str, str]:
        return {"ok": "yes"}

    response = TestClient(app).post("/probe", json={"password": "Sup3r-secret-pw"})

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_request"}
    assert "Sup3r-secret-pw" not in response.text
