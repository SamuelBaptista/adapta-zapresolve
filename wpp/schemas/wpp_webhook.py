from pydantic import BaseModel
from typing import Optional, List


class Text(BaseModel):
    message: str
    description: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    thumbnailUrl: Optional[str] = None

class Reaction(BaseModel):
    value: str
    time: int
    reactionBy: str
    referencedMessage: dict

class ButtonReply(BaseModel):
    buttonId: str
    message: str
    referenceMessageId: str

class ButtonResponse(BaseModel):
    buttonId: str
    message: str

class ListResponse(BaseModel):
    message: str
    title: str
    selectedRowId: str

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
    videoUrl: str
    caption: str
    mimeType: str
    seconds: int
    viewOnce: bool

class Contact(BaseModel):
    displayName: str
    vCard: str
    phones: List[str]

class Document(BaseModel):
    documentUrl: str
    mimeType: str
    title: str
    pageCount: int
    fileName: str
    caption: Optional[str] = ""

class Location(BaseModel):
    longitude: float
    latitude: float
    address: str
    url: str

class Sticker(BaseModel):
    stickerUrl: str
    mimeType: str

class Payment(BaseModel):
    receiverPhone: str
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

    
    def get_payload_type(self) -> str:
        if self.text is not None:
            return "text"
        elif self.image is not None:
            return "image"
        elif self.audio is not None:
            return "audio"
        elif self.video is not None:
            return "video"
        elif self.contact is not None:
            return "contact"
        elif self.document is not None:
            return "document"
        elif self.location is not None:
            return "location"
        elif self.sticker is not None:
            return "sticker"
        elif self.listResponseMessage is not None:
            return "listResponseMessage"
        elif self.buttonsResponseMessage is not None:
            return "buttonsResponseMessage"
        elif self.reaction is not None:
            return "reaction"
        elif self.payment is not None:
            return "payment"
        elif self.order is not None:
            return "order"
        elif self.buttonReply is not None:
            return "buttonReply"
        else:
            return "unknown"