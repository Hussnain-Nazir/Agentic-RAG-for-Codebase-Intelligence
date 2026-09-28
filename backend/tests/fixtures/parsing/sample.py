from fastapi import FastAPI

app = FastAPI()


def helper() -> str:
    return "ok"


class Greeter:
    def greet(self) -> str:
        return helper()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": helper()}
