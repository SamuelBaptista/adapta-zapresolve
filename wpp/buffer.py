import asyncio
import json
import logging

from typing import Dict, List, Optional
from datetime import datetime

import redis

from wpp.api.wpp_message import WppMessage
from wpp.api.wpp_webhook import UserWppWebhook
from wpp.memory import RedisManager

logger = logging.getLogger(__name__)


class MessageBuffer:
    """
    Buffer system that collects messages for a specific user and processes them together
    after a configurable delay period.
    """
    
    def __init__(self, redis_client: redis.Redis, wpp: WppMessage, buffer_delay: int = 5):
        """
        Initialize the message buffer.
        
        Args:
            redis_client: Redis client instance
            wpp: WppMessage instance for sending responses
            buffer_delay: Delay in seconds before processing buffered messages
        """
        self.redis_client = redis_client
        self.wpp = wpp
        self.buffer_delay = buffer_delay
        self.processing_tasks: Dict[str, asyncio.Task] = {}
        
    def _get_buffer_key(self, phone: str) -> str:
        """Get the Redis key for a user's message buffer."""
        return f"msg_buffer:{phone}"
    
    def _get_processing_key(self, phone: str) -> str:
        """Get the Redis key to check if a user is currently being processed."""
        return f"msg_processing:{phone}"
    
    async def add_message(self, phone: str, message_data: dict) -> bool:
        """
        Add a message to the buffer and start or extend the processing timer.
        
        Args:
            phone: User's phone number
            message_data: Complete message data from webhook
            
        Returns:
            bool: True if message was added to buffer, False if already processing
        """
        buffer_key = self._get_buffer_key(phone)
        processing_key = self._get_processing_key(phone)
        
        # Check if user is already being processed
        if self.redis_client.exists(processing_key):
            logger.info(f"User {phone} is already being processed, skipping buffer")
            return False
        
        # Add message to buffer with timestamp
        message_entry = {
            "data": message_data,
            "timestamp": datetime.now().isoformat(),
            "message_id": message_data.get("messageId")
        }
        
        # Get current buffer
        current_buffer = self.redis_client.get(buffer_key)
        buffer_messages = []
        
        if current_buffer:
            try:
                # Handle Redis response - it might be bytes or string
                buffer_str = current_buffer.decode('utf-8') if isinstance(current_buffer, bytes) else str(current_buffer)
                buffer_messages = json.loads(buffer_str)
            except (json.JSONDecodeError, TypeError, AttributeError):
                logger.warning(f"Invalid buffer data for {phone}, starting fresh")
                buffer_messages = []
        
        # Add new message
        buffer_messages.append(message_entry)
        
        # Save updated buffer with expiration
        self.redis_client.setex(
            buffer_key, 
            self.buffer_delay + 5,  # Buffer expires 5 seconds after processing delay
            json.dumps(buffer_messages)
        )
        
        # Cancel existing processing task if any
        if phone in self.processing_tasks:
            self.processing_tasks[phone].cancel()
        
        # Start new processing task
        self.processing_tasks[phone] = asyncio.create_task(
            self._process_buffer_after_delay(phone)
        )
        
        logger.info(f"Added message to buffer for {phone}, total messages: {len(buffer_messages)}")
        return True
    
    async def _process_buffer_after_delay(self, phone: str):
        """
        Wait for the buffer delay and then process all buffered messages.
        
        Args:
            phone: User's phone number
        """
        try:
            # Wait for buffer delay
            await asyncio.sleep(self.buffer_delay)
            
            # Mark user as being processed
            processing_key = self._get_processing_key(phone)
            self.redis_client.setex(processing_key, 30, "1")  # Processing lock for 30 seconds
            
            # Get buffered messages
            buffer_key = self._get_buffer_key(phone)
            buffer_data = self.redis_client.get(buffer_key)
            
            if not buffer_data:
                logger.warning(f"No buffer data found for {phone}")
                return
            
            try:
                # Handle Redis response - it might be bytes or string
                buffer_str = buffer_data.decode('utf-8') if isinstance(buffer_data, bytes) else str(buffer_data)
                buffer_messages = json.loads(buffer_str)
            except (json.JSONDecodeError, TypeError, AttributeError):
                logger.error(f"Invalid buffer data for {phone}")
                return
            
            if not buffer_messages:
                logger.warning(f"Empty buffer for {phone}")
                return
            
            logger.info(f"Processing {len(buffer_messages)} buffered messages for {phone}")
            
            # Process all messages together
            await self._process_buffered_messages(phone, buffer_messages)
            
            # Clean up buffer
            self.redis_client.delete(buffer_key)
            
        except asyncio.CancelledError:
            logger.info(f"Buffer processing cancelled for {phone}")
        except Exception as e:
            logger.error(f"Error processing buffer for {phone}: {e}")
        finally:
            # Remove processing lock
            processing_key = self._get_processing_key(phone)
            self.redis_client.delete(processing_key)
            
            # Remove from processing tasks
            if phone in self.processing_tasks:
                del self.processing_tasks[phone]
    
    async def _process_buffered_messages(self, phone: str, buffer_messages: List[dict]):
        """
        Process all buffered messages together.
        
        Args:
            phone: User's phone number
            buffer_messages: List of buffered message entries
        """
        try:
            # Create a combined message processor
            combined_processor = CombinedMessageProcessor(
                self.redis_client, 
                self.wpp, 
                phone, 
                buffer_messages
            )
            
            # Process all messages together
            await combined_processor.process_combined_messages()
            
        except Exception as e:
            logger.error(f"Error processing combined messages for {phone}: {e}")
            # Send error message to user
            self.wpp.send_message(
                message="Ocorreu um erro ao processar suas mensagens. Por favor, tente novamente.",
                number=phone
            )
    
    def is_processing(self, phone: str) -> bool:
        """Check if a user is currently being processed."""
        processing_key = self._get_processing_key(phone)
        return bool(self.redis_client.exists(processing_key))
    
    def get_buffer_size(self, phone: str) -> int:
        """Get the current buffer size for a user."""
        buffer_key = self._get_buffer_key(phone)
        buffer_data = self.redis_client.get(buffer_key)
        
        if not buffer_data:
            return 0
        
        try:
            # Handle Redis response - it might be bytes or string
            buffer_str = buffer_data.decode('utf-8') if isinstance(buffer_data, bytes) else str(buffer_data)
            buffer_messages = json.loads(buffer_str)
            return len(buffer_messages)
        except (json.JSONDecodeError, TypeError, AttributeError):
            return 0


