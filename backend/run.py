import sys
import asyncio
import uvicorn
from app.config import PORT, HOST

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    print(f"Starting AI Job Application Assistant Backend on http://{HOST}:{PORT}")
    print(f"Mock DOU.ua form:     http://localhost:{PORT}/mock-portals/dou_sample.html")
    print(f"Mock Djinni.co form:  http://localhost:{PORT}/mock-portals/djinni_sample.html")
    print(f"Mock Jobs.ge/HR.ge:   http://localhost:{PORT}/mock-portals/jobs_ge_sample.html")
    print(f"Mock JustJoin.it:     http://localhost:{PORT}/mock-portals/justjoin_sample.html")
    print(f"Mock Greenhouse form: http://localhost:{PORT}/mock-portals/greenhouse_sample.html")
    print(f"Mock Lever form:      http://localhost:{PORT}/mock-portals/lever_sample.html")
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False)
