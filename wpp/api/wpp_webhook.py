import requests
import pdf2image
import io
import base64
import logging
from datetime import datetime
from typing import Optional

from PIL import Image

from repenseai.genai.agent import Agent
from repenseai.genai.tasks.api import Task

from wpp.schemas.wpp_webhook import WppPayload
from wpp.api.wpp_message import WppMessage
from wpp.memory import RedisManager

from wpp.genai.prompts.step1 import PROMPT
from wpp.genai.prompts.step2 import PROMPT2

from pydantic import BaseModel

import redis

logger = logging.getLogger(__name__)


class ExtractedData(BaseModel):
    nome: str
    CPF: str
    telefone: str
    problema: str
    identificador: Optional[str] = None


class Step1Response(BaseModel):
    reasoning: list[str]
    validation_status: str
    mensagem: str
    extracted_data: ExtractedData


class Step2Response(BaseModel):
    reasoning: list[str]
    flag: str
    message: str


class UserWppWebhook:
    def __init__(
        self,
        data: dict, 
        redis_client: redis.Redis,
        wpp: WppMessage,
    ):
        self.data = WppPayload(**data)
        self.wpp = wpp

        self.redis_client = redis_client
        
        self.full_name = self.data.senderName
        self.name = self.data.senderName.split(' ')[0]
        self.message_type = self.data.get_payload_type()

        self.selector = None
        self.user_input = None

        self.cache = None
        self.memory = {}

        self.memory_time = 3600

    def __build_memory(self):
        self.cache = RedisManager(self.redis_client, self.data.phone)
        self.memory = self.cache.get_memory_dict()

        self.memory['chat_history'] = self.memory.get('chat_history', [])
        self.memory['chat_history2'] = self.memory.get('chat_history2', [])
        
        # Initialize shared conversation if not exists
        if 'shared_conversation' not in self.memory:
            self.memory['shared_conversation'] = {
                'participants': {
                    'user': self.data.phone if self.data.phone != "551130039303" else 'unknown',
                    'customer_service': "551130039303",
                    'agent': 'intermediary_agent'
                },
                'conversation_history': [],
                'current_context': {
                    'status': 'active',
                    'last_speaker': None
                }
            }

        self.memory['step'] = self.memory.get('step', 1)
    
    def __add_to_shared_conversation(self, message: str, speaker_role: str, message_type: str = "text"):
        """Add a message to the shared conversation history with role tracking."""
        if 'shared_conversation' not in self.memory:
            return
            
        conversation_entry = {
            'timestamp': datetime.now().isoformat(),
            'speaker_role': speaker_role,  # 'user', 'customer_service', or 'agent'
            'speaker_phone': self.data.phone,
            'message': message,
            'message_type': message_type
        }
        
        self.memory['shared_conversation']['conversation_history'].append(conversation_entry)
        self.memory['shared_conversation']['current_context']['last_speaker'] = speaker_role
        
        # Keep conversation history manageable (last 50 messages)
        if len(self.memory['shared_conversation']['conversation_history']) > 50:
            self.memory['shared_conversation']['conversation_history'] = \
                self.memory['shared_conversation']['conversation_history'][-50:]
    
    def __get_conversation_context_for_agent(self) -> str:
        """Get formatted conversation context for the agent to understand the full conversation."""
        if 'shared_conversation' not in self.memory:
            return ""
            
        shared_conv = self.memory['shared_conversation']
        context_parts = []
        
        # Add participant info
        participants = shared_conv.get('participants', {})
        context_parts.append(f"PARTICIPANTES DA CONVERSA:")
        context_parts.append(f"- Usuário: {participants.get('user', 'unknown')}")
        context_parts.append(f"- Atendimento Porto Seguro: {participants.get('customer_service', 'unknown')}")
        context_parts.append(f"- Agente Intermediário (você): {participants.get('agent', 'intermediary_agent')}")
        
        # Add current context and status
        current_context = shared_conv.get('current_context', {})
        context_parts.append(f"\nSTATUS DA CONVERSA: {current_context.get('status', 'active')}")
        context_parts.append(f"ÚLTIMO A FALAR: {current_context.get('last_speaker', 'unknown')}")
        
        if current_context.get('user_request'):
            context_parts.append(f"\nSOLICITAÇÃO ORIGINAL DO USUÁRIO:")
            user_request = current_context['user_request']
            if isinstance(user_request, dict):
                for key, value in user_request.items():
                    context_parts.append(f"- {key}: {value}")
            else:
                context_parts.append(f"- {user_request}")
        
        # Add conversation flow summary
        history = shared_conv.get('conversation_history', [])
        if history:
            context_parts.append(f"\nRESUMO DA CONVERSA ({len(history)} mensagens trocadas):")
            
            # Count messages by speaker
            user_msgs = len([h for h in history if h.get('speaker_role') == 'user'])
            cs_msgs = len([h for h in history if h.get('speaker_role') == 'customer_service'])
            agent_msgs = len([h for h in history if h.get('speaker_role') == 'agent'])
            
            context_parts.append(f"- Mensagens do usuário: {user_msgs}")
            context_parts.append(f"- Mensagens do atendimento: {cs_msgs}")
            context_parts.append(f"- Suas mensagens como agente: {agent_msgs}")
            
            context_parts.append(f"\nÚLTIMAS 10 MENSAGENS:")
            for entry in history[-10:]:  # Show last 10 messages
                speaker = entry.get('speaker_role', 'unknown')
                message = entry.get('message', '')
                timestamp = entry.get('timestamp', '')
                context_parts.append(f"[{timestamp[-8:-3] if timestamp else ''}] {speaker.upper()}: {message}")
        
        # Add next steps suggestion
        context_parts.append(f"\nSUA FUNÇÃO COMO AGENTE INTERMEDIÁRIO:")
        context_parts.append(f"- Facilitar a comunicação entre o usuário e o atendimento Porto Seguro")
        context_parts.append(f"- Traduzir/clarificar mensagens quando necessário")
        context_parts.append(f"- Manter o contexto da conversa para ambas as partes")
        context_parts.append(f"- Usar as ferramentas send_message(message, to='user') ou send_message(message, to='bot')")
        
        return "\n".join(context_parts)
        
    def __get_text_input(self):
        if self.data.text and self.data.text.message:
            return {"text": self.data.text.message}
        return {"text": ""}
    
    def __get_image_input(self):
        if self.data.image:
            return {
                "image": self.data.image.imageUrl or "",
                "text": self.data.image.caption or "",
            }
        return {"text": ""}

    def __get_audio_input(self):
        if not self.data.audio or not self.data.audio.audioUrl:
            return {"text": ""}
            
        audio_selector = Agent(
            model="whisper-1", 
            model_type="audio", 
        )

        audio_task = Task(
            agent=audio_selector,
        )

        try:
            audio = requests.get(self.data.audio.audioUrl).content
            transcription = audio_task.run({"audio": audio})

            if isinstance(transcription, dict):
                return {
                    "text": transcription.get("response", ""), 
                    "audio_response": transcription
                }
            else:
                return {
                    "text": str(transcription), 
                    "audio_response": transcription
                }
        except Exception as e:
            logger.error(f"Error processing audio: {e}")
            return {"text": ""}
    
    def __get_video_input(self):
        if self.data.video:
            return {
                "video": self.data.video.videoUrl or "",
                "text": self.data.video.caption or "",
            }
        return {"text": ""}
    
    def __get_document_input(self):
        if self.data.document:
            return {
                "document": self.data.document.documentUrl or "",
                "text": self.data.document.caption or "",
                "file_name": self.data.document.fileName or "",
                "page_count": self.data.document.pageCount or 0,
                "mime_type": self.data.document.mimeType or "",
                "title": self.data.document.title or "",
            }
        return {"text": ""}
    
    def __get_location_input(self):
        if self.data.location:
            return {
                "latitude": self.data.location.latitude or 0.0,
                "longitude": self.data.location.longitude or 0.0,
            }
        return {"text": ""}
    
    def __get_contact_input(self):
        if self.data.contact:
            return {
                "name": getattr(self.data.contact, 'name', '') or "",
                "phone": getattr(self.data.contact, 'phone', '') or "",
            }
        return {"text": ""}

    def __get_payment_input(self):
        if self.data.payment:
            return {
                "value": self.data.payment.value or 0,
                "currency": self.data.payment.currencyCode or "",
                "status": self.data.payment.status or "",
                "transaction_status": self.data.payment.transactionStatus or "",
            }
        return {"text": ""}

    def __get_button_list_input(self):
        """Handle button list messages (buttonsResponseMessage)"""
        if self.data.buttonsResponseMessage:
            return {
                "text": self.data.buttonsResponseMessage.message or "",
                "button_id": self.data.buttonsResponseMessage.buttonId or "",
                "button_type": "list",
                "user_selection": self.data.buttonsResponseMessage.message or "",
            }
        return {"text": ""}

    def __get_button_action_input(self):
        """Handle button action messages (buttonReply)"""
        if self.data.buttonReply:
            return {
                "text": self.data.buttonReply.message or "",
                "button_id": self.data.buttonReply.buttonId or "",
                "reference_message_id": self.data.buttonReply.referenceMessageId or "",
                "button_type": "action",
                "user_selection": self.data.buttonReply.message or "",
            }
        return {"text": ""}

    def __get_interactive_input(self):
        """Handle incoming interactive messages (messages with buttons from other bots)"""
        if self.data.interactive:
            # Check if this is a button reply (user clicked a button - HYDRATED BUTTONS)
            if self.data.interactive.type == "button_reply" and self.data.interactive.button_reply:
                # This is a user's button click from a hydrated button
                button_text = f"Botão clicado: {self.data.interactive.button_reply.title}"
                if self.data.interactive.button_reply.id:
                    button_text += f" (ID: {self.data.interactive.button_reply.id})"
                
                return {
                    "text": button_text,
                    "interactive_type": "button_reply",
                    "message_type": "button_click",
                    "button_id": self.data.interactive.button_reply.id,
                    "button_title": self.data.interactive.button_reply.title,
                    "button_payload": self.data.interactive.button_reply.payload or '',
                }
            
            # Check if this is a list reply (user selection from a list)
            if self.data.interactive.type == "list_reply" and self.data.interactive.list_reply:
                # This is a user's selection from a list (radio selection)
                selection_text = f"Seleção da lista: {self.data.interactive.list_reply.title}"
                if self.data.interactive.list_reply.description:
                    selection_text += f" - {self.data.interactive.list_reply.description}"
                selection_text += f" (ID: {self.data.interactive.list_reply.id})"
                
                return {
                    "text": selection_text,
                    "interactive_type": "list_reply",
                    "message_type": "list_selection",
                    "selected_id": self.data.interactive.list_reply.id,
                    "selected_title": self.data.interactive.list_reply.title,
                    "selected_description": self.data.interactive.list_reply.description or "",
                }
            
            # Handle incoming interactive messages (messages with buttons/lists from other bots)
            # Build comprehensive text content for model context
            text_parts = []
            
            # Extract header info
            if self.data.interactive.header:
                if self.data.interactive.header.text:
                    text_parts.append(f"CABEÇALHO: {self.data.interactive.header.text}")
            
            # Extract body text (main message)
            if self.data.interactive.body:
                if self.data.interactive.body.text:
                    text_parts.append(f"MENSAGEM: {self.data.interactive.body.text}")
            
            # Extract footer info
            if self.data.interactive.footer:
                if self.data.interactive.footer.text:
                    text_parts.append(f"RODAPÉ: {self.data.interactive.footer.text}")
            
            # Extract action buttons/lists
            if self.data.interactive.action:
                # Handle buttons
                if self.data.interactive.action.buttons:
                    button_texts = []
                    for button in self.data.interactive.action.buttons:
                        button_title = button.title or ""
                        button_id = button.id or ""
                        if button_title:
                            button_texts.append(f"[{button_title}]({button_id})")
                    if button_texts:
                        text_parts.append(f"BOTÕES DISPONÍVEIS: {', '.join(button_texts)}")
                
                # Handle list sections
                if self.data.interactive.action.sections:
                    section_texts = []
                    for section in self.data.interactive.action.sections:
                        section_title = section.title or ""
                        if section_title:
                            section_texts.append(section_title)
                            # Add rows if available
                            if section.rows:
                                for row in section.rows:
                                    if isinstance(row, dict) and row.get('title'):
                                        section_texts.append(f"  - {row['title']}")
                                    elif hasattr(row, 'title'):
                                        # Handle object with title attribute
                                        title_value = getattr(row, 'title', '')
                                        if title_value:
                                            section_texts.append(f"  - {title_value}")
                    if section_texts:
                        text_parts.append(f"SEÇÕES/LISTAS: {', '.join(section_texts)}")
            
            # FALLBACK: Try to extract any additional fields we might have missed
            # This helps handle unknown interactive message structures
            try:
                # Convert the interactive object to dict to access all fields
                interactive_dict = self.data.interactive.dict() if hasattr(self.data.interactive, 'dict') else {}
                
                # Try to extract text from any field that might contain it
                fallback_text_sources = []
                
                # Check for common text fields
                for field_name in ['text', 'title', 'description', 'button', 'message']:
                    if field_name in interactive_dict and interactive_dict[field_name]:
                        fallback_text_sources.append(f"{field_name.upper()}: {interactive_dict[field_name]}")
                
                # Check for nested objects that might contain text
                for field_name, field_value in interactive_dict.items():
                    if isinstance(field_value, dict) and 'text' in field_value:
                        fallback_text_sources.append(f"{field_name.upper()}: {field_value['text']}")
                
                if fallback_text_sources:
                    if not text_parts:  # Only use fallback if we didn't find standard text
                        text_parts.extend(fallback_text_sources)
                
            except Exception as e:
                logger.error(f"Error in fallback extraction: {e}")
            
            # Combine all parts into single text field
            full_text = " | ".join(text_parts) if text_parts else ""
            
            # If we still have no text, create a minimal fallback
            if not full_text:
                full_text = f"Mensagem interativa (tipo: {self.data.interactive.type})"
            
            interactive_data = {
                "text": full_text,
                "interactive_type": self.data.interactive.type or "",
                "message_type": "interactive_incoming",
                "buttons": [],
                "sections": []
            }
            
            # Still keep structured data for potential future use
            if self.data.interactive.action:
                if self.data.interactive.action.buttons:
                    for button in self.data.interactive.action.buttons:
                        interactive_data["buttons"].append({
                            "id": button.id or "",
                            "title": button.title or "",
                            "type": button.type or ""
                        })
                
                if self.data.interactive.action.sections:
                    for section in self.data.interactive.action.sections:
                        interactive_data["sections"].append({
                            "title": section.title or "",
                            "rows": section.rows or []
                        })
            
            return interactive_data
        return {"text": ""}
    
    def __get_list_message_input(self):
        """Handle list messages with sections and options"""
        if self.data.listMessage:
            # Build comprehensive text content for model context
            text_parts = []
            
            # Add main description
            if self.data.listMessage.description:
                text_parts.append(f"MENSAGEM: {self.data.listMessage.description}")
            
            # Add title if present
            if self.data.listMessage.title:
                text_parts.append(f"TÍTULO: {self.data.listMessage.title}")
            
            # Add button text
            if self.data.listMessage.buttonText:
                text_parts.append(f"BOTÃO: {self.data.listMessage.buttonText}")
            
            # Add footer if present
            if self.data.listMessage.footerText:
                text_parts.append(f"RODAPÉ: {self.data.listMessage.footerText}")
            
            # Process sections and options
            if self.data.listMessage.sections:
                options_text = []
                for section in self.data.listMessage.sections:
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
                    for section in self.data.listMessage.sections
                ]
            }
        return {"text": ""}
    
    def __get_reaction_input(self):
        if self.data.reaction and self.data.reaction.referencedMessage:
            ref_msg_id = ""
            if isinstance(self.data.reaction.referencedMessage, dict):
                ref_msg_id = self.data.reaction.referencedMessage.get("messageId", "")
            return {
                "value": self.data.reaction.value or "",
                "reference_message_id": ref_msg_id,
            }
        return {"text": ""}

    def __default_message(self):
        return {
            "text": ""
        }

    def __get_user_input(self):

        types_dict = {
            "text": self.__get_text_input,
            "image": self.__get_image_input,
            "audio": self.__get_audio_input,
            "video": self.__get_video_input,
            "document": self.__get_document_input,
            "location": self.__get_location_input,
            "contact": self.__get_contact_input,
            "payment": self.__get_payment_input,
            "buttonsResponseMessage": self.__get_button_list_input,
            "buttonReply": self.__get_button_action_input,
            "interactive": self.__get_interactive_input,
            "listMessage": self.__get_list_message_input,
            "reaction": self.__get_reaction_input,
        }

        input_function = types_dict.get(
            self.message_type,
            self.__default_message
        )

        return input_function()   

    def __format_image_history(self):
        # Store image messages as simple text in chat history
        # The actual image processing happens in real-time, not from history
        if self.user_input:
            image_caption = self.user_input.get("text", "")
            
            content = {
                "role": "user",
                "content": f"[Imagem enviada]{': ' + image_caption if image_caption else ''}"
            }

            if self.memory.get("chat_history"):
                self.memory['chat_history'].append(content)
            else:
                self.memory['chat_history'] = [content]

            if self.cache:
                self.cache.set_memory_dict(self.memory, self.memory_time)

    @staticmethod
    def __process_image(image: Image.Image) -> str:
        # Convert to RGB if image is in RGBA mode
        if image.mode == 'RGBA':
            image = image.convert('RGB')
        
        # Initial quality and size parameters
        quality = 90
        max_size = (1024, 1024)
        img_byte_arr = io.BytesIO()
        
        # First try: compress with JPEG and quality
        image.thumbnail(max_size, Image.Resampling.LANCZOS)
        image.save(img_byte_arr, format="JPEG", quality=quality, optimize=True)

        img_size = img_byte_arr.tell()
        
        # If still too large, reduce quality until acceptable
        while img_size > 1048576 and quality > 30:
            img_byte_arr = io.BytesIO()
            quality -= 30
            image.save(img_byte_arr, format="JPEG", quality=quality, optimize=True)
            img_size = img_byte_arr.tell()
        
        # If still too large after quality reduction, reduce dimensions
        size = 1024

        while img_size > 1048576 and size > 64:
            size = int(size * 0.75)
            max_size = (size, size)
            image.thumbnail(max_size, Image.Resampling.LANCZOS)
            
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format="JPEG", quality=quality, optimize=True)
            img_size = img_byte_arr.tell()
        
        img_byte_arr = img_byte_arr.getvalue()
        image_string = base64.b64encode(img_byte_arr).decode("utf-8")
        
        return f"data:image/jpeg;base64,{image_string}"

    def __format_document_history(self):
        if not self.user_input:
            return None
            
        if "image" in self.user_input.get("mime_type", ""):
            self.user_input['image'] = self.user_input['document']
            self.__format_image_history()
        elif "pdf" in self.user_input.get("mime_type", ""):
            page_count = self.user_input.get("page_count", 0)
            if isinstance(page_count, str):
                page_count = int(page_count) if page_count.isdigit() else 0
            if page_count > 10:
                return "O documento excede o limite de 10 páginas"
            
            try:
                pdf = requests.get(self.user_input['document'], stream=True)
                images = pdf2image.convert_from_bytes(pdf.content)

                for image in images:
                    image_string = self.__process_image(image)
                    self.user_input['image'] = image_string
                    self.__format_image_history()
            except Exception as e:
                logger.error(f"Error processing PDF: {e}")
                return "Erro ao processar o documento PDF"
        else:
            return "São suportados apenas documentos em PDF ou imagens"

    def __process_step1(self):
        agent = Agent(
            model="gpt-4.1",
            model_type="chat",
            json_schema=Step1Response,
        )

        history = self.memory.get('chat_history', [])

        if not history:
            history = [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": PROMPT
                        }
                    ]
                }
            ]

            self.memory['chat_history'] = history

        task = Task(
            user=self.user_input.get('text', '') if self.user_input else '',
            history=history,
            agent=agent,
            simple_response=True,
        )

        response = task.run()

        # Handle None response or missing output
        if not response:
            return {
                "type": "message", 
                "message": "Ocorreu um erro interno. Por favor, tente novamente."
            }

        if self.user_input:
            self.memory['chat_history'].append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": self.user_input.get('text', '')
                        }
                    ]
                },
            )

        if isinstance(response, dict):
            message_text = response.get('mensagem', '')
        else:
            message_text = ''

        self.memory['chat_history'].append(
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": message_text
                    }
                ]
            }
        )

        if self.cache:
            self.cache.set_memory_dict(self.memory)

        return response

    def __process_step2(self, data: Optional[dict] = None):
        agent = Agent(
            model="gpt-4.1",
            model_type="chat",
            tools=[self.send_message]
        )

        history = self.memory.get('chat_history2', [])

        if not history:
            # Enhanced system prompt with conversation context
            conversation_context = self.__get_conversation_context_for_agent()
            
            enhanced_prompt = PROMPT2
            if conversation_context:
                enhanced_prompt += f"\n\n# CONTEXTO DA CONVERSA ATUAL\n{conversation_context}"
            
            history = [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": enhanced_prompt
                        }
                    ]
                },               
            ]

            if data:
                history.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": str(data)
                            }
                        ]
                    }
                )

            self.memory['chat_history2'] = history

        task = Task(
            user=self.user_input.get('text', '') if self.user_input else '',
            history=history,
            agent=agent,
            simple_response=True,
        )

        # Determine event source more accurately
        is_bot_event = self.data.phone == "551130039303"
        event_source = "bot" if is_bot_event else "user"
        
        # Add conversation context to help the AI understand the flow
        conversation_context = {
            "event_from": event_source,
            "user_phone": self.memory.get('user_phone', ''),
            "bot_phone": self.memory.get('bot_phone', ''),
            "conversation_id": self.memory.get('conversation_id', f"user_{self.data.phone}_conversation"),
            "current_step": self.memory.get('step', 2)
        }
        
        response = task.run(conversation_context)

        # Handle None response or missing output
        if not response:
            return {
                "type": "message", 
                "message": "Ocorreu um erro interno. Por favor, tente novamente."
            }

        # Update chat_history2 with the updated prompt, but preserve the existing structure
        if hasattr(task, 'prompt') and task.prompt:
            self.memory['chat_history2'] = task.prompt
        else:
            # Fallback: Add the user input to the existing history if task.prompt is not available
            if self.user_input and self.user_input.get('text'):
                self.memory['chat_history2'].append({
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": self.user_input.get('text', '')
                        }
                    ]
                })
        
        # Sync shared conversation data after step2 processing
        self.__sync_shared_conversation()

        return response

    def _process_wpp_message(self):
        self.__build_memory()
        
        # Log raw event from z-api
        logger.info(f"Raw Z-API event from {self.data.phone}: {self.data}")
        
        # Add conversation context to memory for better routing
        if 'conversation_id' not in self.memory:
            if self.data.phone == "551130039303":
                # This is a bot message, try to find the original user
                original_user = self.memory.get('user_phone', 'unknown')
                self.memory['conversation_id'] = f"user_{original_user}_bot_551130039303"
            else:
                # This is a user message
                self.memory['conversation_id'] = f"user_{self.data.phone}_bot_551130039303"
        
        self.user_input = self.__get_user_input()
        
        # Track the incoming message in shared conversation
        if self.user_input and self.user_input.get('text'):
            # Determine speaker role based on phone number
            if self.data.phone == "551130039303":
                speaker_role = "customer_service"
            else:
                speaker_role = "user"
            
            self.__add_to_shared_conversation(
                message=self.user_input['text'],
                speaker_role=speaker_role,
                message_type=self.message_type
            )

        # Handle button messages specially
        if self.message_type in ["buttonsResponseMessage", "buttonReply"]:
            # For button messages, we include the button information in the text
            if self.user_input.get("button_id"):
                button_text = f"Botão selecionado: {self.user_input.get('button_id')} - {self.user_input.get('text', '')}"
                self.user_input['text'] = button_text
                
                # Add button interaction to chat history
                if self.memory.get('chat_history'):
                    self.memory['chat_history'].append({
                        "role": "user",
                        "content": button_text
                    })
                else:
                    self.memory['chat_history'] = [{
                        "role": "user", 
                        "content": button_text
                    }]

        # Handle incoming interactive messages (messages with buttons from other bots OR list selections)
        elif self.message_type == "interactive":
            # The text field already contains all formatted information from __get_interactive_input
            if self.user_input and self.user_input.get('text'):
                # Check if this is a button click (user clicked a hydrated button)
                if self.user_input.get('message_type') == 'button_click':
                    # This is a user's button click from a hydrated button - treat it like a button press
                    button_text = self.user_input['text']
                    self.user_input['text'] = button_text
                    
                    # Add to chat history
                    if self.memory.get('chat_history'):
                        self.memory['chat_history'].append({
                            "role": "user",
                            "content": button_text
                        })
                    else:
                        self.memory['chat_history'] = [{
                            "role": "user", 
                            "content": button_text
                        }]
                
                # Check if this is a list selection (user's choice from a list)
                elif self.user_input.get('message_type') == 'list_selection':
                    # This is a user's selection from a list - treat it more like a button press
                    selection_text = self.user_input['text']
                    self.user_input['text'] = selection_text
                    
                    # Add to chat history
                    if self.memory.get('chat_history'):
                        self.memory['chat_history'].append({
                            "role": "user",
                            "content": selection_text
                        })
                    else:
                        self.memory['chat_history'] = [{
                            "role": "user", 
                            "content": selection_text
                        }]
                else:
                    # This is an incoming interactive message from another bot
                    interactive_text = f"Mensagem interativa recebida: {self.user_input['text']}"
                    self.user_input['text'] = interactive_text
                    
                    # Add to chat history
                    if self.memory.get('chat_history'):
                        self.memory['chat_history'].append({
                            "role": "user",
                            "content": interactive_text
                        })
                    else:
                        self.memory['chat_history'] = [{
                            "role": "user", 
                            "content": interactive_text
                        }]
            else:
                # FALLBACK: If we didn't extract any text from the interactive message,
                # try to create a basic representation
                interactive_fallback = f"Mensagem interativa recebida (tipo: {self.data.interactive.type if self.data.interactive else 'unknown'})"
                self.user_input = {"text": interactive_fallback}
                
                # Add to chat history
                if self.memory.get('chat_history'):
                    self.memory['chat_history'].append({
                        "role": "user",
                        "content": interactive_fallback
                    })
                else:
                    self.memory['chat_history'] = [{
                        "role": "user", 
                        "content": interactive_fallback
                    }]
        
        # Handle incoming list messages (messages with sections and options)
        elif self.message_type == "listMessage":
            if self.user_input and self.user_input.get('text'):
                # This is an incoming list message from another bot
                list_text = f"Lista recebida: {self.user_input['text']}"
                self.user_input['text'] = list_text
                
                # Add to chat history
                if self.memory.get('chat_history'):
                    self.memory['chat_history'].append({
                        "role": "user",
                        "content": list_text
                    })
                else:
                    self.memory['chat_history'] = [{
                        "role": "user", 
                        "content": list_text
                    }]
            else:
                # FALLBACK: If we didn't extract any text from the list message
                list_fallback = "Lista recebida (sem conteúdo)"
                self.user_input = {"text": list_fallback}
                
                # Add to chat history
                if self.memory.get('chat_history'):
                    self.memory['chat_history'].append({
                        "role": "user",
                        "content": list_fallback
                    })
                else:
                    self.memory['chat_history'] = [{
                        "role": "user", 
                        "content": list_fallback
                    }]
        
        if self.message_type == "image":
            self.__format_image_history()

        if self.message_type == "document":
            document_response = self.__format_document_history()

            if document_response:
                return {"type": "message", "message": document_response}
        
        if not self.user_input or not self.user_input.get('text'):
            return None

        if self.memory.get('step') == 1:
            step1_response = self.__process_step1()
            
            if isinstance(step1_response, dict):
                if step1_response.get("validation_status") == "error":
                    return {
                        "type": "message", 
                        "message": "Não foi possível processar a requisição. Por favor, verifique se o assunto está relacionado a Porto Seguro e tente novamente."
                    }
                
                if step1_response.get("validation_status") == "follow-up":
                    return {
                        "type": "message", 
                        "message": step1_response.get('mensagem', 'Por favor, forneça mais informações.')
                    }

                if step1_response.get("validation_status") == "ok":
                    self.memory['step'] = 2
                    self.memory['data'] = step1_response.get('extracted_data')

                    self.memory['user_phone'] = self.data.phone
                    self.memory['bot_phone'] = "551130039303" # 551130039303, 5519999872145
                    
                    # Create shared conversation ID for tracking
                    conversation_id = f"conversation_{self.data.phone}_to_551130039303"
                    self.memory['conversation_id'] = conversation_id

                    # Initialize shared conversation history with role-based tracking
                    if 'shared_conversation' not in self.memory:
                        self.memory['shared_conversation'] = {
                            'participants': {
                                'user': self.data.phone,
                                'customer_service': "551130039303", 
                                'agent': 'intermediary_agent'
                            },
                            'conversation_history': [],
                            'current_context': {
                                'user_request': step1_response.get('extracted_data'),
                                'status': 'initiated',
                                'last_speaker': 'user'
                            }
                        }

                    # Save updated memory to user's context
                    if self.cache:
                        self.cache.set_memory_dict(self.memory)

                    # Create shared memory for bot context with SAME conversation data
                    bot_memory = {
                        'step': 2,
                        'data': step1_response.get('extracted_data'),
                        'user_phone': self.data.phone,
                        'bot_phone': "551130039303",
                        'conversation_id': conversation_id,
                        'chat_history2': self.memory.get('chat_history2', []),
                        # SHARED conversation data so agent can see both sides
                        'shared_conversation': self.memory['shared_conversation']
                    }
                    
                    # Save bot memory to bot's context
                    bot_cache = RedisManager(self.redis_client, self.memory['bot_phone'])
                    bot_cache.set_memory_dict(bot_memory)

                    self.wpp.send_message(
                        message="Oi Porto!",
                        number=self.memory['bot_phone'],
                    )

        if self.memory.get('step') == 2:
            _ = self.__process_step2(self.memory.get('data'))

    def send_message(self, message: str, to: str):
        """
        Sends a message to a specified recipient.

        Args:
            message (str): The message content to send.
            to (str): The recipient type, can be "user" or "bot".
        """
        
        # Determine the correct phone number based on context
        if to == "bot":
            target_phone = self.memory.get('bot_phone', "551130039303")
            recipient_role = "customer_service"
        else:
            target_phone = self.memory.get('user_phone', self.data.phone)
            recipient_role = "user"
            
        # Track the outgoing message in shared conversation
        self.__add_to_shared_conversation(
            message=message,
            speaker_role="agent",
            message_type="agent_response"
        )
        
        # Update shared conversation context for both user and bot
        self.__sync_shared_conversation()
            
        # Log the message routing for debugging
        logger.info(f"Agent routing message to {to} ({target_phone}): {message[:50]}...")

        self.wpp.send_message(
            message=message,
            number=target_phone,
        )
    
    def __sync_shared_conversation(self):
        """Sync shared conversation data between user and bot memory contexts."""
        try:
            # Update user memory
            if self.cache:
                self.cache.set_memory_dict(self.memory)
            
            # Update bot memory if it exists
            if self.memory.get('bot_phone'):
                bot_cache = RedisManager(self.redis_client, self.memory['bot_phone'])
                bot_memory = bot_cache.get_memory_dict()
                if bot_memory:
                    bot_memory['shared_conversation'] = self.memory['shared_conversation']
                    bot_memory['chat_history2'] = self.memory.get('chat_history2', [])
                    bot_cache.set_memory_dict(bot_memory)
                    
        except Exception as e:
            logger.error(f"Error syncing shared conversation: {e}")

    def process_event(self):

        message_type = {
            "message": self.wpp.send_message,
            "image": self.wpp.send_image,
            "button_list": self.wpp.send_buttons_list,
            "button_action": self.wpp.send_buttons_action,
        }

        response = self._process_wpp_message()

        if response:
            response['number'] = self.data.phone
            response_type = response.pop('type')

            send_function = message_type.get(response_type)
            if send_function:
                send_function(**response)