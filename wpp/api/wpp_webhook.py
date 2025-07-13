import requests
import pdf2image
import io
import base64
import logging

from PIL import Image

from repenseai.genai.agent import Agent

from repenseai.genai.tasks.api import Task
from repenseai.genai.tasks.workflow import Workflow

from wpp.schemas.wpp_webhook import WppPayload
from wpp.api.wpp_message import WppMessage
from wpp.memory import RedisManager

import redis

logger = logging.getLogger(__name__)

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
            selector=audio_selector,
        )

        audio = requests.get(self.data.audio.audioUrl).content
        transcription = audio_task.predict({"audio": audio})

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

        content = {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": self.user_input["image"],
                        "detail": "high",
                    },
                }
            ]
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

    def _process_wpp_message(self, workflow: Workflow):
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

        self.user_input["redis"] = self.cache
        self.user_input["full_name"] = self.full_name
        self.user_input["name"] = self.name
        self.user_input["phone"] = self.data.phone

        response = workflow.run(self.user_input)

        # Handle None response or missing output
        if not response or not response.get('output'):
            return {
                "type": "message", 
                "message": "Ocorreu um erro interno. Por favor, tente novamente."
            }

        output = response['output']

        if output.get("validation_status") == "error":
            return {
                "type": "message", 
                "message": "Não foi possível processar a requisição. Por favor, verifique se o assunto está relacionado a Porto Seguro e tente novamente."
            }
        
        if output.get("validation_status") == "follow-up":
            return {
                "type": "message", 
                "message": output.get('mensagem', 'Por favor, forneça mais informações.')
            }

        if output.get("validation_status") == "ok":
            return {
                "type": "message", 
                "message": "Ok! Estamos processando sua requisição. Por favor, aguarde um momento."
            }
        
        return {
            "type": "message", 
            "message": "ERRO!"
        }

    def process_event(self, workflow: Workflow):

        message_type = {
            "message": self.wpp.send_message,
            "image": self.wpp.send_image,
            "button_list": self.wpp.send_buttons_list,
            "button_action": self.wpp.send_buttons_action,
        }

        response = self._process_wpp_message(workflow)
        logger.info(response)

        if response:
            response['number'] = self.data.phone
            response_type = response.pop('type')

            send_function = message_type.get(response_type)
            send_function(**response)