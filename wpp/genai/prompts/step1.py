PROMPT = """
Sua tarefa é processar uma mensagem de texto aberta enviada por um usuário via WhatsApp e, a partir desse texto, realizar as etapas abaixo:

1. Interpretar o texto para identificar e extrair explicitamente todos os dados relevantes (campos estáticos obrigatórios e quaisquer campos dinâmicos/contextuais necessários para o caso).
2. Executar a validação detalhada desses dados conforme as regras a seguir, usando raciocínio explícito e encadeado.
3. Após todas as etapas de raciocínio, retornar um objeto JSON rigorosamente estruturado conforme os exemplos.

O objetivo é apenas extrair e validar dados (não avançar no fluxo, não fornecer instruções de processo ou pedir dados adicionais além da mensagem de follow-up). Especifique, em seu raciocínio, cada decisão de extração e validação dos campos individualmente, sempre em português.

# Etapas

1. **Extração de Dados**  
   Analise o texto do usuário apresentado em linguagem natural e determine, com raciocínio explícito (passo a passo), quais campos estruturados (ex: 'nome', 'CPF', 'telefone', 'problema', 'sinistro_id', etc.) podem ser extraídos e quais não estão presentes ou estão ambíguos. Comente seu processo de extração antes de avançar para a validação.
2. **Validação de Campos**  
   Para cada campo obrigatório (estático: 'nome', 'CPF', 'telefone', 'problema' — e dinâmico/contextual como 'sinistro'/'protocolo' se relevante):
     - O campo foi extraído do texto?  
     - O valor extraído parece válido (formato/completude)?  
     Explique cada decisão de validação, campo a campo.
3. **Relatório de Validação**  
   Após o raciocínio, defina "validation_status" e construa a "mensagem" de acordo:
   - "ok" se todas as validações passaram.
   - "follow-up" se faltar/campo inválido, com mensagem apropriada, em português, identificando exatamente o que requer correção/complemento.
   - "error" se o assunto não for pertinente à Porto Seguro (neste caso, “mensagem” deve ser vazio).
4. **Construção do Objeto de Saída**
   Compile o resultado em JSON conforme o formato estrito a seguir.

# Formato de resposta

Responda sempre estritamente em JSON (sem blocos de código), usando esta estrutura:
- "reasoning": lista de raciocínio passo a passo, em português, explicitando cada decisão na sequência:
  1. Processo de extração de dados do texto (por campo)
  2. Processo de validação de cada campo extraído
- "validation_status": string, conforme lógica acima.
- "mensagem": conforme especificações acima.
- "extracted_data": objeto JSON com todos os campos extraídos do texto original (inclusos com valor vazio nulo caso não extraídos/inválidos).

# Exemplos

Exemplo 1 (WhatsApp — dados incompletos):
Input:  
"Oi, aqui é o Carlos Silva, meu CPF é 12345678900. Preciso abrir um sinistro. Obrigado!"

Output:
{
  "reasoning": [
    "Extração: Identifiquei o nome 'Carlos Silva' no texto.",
    "Extração: Localizei CPF '12345678900'.",
    "Extração: Não encontrei telefone informado explicitamente.",
    "Extração: Mensão a pedido de sinistro em 'Preciso abrir um sinistro'.",
    "Extração: identificador não informado.",
    "Validação: nome presente e adequado.",
    "Validação: CPF presente e adequado.",
    "Validação: telefone ausente.",
    "Validação: problema presente e válido.",
    "Validação: identificador ausente, necessário neste caso."
  ],
  "validation_status": "follow-up",
  "mensagem": "Por favor, informe seu telefone de contato e o número do sinistro para prosseguir.",
  "extracted_data": {
    "nome": "Carlos Silva",
    "CPF": "12345678900",
    "telefone": "",
    "problema": "abrir um sinistro",
    "identificador": null
  }
}

Exemplo 2 (WhatsApp — todos os dados presentes e corretos):
Input:  
"Olá, sou a Joana Souza, CPF 98765432100, meu telefone é 11988887777. Preciso atualizar dados do sinistro SN-2033."

Output:
{
  "reasoning": [
    "Extração: Nome 'Joana Souza' identificado.",
    "Extração: CPF 98765432100 encontrado.",
    "Extração: telefone 11988887777 extraído.",
    "Extração: Pedido para atualizar dados identificado como 'problema'.",
    "Extração: identificador 'SN-2033' identificado.",
    "Validação: nome presente e adequado.",
    "Validação: CPF presente e adequado.",
    "Validação: telefone presente e adequado.",
    "Validação: problema presente e válido.",
    "Validação: identificador presente e válido."
  ],
  "validation_status": "ok",
  "mensagem": "",
  "extracted_data": {
    "nome": "Joana Souza",
    "CPF": "98765432100",
    "telefone": "11988887777",
    "problema": "atualizar dados",
    "identificador": "SN-2033"
  }
}

Exemplo 3 (WhatsApp — assunto não pertinente):
Input:  
"Boa noite, sou Pedro Gomes e quero cancelar minha assinatura da Netflix. Meu telefone é 21999887766."

Output:
{
  "reasoning": [
    "Extração: Nome 'Pedro Gomes' localizado.",
    "Extração: Telefone 21999887766 extraído.",
    "Extração: Não localizei CPF no texto.",
    "Extração: Pedido para cancelar assinatura da Netflix não é relacionado à Porto Seguro.",
    "Validação: nome presente.",
    "Validação: telefone presente.",
    "Validação: CPF ausente.",
    "Validação: problema não pertinente à Porto Seguro."
  ],
  "validation_status": "error",
  "mensagem": "",
  "extracted_data": {
    "nome": "Pedro Gomes",
    "CPF": "",
    "telefone": "21999887766",
    "problema": "cancelar assinatura da Netflix"
  }
}

(Adapte a mensagem de follow-up de acordo com a(s) informação(ões) ausente(s) de cada caso real.)

# Notas

- O input SEMPRE é uma única mensagem livre de WhatsApp, em português.
- Nunca continue o fluxo, apenas extraia, valide e reporte conforme instruído.
- Relate todo o raciocínio de extração e validação antes de definir qualquer resultado.
- Campos não encontrados devem ser registrados como valores vazios e relatados no raciocínio.
- Cite explicitamente, em "mensagem", todos os dados faltantes/irregulares para follow-up.
- NÃO use blocos de código.
- Siga exatamente o formato/ordem dos campos do exemplo.
- Persistência: Caso a mensagem seja complexa ou ambígua, continue processando e raciocinando até capturar todos os dados possíveis do texto antes de apresentar a resposta final.

# Output Format

A resposta deve ser estritamente um objeto JSON único, sem blocos de código, contendo:
- "reasoning": array de strings (explicitação passo a passo, começando pela extração, depois validação, sempre em português);
- "validation_status": string ("ok", "follow-up", ou "error");
- "mensagem": string conforme as regras;
- "extracted_data": objeto JSON, com todos os campos extraídos ou marcados como vazio/nulo conforme aplicável. 

Lembre-se: sempre inicie pelo raciocínio de extração, depois validação, e só então reporte resultado e mensagem.

Memória:
{memory}

Input:
{text}

Output:
"""