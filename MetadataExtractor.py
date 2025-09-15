# Nueva versión del extractor con soporte para formatos/documentos personalizados

import re
from datetime import datetime
import fitz  # PyMuPDF
import spacy
import logging
import pytesseract
from pdf2image import convert_from_path
from transformers import pipeline, AutoTokenizer
import openai
# Carga de modelo spaCy
nlp = spacy.load("es_core_news_md")
openai.api_key = "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"
# Logging
logging.basicConfig(filename="errores_extraccion.log", level=logging.WARNING)

# Inicializa el modelo de resumen
resumen_pipeline = pipeline("summarization", model="facebook/bart-large-cnn")  # Ejemplo de modelo específico


# ---------------------- NUEVO: Regex por formato ----------------------
regex_por_formato = {
    "factura": {
        "numero_factura": r"(?i)(?:factura\s+)?(?:N[oº°]?[\s:.-]*)?(\d{3,})?(factura (No\.?|N°|número)[:\s]*\d+)?(N°[\s]*\d{3,})",
        "fecha_factura": r"(?i)(\d{2}/\d{2}/\d{4})?\d{1,2} de [a-zA-Z]+ de \d{4}",
        "proveedor": r"(?i)(?:Empresa|Proveedor|Vendedor|Emisor|Factura Electrónica de Venta)[:\s]*([\wÁÉÍÓÚÑ\s]+)\n",
        "representante_legal": r"(?i)representad[oa]\s+legalmente\s+por\s*([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)+)",
        "nit_proveedor": r"(?i)NIT[:\s]*(\d{7,10}-\d)"
    },
    "generico": {
        "numero_contrato": r"(?i)(?:contrato(?:\s+n[úu]mero)?|No\.?|Nº)[\s:]*([A-Z0-9\-\/]{3,})",
        "fecha_contrato": r"(?i)(?:fecha\s+(?:de\s+)?(suscripci[oó]n|firma|inicio|documento))[\s:]*([\d]{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|\d{1,2}\s+de\s+[a-záéíóú]+(?:\s+de)?\s+\d{4})",
        "contratante": r"(?i)(?:el|la)?\s*contratante[\s:]*([A-ZÁÉÍÓÚÑ][\w\s]+?)(?=\s*(?:NIT|identificado|mayor))",
        "contratista": r"(?i)(?:el|la)?\s*contratista[\s:]*([A-ZÁÉÍÓÚÑ][\w\s]+?)(?=\s*(?:NIT|identificado|mayor))",
        "objeto_contrato": r"(?i)objeto\s*(?:del)?\s*contrato[:\s]+(.+?)(?:\.|\n|$)",
        "representante_legal": r"(?i)representante\s+legal\s+(?:de\s+la\s+empresa)?[\s:]*([A-ZÁÉÍÓÚÑ][\w\s]+?)(?:\s+identificado|\s+NIT|,|\.)",
        "partes_contrato": r"(?i)entre\s+los\s+suscritos.*?([A-ZÁÉÍÓÚÑ\s]+?)\s+y\s+([A-ZÁÉÍÓÚÑ\s]+?)[,\.]",
        "tipo_documento": r"(?i)(asunto|referencia|ref)[:\s]+([A-ZÁÉÍÓÚÑ\s]{5,})",
        "juez": r"(?i)(juzgado[\w\s\.]+)",
        "secretaria": r"(?i)(secretar[ií]a|secretario|informe secretarial)[:\s]+([A-ZÁÉÍÓÚÑ\s\.]+)",
        "fecha_oficio": r"(?i)(fecha\s+de\s+(oficio|providencia|respuesta|env[ií]o|radicaci[oó]n))[:\s]+(?:el\s+)?(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
        "demandante": r"(?i)([A-ZÁÉÍÓÚÑ\s\.]+?)\s+contra\s+",
        "demandado": r"(?i)contra\s+([A-ZÁÉÍÓÚÑ\s\.]+)",
        "radicado": r"(?i)(?:radicado|número de radicación)[:\s]+([\d\-]+)",
        "otorgante": r"(?i)yo[\s,]+([A-ZÁÉÍÓÚÑ\s]+),\s+mayor",
        "apoderado": r"(?i)otorgo\s+poder\s+especial\s+a\s+favor\s+de\s+([A-ZÁÉÍÓÚÑ\s]+),\s+identificado"
    },   
    "compraventa": {
        "numero_contrato": r"(?i)CONTRATO\s+No\.?\s*(\d+\s*de\s*\d{4})",
        "fecha_contrato": r"(?i)celebrado\s+el\s+d[ií]a\s+(\d{1,2}\s+de\s+[a-záéíóú]+\s+de\s+\d{4})",
        "contratista": r"(?i)quien\s+en\s+adelante\s+se\s+denominar[aá]\s+EL\s+CONTRATISTA[\s,:]+([\wÁÉÍÓÚÑ\s]+)",
        "contratante": r"(?i)entre\s+el\s+Departamento\s+Administrativo\s+de\s+Ciencia.*?quien\s+en\s+adelante\s+se\s+denominar[aá]\s+EL\s+CONTRATANTE",
        "representante_legal": r"(?i)representado\s+legalmente\s+por[\s,:]+([\wÁÉÍÓÚÑ\s]+),",
        "objeto_contrato": r"(?i)OBJETO\s+DEL\s+CONTRATO[\s:]+(.+?)(?:\n|\.|$)",
        "valor_total": r"(?i)VALOR\s+DEL\s+CONTRATO[\s:]+(?:la\s+)*suma\s+de\s+(.+?)\s+m[.]?",
        "forma_pago": r"(?i)FORMA\s+DE\s+PAGO[\s:]+(.+?)(?:\n|\.|$)"
    },
    "contrato_fcm": {
        "numero_contrato": r"(?i)CONTRATO\s+(?:N[º°o]\.?|No\.?)?\s*([A-Z0-9\-\/]+)",
        "fecha_contrato": r"(?i)(?:suscrito|firmado)?\s*(?:el\s+d[ií]a\s+)?(\d{1,2}\s+de\s+[a-záéíóú]+(?:\s+de)?\s+\d{4})",
        "contratante": r"(?i)entre\s+la\s+(?:empresa|entidad|[A-ZÁÉÍÓÚÑ\s]+),?\s*(?:identificada)?\s*.*?y\s+el\s+señor",
        "contratista": r"(?i)el\s+señor\s+([A-ZÁÉÍÓÚÑ\s]+?),?\s+mayor\s+de\s+edad",
        #"objeto_contrato": r"(?i)objeto\s+del\s+contrato[:\s]*([\s\S]{20,300}?)(?=\.|\n)",
        "representante_legal": r"(?i)representante\s+legal\s+de\s+la\s+(?:empresa|entidad)[\s:]*([A-ZÁÉÍÓÚÑ\s]+)",
    },
    "contrato_indefinido": {
        "numero_contrato": r"(?i)(?:C[ÓO]DIGO\s*[:\-]?\s*)([A-Z]{3}-FOR-\d+)",
        "fecha_contrato": r"(?i)Ciudad\s+y\s+Fecha\s*:\s*[A-ZÁÉÍÓÚÑ\s\.]+,\s*(\d{1,2}\s+de\s+[a-záéíóú]+(?:\s+del|\s+de)?\s+\d{4})",
        "contratista": r"(?i)Nombres?\s*[:\-]?\s*([A-ZÁÉÍÓÚÑ\s]{5,})",
        "contratante": r"(?i)Nombre\s*[:\-]?\s*(ASSURANCE CONTROLTECH(?: SAS)?)",
       # "objeto_contrato": r"(?i)NATURALEZA DEL TRABAJO A CONTRATAR[:\s]*([\s\S]+?)(?=\n\s*[A-Z])",
        "representante_legal": r"(?i)Representante Legal\s*[:\-]?\s*([A-ZÁÉÍÓÚÑ\s]{5,})"
    },
    "aprendizaje": {
        "numero_contrato": r"(?i)(?:contrato\s*(?:n[úu]mero|No\.?)\s*[:\-]?\s*)([\w\-\/]+)",
        "fecha_contrato": r"(?i)(?:fecha\s+del\s+contrato|fecha\s+de\s+suscripci[oó]n|fecha\s+documento)[\s:]*([\d]{1,2}[\/\-]\d{1,2}[\/\-]\d{4}|\d{1,2}\s+de\s+[a-záéíóú]+\s+de\s+\d{4})",
        "contratista": r"(?i)\b(?:aprendiz|contratista)\b\s*[:\-]?\s*([A-ZÁÉÍÓÚÑ][\w\s]{5,})(?=\s+(?:identificado|con|C[eé]dula|n[uú]mero)|$)",
        "contratante": r"(?i)(?:empresa|entidad|representada\s+por)\s*[:\-]?\s*([A-ZÁÉÍÓÚÑ][\w\s]+?)(?=\s+NIT|\s+C[eé]dula|$)",
        "partes_contrato": r"(?i)entre\s+los\s+suscritos[,:\s]+([\wÁÉÍÓÚÑ\s]+)\s+y\s+([\wÁÉÍÓÚÑ\s]+)",
        #"objeto_contrato": r"(?i)(?:objeto(?:\s+del\s+contrato)?[:\s]+)(.+?)(?:\.|\n|$)",
        "representante_legal": r"(?i)(?:representante\s+legal\s+(?:de\s+la\s+empresa|por\s+parte\s+de)?[:\s]*)([A-ZÁÉÍÓÚÑ][\w\s]+)(?=\s+C[eé]dula|\s+NIT|\s*$)",
        #"nombre_aprendiz": r"(?i)(?:nombre\s+(?:del\s+)?aprendiz\s*[:\-]?\s*)(?!representante)([A-ZÁÉÍÓÚÑ][\w\s]{5,})(?=\s+(?:identificado|con|C[eé]dula|n[uú]mero)|$)",
        "documento_aprendiz": r"(?i)C[ÉE]DULA O TARJETA IDENTIDAD\s*([\d\.]{6,15})",
        "empresa": r"(?i)(?:(?:empresa|entidad)(?:\s*contratante)?)[\s:]*([A-ZÁÉÍÓÚÑ][\w\s]+?)(?:\s*NIT|$)",
        #"representante_empresa": r"(?i)representante\s+legal\s+de\s+la\s+empresa\s*[:\-]?\s*([A-ZÁÉÍÓÚÑ][\w\s]+?)(?:\s*NIT|$)"
    },
    "prestacion_servicios": {
        "contratante": r"(?i)Entre los suscritos\s+([A-ZÁÉÍÓÚÑ\s]+?)\s+mayor de edad",
        "contratista": r"(?i)por una parte y,?\s+por otra\s+([A-ZÁÉÍÓÚÑ\s]+?)\s+mayor de edad",
        "fecha_contrato": r"(?i)acuerdan celebrar el presente contrato[^\n]+?el\s+(\d{1,2}\s+de\s+[A-ZÁÉÍÓÚÑa-záéíóúñ]+\s+de\s+\d{4})",
        #"objeto_contrato": r"(?i)El objeto del presente contrato\s+es\s+la\s+presentaci[oó]n\s+de\s+los\s+servicios\s+profesionales[^\.\n]{10,200}",
        "representante_legal": r"(?i)en nombre y representación de\s+([A-ZÁÉÍÓÚÑ\s\.]+?),?\s+Nit"
    },
    "documento_judicial_general": {
        "tipo_documento": r"(?i)(asunto|referencia|ref)[:\s]+([A-ZÁÉÍÓÚÑ\s]{5,})",
        "juez": r"(?i)(juzgado[\w\s\.]+)",
        "secretaria": r"(?i)(secretar[ií]a|secretario|informe secretarial)[:\s]+([A-ZÁÉÍÓÚÑ\s\.]+)",
        "fecha_oficio": r"(?i)(fecha\s+de\s+(oficio|providencia|respuesta|env[ií]o|radicaci[oó]n))[:\s]+(?:el\s+)?(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
        "demandante": r"(?i)([A-ZÁÉÍÓÚÑ\s\.]+?)\s+contra\s+",
        "demandado": r"(?i)contra\s+([A-ZÁÉÍÓÚÑ\s\.]+)",
        "radicado": r"(?i)(?:radicado|número de radicación)[:\s]+([\d\-]+)",
        "otorgante": r"(?i)yo[\s,]+([A-ZÁÉÍÓÚÑ\s]+),\s+mayor",
        "apoderado": r"(?i)otorgo\s+poder\s+especial\s+a\s+favor\s+de\s+([A-ZÁÉÍÓÚÑ\s]+),\s+identificado"
    },
    "documento_demanda": {
        "tipo_documento": r"(?i)(asunto|referencia|ref)[\s:]+([A-Z\s]{5,})",
        "juez": r"(?i)(juzgado.+?)\n",
        "secretaria": r"(?i)secretari[ao]:?\s+([A-ZÁÉÍÓÚÑ\s]+)",
        "fecha_oficio": r"(?i)(fecha\s+de\s+(providencia|oficio|env[ií]o|radicaci[oó]n))[:\s]+(?:el\s+)?(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
        "demandante": r"(?i)(?:demandante|parte demandante|promovido por)[:\s]+([A-ZÁÉÍÓÚÑ\s\.\&]+)",
        "demandado": r"(?i)(?:demandado|contra)[:\s]+([A-ZÁÉÍÓÚÑ\s]+)",
        "radicado": r"(?i)(radicado|número de radicación)[:\s]+([\d\-]+)"
    },

    "documento_poder": {
        "tipo_documento": r"(?i)(asunto|referencia|ref)[:\s]+([A-ZÁÉÍÓÚÑ\s]{5,})",
        "juez": r"(?i)(juzgado[\w\s\.]+)",
        "otorgante": r"(?i)yo[,\s]+([A-ZÁÉÍÓÚÑ\s]+),\s+mayor",
        "apoderado": r"(?i)otorgo\s+poder\s+(?:especial\s+)?a\s+favor\s+de\s+([A-ZÁÉÍÓÚÑ\s\.]+?),\s+identificado",
        "radicado": r"(?i)(?:radicado|número de radicación)[:\s]+([\d\-]+)",
        "demandante": r"(?i)(?:demandante|parte demandante|promovido por)[:\s]+([A-ZÁÉÍÓÚÑ\s\.\&]+)",
        "demandado": r"(?i)(?:demandado|contra)[:\s]+([A-ZÁÉÍÓÚÑ\s]+)",
        "secretaria": r"(?i)secretari[ao]:?\s+([A-ZÁÉÍÓÚÑ\s]+)"
    },

    "acta_reparto": {
        "radicado": r"(?i)radicad[oa]\s+n[úu]mero\s*[:\-]?\s*([\d\-]{6,})",
        "juez": r"(?i)se\s+reparte\s+al\s+(juzgado\s+[\w\s]+)",
        "demandante": r"(?i)(?:demandante|parte demandante|promovido por)[:\s]+([A-ZÁÉÍÓÚÑ\s\.\&]+)",
        "demandado": r"(?i)(?:demandado|contra)[:\s]+([A-ZÁÉÍÓÚÑ\s]+)",
        "secretaria": r"(?i)secretar[iaío]\s+(?:de|del)?\s*(juzgado\s+[\w\s]+)"
    },

    "respuesta_oficio": {
        "tipo_documento": r"(?i)(referencia|respuesta)[:\s]+([\w\s]+)",
        "juez": r"(?i)(juzgado[\w\s\.]+)",
        "secretaria": r"(?i)informe\s+secretaria",
        "fecha_oficio": r"(?i)fecha\s+(?:de\s+respuesta|env[ií]o|oficio)\s*[:\-]?\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})",
        "demandante": r"(?i)([A-ZÁÉÍÓÚÑ\s]+?)\s+contra\s+([A-ZÁÉÍÓÚÑ\s]+)",
        "demandado": r"(?i)(?:contra|demandado)[:\s]+([A-ZÁÉÍÓÚÑ\s]+)",
        "radicado": r"(?i)(?:radicado|número de radicación)[:\s\-]*([\d\-]{6,})"
    },

    "acta_notificacion": {
        "juez": r"(?i)(juzgado[\w\s\.]+)",
        "fecha_oficio": r"(?i)notificaci[oó]n\s+(?:electr[oó]nica\s+)?efectuada\s+el\s+(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})",
        "demandante": r"(?i)([A-ZÁÉÍÓÚÑ\s]+)\s+contra\s+([A-ZÁÉÍÓÚÑ\s]+)",
        "demandado": r"(?i)(?:demandado|contra)[:\s]+([A-ZÁÉÍÓÚÑ\s]+)",
        "radicado": r"(?i)(?:radicado|número de radicación)[:\s]+([\d\-]+)"
    }
}

