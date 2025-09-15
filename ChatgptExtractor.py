import os
import openai
import tiktoken

openai.api_key = os.getenv("KEY_CHATGPT")

#funcion que llama y utiliza OpenAI
def extraer_metadatos_y_resumen_con_gpt(texto, token_entrada, token_salida, campos_deseados=None, incluir_resumen=True):
   

    # Recorte de tokens si el texto es demasiado largo
    encoding = tiktoken.encoding_for_model("gpt-4-1106-preview")
    tokens = encoding.encode(texto)
    MAX_TOKENS_ENTRADA = token_entrada

    if len(tokens) > MAX_TOKENS_ENTRADA:
        print(f"⚠️ El texto tiene {len(tokens)} tokens. Se recorta a {MAX_TOKENS_ENTRADA} tokens.")
        texto = encoding.decode(tokens[:MAX_TOKENS_ENTRADA])

    #  Construcción del prompt
    prompt = """
Analiza el siguiente texto de un documento PDF y realiza lo siguiente:

1. Detecta el tipo de documento: puede ser uno de estos: 'contrato', 'factura', 'documento legal', 'otros'.
2. Según el tipo detectado, extrae los metadatos correspondientes.
3. Devuelve **únicamente** una lista JSON de strings con formato exacto, como se muestra:

[
  "campo 1: valor 1",
  "campo 2: valor 2",
  "campo 3: valor 3"
]

⚠️ Muy importante:
- NO incluyas explicaciones.
- NO uses bloque de código (no pongas ```json ni ```).
- NO agregues texto antes ni después.
- Cada línea debe ser una string `"campo: valor"`.
- Si un campo no se encuentra, escribe `"campo: No encontrado"`.
(Sin encabezados, sin comentarios, sin explicaciones. Solo la lista.)
- Devuelve el nombre de los campos tal cual como te los enviaron.
- Si no encuentras un valor, escribe "campo: No encontrado".
- Si el campo contiene varios datos, colócalos en una sola línea.

""".strip()

    if campos_deseados:
        prompt += "\nExtrae únicamente estos campos si son relevantes:\n"
        for campo in campos_deseados:
            prompt += f"- {campo}\n"
    else:
        prompt += """
Si no hay metadatos a extraer no los extraigas y continua con el proceso del resumen
"""


    if incluir_resumen:
            prompt += "\n- resumen: (máx. 10000 caracteres, texto limpio y coherente, incluir como último ítem de la lista)"


    prompt += "\n\nIMPORTANTE: Devuelve únicamente la lista, sin texto adicional, sin introducción, sin conclusiones. Ademas, asi no tenga metadatos y el resumen es true por favor saca el resumen."
    prompt += f"""\n\nTexto:\n\"\"\"\n{texto}\n\"\"\""""

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4-1106-preview",
            messages=[
                {"role": "system", "content": "Eres un asistente experto en análisis de documentos y extracción de información clave y solo devuelve listas JSON. No expliques, no introduzcas, no concluyas. Solo responde con una lista de strings del tipo 'campo: valor'."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens= token_salida
        )

        return response['choices'][0]['message']['content'].strip()

    except Exception as e:
        return {"error": str(e)}

