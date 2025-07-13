import ngrok
import os
import redis
import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from wpp.api.wpp_message import WppMessage
from wpp.api.wpp_webhook import UserWppWebhook
from wpp.buffer import MessageBuffer
from wpp.memory import RedisManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

redis_client = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True
)

# Global message buffer instance
message_buffer = None


def get_message_buffer():
    """Get or create the global message buffer instance."""
    global message_buffer
    if message_buffer is None:
        # Get required environment variables
        wpp_id = os.getenv("WPP_INSTANCE_ID")
        wpp_token = os.getenv("WPP_INSTANCE_TOKEN")
        wpp_secret = os.getenv("WPP_CLIENT_TOKEN")
        
        if not wpp_id or not wpp_token or not wpp_secret:
            logger.error("Missing required WhatsApp API credentials for buffer initialization")
            # Create with empty strings as fallback
            wpp_id = wpp_id or ""
            wpp_token = wpp_token or ""
            wpp_secret = wpp_secret or ""
        
        # Create a dummy WppMessage instance for the buffer
        # The actual WppMessage instances will be created per request
        dummy_wpp = WppMessage(wpp_id, wpp_token, wpp_secret)
        message_buffer = MessageBuffer(redis_client, dummy_wpp, buffer_delay=5)
    return message_buffer


@app.post("/wpp_webhook")
async def recieve_wpp_message(
    request: Request,
):
    token = request.headers.get("z-api-token")

    wpp_id = os.getenv("WPP_INSTANCE_ID")
    wpp_token = os.getenv("WPP_INSTANCE_TOKEN")
    wpp_secret = os.getenv("WPP_CLIENT_TOKEN")

    if not wpp_id or not wpp_token or not wpp_secret:
        logger.error("Missing required WhatsApp API credentials")
        return JSONResponse("Missing API credentials", status_code=500)

    if token != wpp_token:
        return JSONResponse("Permission Denied", status_code=403)
    
    data = await request.json()

    # Handle revoked messages
    if data.get('notification') == "REVOKE":
        return JSONResponse("Mensagem processada com sucesso!", status_code=200)
    
    # Check for duplicate messages
    redis_manager = RedisManager(redis_client, "wpp_webhook")
    message_id = data.get('messageId')
    
    if message_id and redis_manager.redis.exists(message_id):
        return JSONResponse("Message already processed", status_code=200)

    # Skip group messages
    if data.get("isGroup"):
        return JSONResponse("Group messages are not supported", status_code=400)
    
    # Extract phone number
    phone = data.get("phone")
    if not phone:
        return JSONResponse("Phone number required", status_code=400)

    try:
        # Create WppMessage instance for this request
        wpp = WppMessage(wpp_id, wpp_token, wpp_secret)
        
        # Get the message buffer
        buffer = get_message_buffer()
        buffer.wpp = wpp  # Update the WppMessage instance
        
        # Add message to buffer
        buffer_added = await buffer.add_message(phone, data)
        
        if buffer_added:
            logger.info(f"Message added to buffer for {phone}")
            
            # Mark message as processed to prevent duplicates
            if message_id:
                redis_manager.redis.set(message_id, "1", ex=300)  # 5 minutes expiry
            
            return JSONResponse("Mensagem adicionada ao buffer", status_code=200)
        else:
            # User is already being processed, process immediately as fallback
            logger.info(f"User {phone} already being processed, falling back to immediate processing")
            
            hook = UserWppWebhook(data, redis_client, wpp)
            hook.process_event()
            
            # Mark message as processed
            if message_id:
                redis_manager.redis.set(message_id, "1", ex=300)
            
            return JSONResponse("Mensagem processada imediatamente", status_code=200)
            
    except Exception as e:
        logger.error(f"Error processing webhook message: {e}")
        return JSONResponse("Erro interno do servidor", status_code=500)


@app.get("/buffer/status/{phone}")
async def get_buffer_status(phone: str):
    """Get buffer status for a specific phone number."""
    try:
        buffer = get_message_buffer()
        
        status = {
            "phone": phone,
            "buffer_size": buffer.get_buffer_size(phone),
            "is_processing": buffer.is_processing(phone)
        }
        
        return JSONResponse(status, status_code=200)
    except Exception as e:
        logger.error(f"Error getting buffer status: {e}")
        return JSONResponse({"error": "Internal server error"}, status_code=500)


@app.get("/buffer/stats")
async def get_buffer_stats():
    """Get overall buffer statistics."""
    try:
        buffer = get_message_buffer()
        
        stats = {
            "active_processing_tasks": len(buffer.processing_tasks),
            "buffer_delay_seconds": buffer.buffer_delay
        }
        
        return JSONResponse(stats, status_code=200)
    except Exception as e:
        logger.error(f"Error getting buffer stats: {e}")
        return JSONResponse({"error": "Internal server error"}, status_code=500)


async def setup_listener():
    listen = f"localhost:8000"
    token = os.getenv("NGROK_AUTH_TOKEN")

    if not token:
        logger.error("NGROK_AUTH_TOKEN not provided")
        return

    session = await ngrok.SessionBuilder().authtoken(token).connect()

    listener = await (
        session.http_endpoint()
        .domain('humorous-inviting-oyster.ngrok-free.app')
        .listen()
    )

    listener.forward(listen)
    logger.info("Ngrok tunnel established")


if __name__ == "__main__":
    import uvicorn

    try:
        # Check if we're already in an event loop
        loop = asyncio.get_running_loop()
        # If we're in a running loop, create the task
        loop.create_task(setup_listener())
    except RuntimeError:
        # No running loop, so we can run the async function
        asyncio.run(setup_listener())

    uvicorn.run("app:app", host="localhost", port=8000, workers=1)