import requests

from wpp.schemas.wpp_message import OptionsList

class WppMessage:
    def __init__(self, instance_id: str, instance_token: str, client_token: str):

        self.root = "https://api.z-api.io/instances"

        self.headers = {"client-token": client_token}
        self.instance = f"{instance_id}/token/{instance_token}"

    def send_message(self, message: str | list, number: str, message_id: str = "") -> dict:      

        url = f"{self.root}/{self.instance}/send-text"

        if isinstance(message, list):
            for msg in message:
                payload = {"phone": number, "message": msg}
                response = requests.post(url, data=payload, headers=self.headers)
        else:
            payload = {"phone": number, "message": message}

            if message_id:
                payload["messageId"] = message_id

            response = requests.post(url, data=payload, headers=self.headers)

        return response


    def send_image(self, image: str, number: str, message: str = "") -> dict:
        
        url = f"{self.root}/{self.instance}/send-image"
        payload = {"phone": number, "image": image}

        if message:
            payload["caption"] = message

        response = requests.post(url, data=payload, headers=self.headers)

        return response


    def send_video(self, video_url: str, number: str, caption: str = "") -> dict:
        
        url = f"{self.root}/{self.instance}/send-video"
        payload = {"phone": number, "video": video_url, "caption": caption}

        response = requests.post(url, data=payload, headers=self.headers)

        return response


    def send_options_list(self, message: str, number: str, options: OptionsList) -> dict:

        url = f"{self.root}/{self.instance}/send-option-list"

        payload = {"phone": number, "message": message, "optionList": options}

        response = requests.post(url, json=payload, headers=self.headers)
        return response
    
    def send_buttons_list(
            self, 
            message: str, 
            number: str, 
            buttons: list[str],
            image: str = ""
        ) -> dict:

        url = f"{self.root}/{self.instance}/send-button-list"

        button_list = {
            "buttons": [
                {"id": i, "label": button} 
                for i, button in enumerate(buttons)
            ]
        }

        if image:
            button_list["image"] = image

        payload = {"phone": number, "message": message, "buttonList": button_list}

        response = requests.post(url, json=payload, headers=self.headers)
        return response
    
    def send_buttons_action(self, message: str, number: str, buttons: list[dict[str, str]]) -> dict:

        url = f"{self.root}/{self.instance}/send-button-actions"

        buttons_action = [
            {"id": i, "label": button['label'], 'type': button['type'], 'url': button.get('url', "")} 
            for i, button in enumerate(buttons)
        ]

        payload = {
            "phone": number, 
            "message": message,
            "buttonActions": buttons_action
        }

        response = requests.post(url, json=payload, headers=self.headers)
        return response
    
    def send_pix_button(self, message: str, number: str) -> dict:

        url = f"{self.root}/{self.instance}/send-button-pix"

        payload = {"phone": number, "pixKey": message, "type": "EVP"}

        response = requests.post(url, json=payload, headers=self.headers)
        return response
