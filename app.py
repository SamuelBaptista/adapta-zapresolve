import ngrok
import os
import redis

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from wpp.api.wpp_message import WppMessage
from wpp.api.wpp_webhook import UserWppWebhook

from wpp.memory import RedisManager

from wpp.genai.workflows.step1 import step1_workflow


app = FastAPI()

redis_client = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True
)


@app.post("/wpp_webhook")
async def recieve_wpp_message(
    request: Request,
):

    token = request.headers.get("z-api-token")

    wpp_id = os.getenv("WPP_INSTANCE_ID")
    wpp_token = os.getenv("WPP_INSTANCE_TOKEN")
    wpp_secret = os.getenv("WPP_CLIENT_TOKEN")

    if token != wpp_token:
        return JSONResponse("Permission Denied", status_code=403)
    
    wpp = WppMessage(wpp_id, wpp_token, wpp_secret)
    data = await request.json()

    print(data)

    if data.get('notification') == "REVOKE":
        return JSONResponse("Mensagem processada com sucesso!", status_code=200)
    
    redis_manager = RedisManager(redis_client, "wpp_webhook")

    if redis_manager.redis.exists(message_id := data.get('messageId')):
        return JSONResponse("Message already processed", status_code=200)

    if data.get("isGroup"):
        return JSONResponse("Group messages are not supported", status_code=400)
    
    hook = UserWppWebhook(data, redis_client, wpp)
    hook.process_event(step1_workflow)

    redis_manager.redis.set(message_id, "1", ex=60)
    return JSONResponse("Mensagem processada com sucesso!", status_code=200)


async def setup_listener():
    listen = f"localhost:8000"
    token = os.getenv("NGROK_AUTH_TOKEN")

    session = await ngrok.SessionBuilder().authtoken(token).connect()

    listener = await (
        session.http_endpoint()
        .domain('humorous-inviting-oyster.ngrok-free.app')
        .listen()
    )

    listener.forward(listen)

if __name__ == "__main__":
    import asyncio
    import uvicorn

    try:
        running_loop = asyncio.get_running_loop()
        running_loop.create_task(setup_listener())
    except RuntimeError:
        asyncio.run(setup_listener())

    uvicorn.run("app:app", host="localhost", port=8000, workers=1)