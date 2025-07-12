from pydantic import BaseModel
from typing import List


class Option(BaseModel):
    description: str
    title: str


class Options(BaseModel):
    title: str
    buttonLabel: str
    options: List[Option]


class OptionsList(BaseModel):
    phone: str
    message: str
    optionsList: List[Options]