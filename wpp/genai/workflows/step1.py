import json
from typing import Optional

from wpp.genai.prompts.step1 import PROMPT

from repenseai.genai.agent import Agent
from repenseai.genai.tasks.api import Task
from repenseai.genai.tasks.workflow import Workflow

from pydantic import BaseModel


# Functions

def get_memory_dict(context: dict) -> dict:
    memory = context['redis'].get_memory_dict()
    return memory.get('chat_history', [])


def set_memory_dict(context: dict) -> bool:

    memory = context['redis'].get_memory_dict()
    history = memory.get('chat_history', [])

    user = {
        "role": "user",
        "content": context['text']
    }

    assistant = {
        "role": "assistant", 
        "content": json.dumps(context['output'])
    }

    history.append(user)
    history.append(assistant)

    memory['chat_history'] = history
    context['redis'].set_memory_dict(memory)

    return True

# Models

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


# Workflow

agent = Agent(
    model="gpt-4.1",
    model_type="chat",
    json_schema=Step1Response,
)

task = Task(
    user=PROMPT,
    agent=agent,
    simple_response=True,
)


step1_workflow = Workflow(
    [
        [get_memory_dict, "memory"],
        [task, "output"],
        [set_memory_dict, "update_memory"],
    ]
)