def extract_user_input(message_data: dict, redis_client: redis.Redis, wpp: WppMessage) -> Optional[dict]:
    """
    Helper function to extract user input from a message without accessing private methods.
    
    Args:
        message_data: Raw message data from webhook
        redis_client: Redis client instance
        wpp: WppMessage instance
        
    Returns:
        dict: User input data or None if extraction fails
    """
    try:
        # Create a temporary webhook instance to extract user input
        webhook = UserWppWebhook(message_data, redis_client, wpp)
        
        # Extract input based on message type
        message_type = webhook.message_type
        
        if message_type == "text" and webhook.data.text:
            return {"text": webhook.data.text.message}
        elif message_type == "image" and webhook.data.image:
            return {
                "image": webhook.data.image.imageUrl,
                "text": webhook.data.image.caption,
            }
        elif message_type == "audio" and webhook.data.audio:
            return {"text": "[Audio message]"}  # Simplified for now
        elif message_type == "video" and webhook.data.video:
            return {
                "video": webhook.data.video.videoUrl,
                "text": webhook.data.video.caption,
            }
        elif message_type == "document" and webhook.data.document:
            return {
                "document": webhook.data.document.documentUrl,
                "text": webhook.data.document.caption,
                "file_name": webhook.data.document.fileName,
                "page_count": webhook.data.document.pageCount,
                "mime_type": webhook.data.document.mimeType,
                "title": webhook.data.document.title,
            }
        elif message_type == "buttonsResponseMessage" and webhook.data.buttonsResponseMessage:
            return {
                "text": webhook.data.buttonsResponseMessage.message,
                "button_id": webhook.data.buttonsResponseMessage.buttonId,
                "button_type": "list",
            }
        elif message_type == "buttonReply" and webhook.data.buttonReply:
            return {
                "text": webhook.data.buttonReply.message,
                "button_id": webhook.data.buttonReply.buttonId,
                "button_type": "action",
            }
        elif message_type == "interactive" and webhook.data.interactive:
            # Handle list reply (user selection from a list/radio selection)
            if webhook.data.interactive.type == "list_reply" and webhook.data.interactive.list_reply:
                selection_text = f"Seleção da lista: {webhook.data.interactive.list_reply.title}"
                if webhook.data.interactive.list_reply.description:
                    selection_text += f" - {webhook.data.interactive.list_reply.description}"
                selection_text += f" (ID: {webhook.data.interactive.list_reply.id})"
                
                return {
                    "text": selection_text,
                    "interactive_type": "list_reply",
                    "message_type": "list_selection",
                    "selected_id": webhook.data.interactive.list_reply.id,
                    "selected_title": webhook.data.interactive.list_reply.title,
                    "selected_description": webhook.data.interactive.list_reply.description or "",
                }
            else:
                # Handle incoming interactive messages from other bots
                interactive_text = ""
                if webhook.data.interactive.body and webhook.data.interactive.body.text:
                    interactive_text = webhook.data.interactive.body.text
                
                buttons = []
                if webhook.data.interactive.action and webhook.data.interactive.action.buttons:
                    for button in webhook.data.interactive.action.buttons:
                        buttons.append({
                            "id": button.id or "",
                            "title": button.title or "",
                            "type": button.type or ""
                        })
                
                sections = []
                if webhook.data.interactive.action and webhook.data.interactive.action.sections:
                    for section in webhook.data.interactive.action.sections:
                        sections.append({
                            "title": section.title or "",
                            "rows": section.rows or []
                        })
                
                return {
                    "text": interactive_text,
                    "interactive_type": webhook.data.interactive.type or "",
                    "message_type": "interactive_incoming",
                    "buttons": buttons,
                    "sections": sections
                }
        elif message_type == "listMessage" and webhook.data.listMessage:
            # Handle list messages with sections and options
            text_parts = []
            
            # Add main description
            if webhook.data.listMessage.description:
                text_parts.append(f"MENSAGEM: {webhook.data.listMessage.description}")
            
            # Add title if present
            if webhook.data.listMessage.title:
                text_parts.append(f"TÍTULO: {webhook.data.listMessage.title}")
            
            # Add button text
            if webhook.data.listMessage.buttonText:
                text_parts.append(f"BOTÃO: {webhook.data.listMessage.buttonText}")
            
            # Add footer if present
            if webhook.data.listMessage.footerText:
                text_parts.append(f"RODAPÉ: {webhook.data.listMessage.footerText}")
            
            # Process sections and options
            if webhook.data.listMessage.sections:
                options_text = []
                for section in webhook.data.listMessage.sections:
                    if section.title:
                        options_text.append(f"SEÇÃO: {section.title}")
                    
                    for option in section.options:
                        option_text = f"[{option.title}]({option.rowId})"
                        if option.description:
                            option_text += f" - {option.description}"
                        options_text.append(option_text)
                
                if options_text:
                    text_parts.append(f"OPÇÕES: {', '.join(options_text)}")
            
            # Combine all parts into single text field
            full_text = " | ".join(text_parts) if text_parts else ""
            
            return {
                "text": full_text,
                "message_type": "list_message_incoming",
                "sections": [
                    {
                        "title": section.title,
                        "options": [
                            {
                                "title": option.title,
                                "description": option.description,
                                "rowId": option.rowId
                            }
                            for option in section.options
                        ]
                    }
                    for section in webhook.data.listMessage.sections
                ]
            }
        else:
            return {"text": ""}
            
    except Exception as e:
        logger.error(f"Error extracting user input: {e}")
        return None


