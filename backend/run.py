import sys
import asyncio
import uvicorn
from app.config import PORT, HOST

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    print(f"Starting AI Job Application Assistant Backend on http://{HOST}:{PORT}")
    print(f"API Documentation (Swagger): http://localhost:{PORT}/docs")
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False)
