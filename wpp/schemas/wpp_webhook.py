from pydantic import BaseModel
from typing import Optional, List


class Text(BaseModel):
    message: str
    description: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    thumbnailUrl: Optional[str] = None


class ButtonReply(BaseModel):
    buttonId: str
    message: str
    referenceMessageId: str

class ButtonResponse(BaseModel):
    buttonId: str
    message: str


class ListResponse(BaseModel):
    listType: str
    multipleSelection: bool
    message: str


class Image(BaseModel):
    mimeType: str
    imageUrl: str
    thumbnailUrl: str
    caption: str
    width: int
    height: int
    viewOnce: bool

class Audio(BaseModel):
    ptt: bool
    seconds: int
    audioUrl: str
    mimeType: str
    viewOnce: bool


class Video(BaseModel):
    mimeType: str
    videoUrl: str
    thumbnailUrl: str
    caption: str
    width: int
    height: int
    viewOnce: bool


class Document(BaseModel):
    mimeType: str
    documentUrl: str
    thumbnailUrl: str
    caption: str
    fileName: str
    pageCount: int
    title: str


class Contact(BaseModel):
    name: str
    phone: str


class Location(BaseModel):
    latitude: float
    longitude: float


class Sticker(BaseModel):
    mimeType: str
    stickerUrl: str
    thumbnailUrl: str
    width: int
    height: int


class Reaction(BaseModel):
    value: str
    referencedMessage: Optional[dict] = None


class Payment(BaseModel):
    value: int
    currencyCode: str
    status: str
    transactionStatus: str


class Product(BaseModel):
    quantity: int
    name: str
    productId: str
    retailerId: Optional[str] = None
    price: int
    currencyCode: str

class Order(BaseModel):
    itemCount: int
    orderId: str
    message: str
    orderTitle: str
    sellerJid: str
    thumbnailUrl: str
    token: str
    currency: str
    total: int
    subTotal: int
    products: List[Product]


# New models for incoming interactive messages
class InteractiveButton(BaseModel):
    id: str
    title: str
    type: Optional[str] = None

class InteractiveSection(BaseModel):
    title: str
    rows: List[dict]

class InteractiveAction(BaseModel):
    buttons: Optional[List[InteractiveButton]] = None
    sections: Optional[List[InteractiveSection]] = None

class InteractiveHeader(BaseModel):
    type: str  # text, image, video, document
    text: Optional[str] = None
    image: Optional[str] = None
    video: Optional[str] = None
    document: Optional[str] = None

class InteractiveBody(BaseModel):
    text: str

class InteractiveFooter(BaseModel):
    text: str

# New model for list reply responses
class ListReply(BaseModel):
    id: str
    title: str
    description: Optional[str] = None

# New model for interactive button reply responses (hydrated buttons)
class InteractiveButtonReply(BaseModel):
    id: str
    title: str
    payload: Optional[str] = None

# New models for List Messages (different from interactive lists)
class ListMessageOption(BaseModel):
    title: str
    description: str
    rowId: str

class ListMessageSection(BaseModel):
    title: Optional[str] = None
    options: List[ListMessageOption]

class ListMessage(BaseModel):
    description: str
    footerText: Optional[str] = None
    title: Optional[str] = None
    buttonText: str
    sections: List[ListMessageSection]

class Interactive(BaseModel):
    type: str  # button, list, list_reply, etc.
    header: Optional[InteractiveHeader] = None
    body: Optional[InteractiveBody] = None
    footer: Optional[InteractiveFooter] = None
    action: Optional[InteractiveAction] = None
    # New field for list reply responses
    list_reply: Optional[ListReply] = None
    
    # Additional fields for other interactive message types
    button: Optional[str] = None  # For simple button text
    title: Optional[str] = None   # For message title
    description: Optional[str] = None  # For message description
    
    # Button reply response (when user clicks a button - hydrated buttons)
    button_reply: Optional[InteractiveButtonReply] = None
    
    # Allow any additional fields that we might not know about
    class Config:
        extra = "allow"


class WppPayload(BaseModel):
    isStatusReply: bool
    chatLid: Optional[str] = None
    connectedPhone: str
    waitingMessage: bool
    isEdit: bool
    isGroup: bool
    isNewsletter: bool
    instanceId: str
    messageId: str
    phone: str
    fromMe: bool
    momment: int
    status: str
    chatName: str
    senderPhoto: Optional[str] = None
    senderName: str
    photo: Optional[str] = None
    broadcast: bool
    participantLid: Optional[str] = None
    forwarded: bool
    type: str
    fromApi: bool
    participantPhone: Optional[str] = None
    text: Optional[Text] = None
    image: Optional[Image] = None
    audio: Optional[Audio] = None
    video: Optional[Video] = None
    contact: Optional[Contact] = None
    document: Optional[Document] = None
    location: Optional[Location] = None
    sticker: Optional[Sticker] = None
    listResponseMessage: Optional[ListResponse] = None
    buttonsResponseMessage: Optional[ButtonResponse] = None
    buttonReply: Optional[ButtonReply] = None
    reaction: Optional[Reaction] = None
    payment: Optional[Payment] = None
    order: Optional[Order] = None
    # New field for incoming interactive messages
    interactive: Optional[Interactive] = None
    # New field for list messages (different from interactive lists)  
    listMessage: Optional[ListMessage] = None

    
    def get_payload_type(self) -> str:
        if self.text and self.text.message:
            return "text"
        elif self.image:
            return "image"
        elif self.audio:
            return "audio"
        elif self.video:
            return "video"
        elif self.document:
            return "document"
        elif self.location:
            return "location"
        elif self.contact:
            return "contact"
        elif self.sticker:
            return "sticker"
        elif self.reaction:
            return "reaction"
        elif self.payment:
            return "payment"
        elif self.order:
            return "order"
        elif self.listResponseMessage:
            return "listResponseMessage"
        elif self.buttonsResponseMessage:
            return "buttonsResponseMessage"
        elif self.buttonReply:
            return "buttonReply"
        elif self.interactive:
            return "interactive"
        elif self.listMessage:
            return "listMessage"
        else:
            return "unknown"