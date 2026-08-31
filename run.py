import uvicorn

from app.config.settings import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.agent_host,
        port=settings.agent_port,
    )
