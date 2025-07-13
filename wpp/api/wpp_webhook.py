import requests
import pdf2image
import io
import base64
import logging
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

        self.memory['step'] = self.memory.get('step', 1)
        
    def __get_text_input(self):
        return {"text": self.data.text.message}
    
    def __get_image_input(self):
        return {
            "image": self.data.image.imageUrl,
            "text": self.data.image.caption,
        }

    def __get_audio_input(self):
        audio_selector = Agent(
            model="whisper-1", 
            model_type="audio", 
        )

        audio_task = Task(
            agent=audio_selector,
        )

        audio = requests.get(self.data.audio.audioUrl).content
        transcription = audio_task.run({"audio": audio})

        return {
            "text": transcription.get("response"), 
            "audio_response": transcription
        }
    
    def __get_video_input(self):
        return {
            "video": self.data.video.videoUrl,
            "text": self.data.video.caption,
        }
    
    def __get_document_input(self):
        return {
            "document": self.data.document.documentUrl,
            "text": self.data.document.caption,
            "file_name": self.data.document.fileName,
            "page_count": self.data.document.pageCount,
            "mime_type": self.data.document.mimeType,
            "title": self.data.document.title,
        }
    
    def __get_location_input(self):
        return {
            "latitude": self.data.location.latitude,
            "longitude": self.data.location.longitude,
        }
    
    def __get_contact_input(self):
        return {
            "name": self.data.contact.name,
            "phone": self.data.contact.phone,
        }

    def __get_payment_input(self):
        return {
            "valeu": self.data.payment.value,
            "currency": self.data.payment.currencyCode,
            "status": self.data.payment.status,
            "transaction_status": self.data.payment.transactionStatus,
        }

    def __get_button_list_input(self):
        return {
            "text": self.data.buttonsResponseMessage.message,
            "button_id": self.data.buttonsResponseMessage.buttonId,
        }

    def __get_button_action_input(self):
        return {
            "text": self.data.buttonReply.message,
            "button_id": self.data.buttonReply.buttonId,
            "reference_message_id": self.data.buttonReply.referenceMessageId,
        }
    
    def __get_reaction_input(self):
        return {
            "value": self.data.reaction.value,
            "reference_message_id": self.data.reaction.referencedMessage.messageId,
        }

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
        image_caption = self.user_input.get("text", "")
        
        content = {
            "role": "user",
            "content": f"[Imagem enviada]{': ' + image_caption if image_caption else ''}"
        }

        if self.memory.get("chat_history"):
            self.memory['chat_history'].append(content)
        else:
            self.memory['chat_history'] = [content]

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
        if "image" in self.user_input["mime_type"]:
            self.user_input['image'] = self.user_input['document']
            self.__format_image_history()
        elif "pdf" in self.user_input["mime_type"]:
            if self.user_input["page_count"] > 10:
                return "O documento excede o limite de 10 páginas"
            
            pdf = requests.get(self.user_input['document'], stream=True)
            images = pdf2image.convert_from_bytes(pdf.content)

            for image in images:

                image_string = self.__process_image(image)
                self.user_input['image'] = image_string
                self.__format_image_history()
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
            user=self.user_input['text'],
            history=history,
            agent=agent,
            simple_response=True,
        )

        response = task.run()
        logger.info(task.prompt)

        # Handle None response or missing output
        if not response:
            return {
                "type": "message", 
                "message": "Ocorreu um erro interno. Por favor, tente novamente."
            }

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

        self.memory['chat_history'].append(
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": response.get('mensagem', '')
                    }
                ]
            }
        )

        self.cache.set_memory_dict(self.memory)

        return response

    def __process_step2(self, data: dict | None = None):
        agent = Agent(
            model="gpt-4.1",
            model_type="chat",
            tools=[self.send_message]
        )

        history = self.memory.get('chat_history2', [])

        if not history:
            history = [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": PROMPT2
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
            user=self.user_input['text'],
            history=history,
            agent=agent,
            simple_response=True,
        )

        response = task.run({
            "bot_phone": self.memory['bot_phone'],
            "user_phone": self.memory['user_phone'],
            "event_from": self.data.phone,
        })

        logger.info(task.prompt)

        # Handle None response or missing output
        if not response:
            return {
                "type": "message", 
                "message": "Ocorreu um erro interno. Por favor, tente novamente."
            }

        self.memory['chat_history2'] = task.prompt
        self.cache.set_memory_dict(self.memory)

        return response

    def _process_wpp_message(self):
        self.__build_memory()
        self.user_input = self.__get_user_input()

        
        if self.message_type == "image":
            self.__format_image_history()

        if self.message_type == "document":
            document_response = self.__format_document_history()

            if document_response:
                return {"type": "message", "message": document_response}
        
        if not self.user_input.get('text'):
            return None

        if self.memory.get('step') == 1:
            step1_response = self.__process_step1()
            
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

                self.cache.set_memory_dict(self.memory)

                temp_cache = RedisManager(self.redis_client, self.memory['bot_phone'])
                temp_cache.set_memory_dict(self.memory)

                self.wpp.send_message(
                    message="Oi Porto!",
                    number=self.memory['bot_phone'],
                )

        if self.memory.get('step') == 2:
            logger.info(self.memory)
            _ = self.__process_step2(self.memory['data'])

    def send_message(self, message: str, to: str):
        """
        Sends a message to a specified recipient.

        Args:
            message (str): The message content to send.
            to (str): The recipient type, can be "user" or "bot".
        """

        self.wpp.send_message(
            message=message,
            number=self.memory['bot_phone'] if to == "bot" else self.memory['user_phone'],
        )

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
            send_function(**response)