class CombinedMessageProcessor:
    """
    Processor that handles multiple messages together for more intelligent processing.
    """
    
    def __init__(self, redis_client: redis.Redis, wpp: WppMessage, phone: str, buffer_messages: List[dict]):
        self.redis_client = redis_client
        self.wpp = wpp
        self.phone = phone
        self.buffer_messages = buffer_messages
        self.cache = RedisManager(redis_client, phone)
        self.memory = self.cache.get_memory_dict()
        
    async def process_combined_messages(self):
        """Process all buffered messages together."""
        try:
            # Sort messages by timestamp
            sorted_messages = sorted(
                self.buffer_messages, 
                key=lambda x: x.get("timestamp", "")
            )
            
            # Combine text messages and handle special message types
            combined_text = []
            special_messages = []
            
            for msg_entry in sorted_messages:
                msg_data = msg_entry["data"]
                
                # Extract user input using helper function
                user_input = extract_user_input(msg_data, self.redis_client, self.wpp)
                
                if user_input:
                    # Handle text messages
                    if user_input.get("text"):
                        combined_text.append(user_input["text"])
                    
                    # Handle special messages (images, documents, etc.)
                    webhook = UserWppWebhook(msg_data, self.redis_client, self.wpp)
                    if webhook.message_type in ["image", "document", "audio", "video", "buttonsResponseMessage", "buttonReply", "interactive", "listMessage"]:
                        special_messages.append({
                            "type": webhook.message_type,
                            "input": user_input,
                            "timestamp": msg_entry["timestamp"]
                        })
            
            # Create combined text message
            if combined_text:
                combined_message = " ".join(combined_text)
                
                # Process the combined message
                await self._process_combined_text(combined_message, special_messages)
            
            # If no text messages, handle special messages
            elif special_messages:
                await self._process_special_messages(special_messages)
            
            else:
                logger.warning(f"No processable messages found for {self.phone}")
                
        except Exception as e:
            logger.error(f"Error in combined message processing: {e}")
            raise
    
    async def _process_combined_text(self, combined_text: str, special_messages: List[dict]):
        """Process combined text messages with context from special messages."""
        try:
            # Create a single webhook processor with combined text
            first_msg = self.buffer_messages[0]["data"].copy()
            
            # Add context about multiple messages
            if len(self.buffer_messages) > 1:
                context_msg = f"[Processando {len(self.buffer_messages)} mensagens recebidas] "
                combined_text = context_msg + combined_text
            
            # Modify the first message to contain combined text
            first_msg["text"] = {"message": combined_text}
            first_msg["type"] = "text"
            
            # Ensure phone number is preserved in the message
            if "phone" not in first_msg:
                first_msg["phone"] = self.phone
            
            # Create webhook processor
            webhook = UserWppWebhook(first_msg, self.redis_client, self.wpp)
            
            # Process the combined message
            response = webhook._process_wpp_message()
            
            # Sync shared conversation data after processing
            if hasattr(webhook, 'cache') and webhook.cache:
                webhook.cache.set_memory_dict(webhook.memory)
            
            # Send response if available
            if response:
                self._send_response(response)
                
        except Exception as e:
            logger.error(f"Error processing combined text: {e}")
            raise
    
    async def _process_special_messages(self, special_messages: List[dict]):
        """Process special messages (images, documents, etc.)."""
        try:
            # For now, process special messages individually
            # In the future, this could be enhanced to handle multiple images, etc.
            
            for special_msg in special_messages:
                # Create a webhook processor for each special message
                msg_data = None
                
                # Find the original message data
                for msg_entry in self.buffer_messages:
                    webhook = UserWppWebhook(msg_entry["data"], self.redis_client, self.wpp)
                    if webhook.message_type == special_msg["type"]:
                        msg_data = msg_entry["data"]
                        break
                
                if msg_data:
                    webhook = UserWppWebhook(msg_data, self.redis_client, self.wpp)
                    response = webhook._process_wpp_message()
                    
                    if response:
                        self._send_response(response)
                        
        except Exception as e:
            logger.error(f"Error processing special messages: {e}")
            raise
    
    def _send_response(self, response: dict):
        """Send response to user."""
        try:
            message_type = {
                "message": self.wpp.send_message,
                "image": self.wpp.send_image,
                "button_list": self.wpp.send_buttons_list,
                "button_action": self.wpp.send_buttons_action,
            }
            
            response['number'] = self.phone
            response_type = response.pop('type')
            
            send_function = message_type.get(response_type)
            if send_function:
                send_function(**response)
                
        except Exception as e:
            logger.error(f"Error sending response: {e}") 