# ---------------------- Normalización de sinónimos ----------------------
sinonimos = {
    "número del contrato": "numero_contrato",
    "fecha del contrato": "fecha_contrato",
    "nombre del contratista": "contratista",
    "nombre del contratante": "contratante",
    "partes del contrato": "partes_contrato",
    "objeto del contrato": "objeto_contrato",
    "representante legal": "representante_legal",
    "nombre representante": "representante_legal",
    "nombre del aprendiz": "nombre_aprendiz",
    "documento del aprendiz": "documento_aprendiz",
    "numero de contrato": "numero_contrato",
    "fecha inicio": "fecha_contrato",
    "numero factura": "numero de factura",
    "número factura": "numero de factura",
    "nit proveedor": "nit_proveedor",
    "tipo documento": "tipo_documento",
    "juez de la causa": "juez",
    "juez": "juez",
    "juzgado": "juez",
    "secretario": "secretaria",
    "nombre secretario": "secretaria",
    "fecha del oficio": "fecha_oficio",
    "radicado número": "radicado",
    "identificación aprendiz": "documento_aprendiz",
    "fecha firma": "fecha_contrato"
}

def extraer_objeto_contrato(texto):
    patrones = [
        r"(el objeto del presente contrato.*?\.)",
        r"(el contrato tiene por objeto.*?\.)",
        r"(tiene por objeto.*?\.)",
        r"(la naturaleza del trabajo.*?\.)",
        r"(el trabajador.*?prestar.*?servicios.*?\.)"
    ]
    for patron in patrones:
        match = re.search(patron, texto, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    return "No encontrado"

# ---------------------- Funciones de soporte ----------------------
def limpiar_valor(valor, campo):
    valor = re.sub(r'\s+', ' ', valor).strip(" .:-\n\t")
    valor = re.sub(r"[^\w\s\.,%$\-/]", "", valor)
    if campo == "numero_contrato":
        # Elimina palabras irrelevantes
        palabras_invalidas = ["vigencia", "implica", "tar", "contrato", "No", "encontrado"]
        for palabra in palabras_invalidas:
            if palabra.lower() in valor.lower():
                return "No encontrado"
        # Elimina caracteres no deseados
        valor = re.sub(r"[^A-Za-z0-9\-\.\/]", " ", valor).strip()
        return valor if valor else "No encontrado"
    elif campo == "fecha_contrato":
        # Valida si hay una fecha razonable
        if re.search(r"\d{1,2}[\-/ de]+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre|\d{1,2})[\-/ de]+\d{2,4}", valor, re.IGNORECASE):
            return valor
        return "No encontrado"
    return valor

def es_valor_relevante(valor):
    if not valor or not isinstance(valor, str): return False
    valor = valor.strip().lower()
    palabras_ignoradas = {"cliente", "proveedor", "prefijo", "fecha", "valor total", "documento", "contratista", "el contratista"}
    return valor not in palabras_ignoradas and len(valor) >= 3

def extraer_texto(file_path):
    texto = ""
    with fitz.open(file_path) as doc:
        for page in doc:
            texto += page.get_text()
    return texto

# ---------------------- Extracción con spaCy como fallback ----------------------
def extraer_con_spacy(texto, campo):
    doc = nlp(texto)
    campo = campo.lower()
    if "nombre" in campo:
        candidatos = [ent.text for ent in doc.ents if ent.label_ == "PER"]
    elif "fecha" in campo:
        candidatos = [ent.text for ent in doc.ents if ent.label_ == "DATE"]
    elif "valor" in campo or "monto" in campo:
        candidatos = [ent.text for ent in doc.ents if ent.label_ == "MONEY"]
    elif "nit" in campo:
        candidatos = re.findall(r"\b\d{7,10}-?\d?\b", texto)
    else:
        candidatos = [ent.text for ent in doc.ents if campo in ent.text.lower()]
    for c in candidatos:
        valor = limpiar_valor(c, campo)
        if es_valor_relevante(valor):
            return valor
    return "No encontrado"

def extraer_texto_con_ocr(pdf_path):
    texto = ""
    try:
        imagenes = convert_from_path(pdf_path)
        texto = "\n".join([pytesseract.image_to_string(imagen, lang='spa') for imagen in imagenes])
    except Exception as e:
        print(f"Error al aplicar OCR: {e}")
    return texto

#Identifica si el ocr es debil 
def texto_pobre(texto):
    palabras = texto.strip().split()
    
    # Reglas básicas
    pocas_palabras = len(palabras) < 30

    # Proporción de caracteres alfabéticos vs totales (evitar símbolos raros)
    total_chars = len(texto)
    alphas = len(re.findall(r'[A-Za-zÁÉÍÓÚáéíóúÑñ]', texto))
    proporcion_alfabetica = alphas / total_chars if total_chars else 0
    texto_ruidoso = proporcion_alfabetica < 0.5

    return pocas_palabras or texto_ruidoso

def metadatos_son_confiables(metadatos):
    claves_importantes = ['valor total', 'número de contrato', 'fecha del contrato']
    for clave in claves_importantes:
        valor = metadatos.get(clave, "").strip().lower()
        if not valor or valor in ["vigencia", "código", "empresa"]:
            return False
    return True

# ---------------------- Extracción por formato ----------------------
def extraer_por_formato(texto, campos_a_extraer):
    patrones = regex_por_formato.get(tipo_formato.lower(), {})
    resultado = {}
    for campo in campos_a_extraer:
        clave = sinonimos.get(campo.lower(), campo.lower())
        patron = patrones.get(clave)
        if patron:
            match = re.search(patron, texto, re.IGNORECASE)
            if match and match.lastindex:
                valor = limpiar_valor(match.group(1), campo)
                if es_valor_relevante(valor):
                    resultado[campo] = valor
                    continue
            resultado[campo] = extraer_con_spacy(texto, campo)
        else:
            resultado[campo] = extraer_con_spacy(texto, campo)
    return resultado

# ---------------------- Función principal ----------------------
def procesar_archivo(file_path, campos):
    """
    Extrae los campos manualmente desde el texto del PDF (ya extraído o con OCR si aplica).
    Busca coincidencias simples por nombre de campo dentro del texto.
    """
    texto_extraido = extraer_texto(file_path)
    resultado = {}

    for campo in campos:
        campo_formateado = campo.lower().replace("_", " ")
        encontrado = "No encontrado"

        for linea in texto_extraido.splitlines():
            if campo_formateado in linea.lower():
                encontrado = linea.strip()
                break

        resultado[campo] = encontrado

    return resultado


