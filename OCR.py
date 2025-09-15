#importacion de librerias
from flask import Flask, request, jsonify
import pytesseract
import os, sys, tempfile, uuid, unicodedata
import PyPDF2
from concurrent.futures import ThreadPoolExecutor
from pdf2image import convert_from_path
import shutil
import glob
import fitz  # PyMuPDF para PDF
from datetime import datetime
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
import ast
import json 

sys.path.append(os.getcwd())
# Importamos las funciones de metadata_extractor
from MetadataExtractor import (
    procesar_archivo,
    extraer_texto,
    texto_pobre,
    extraer_texto_con_ocr,
    sinonimos
)
#importamos funcion de chatgpt_extractor
from ChatgptExtractor import extraer_metadatos_y_resumen_con_gpt

app = Flask(__name__)

# Configuración de rutas para Tesseract y Poppler
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
os.environ["TESSDATA_PREFIX"] = r"C:\Program Files\Tesseract-OCR\tessdata"
POPPLER_PATH = r"C:\Users\cmorales\Downloads\poppler-24.08.0\Library\bin"

#procesa la imagen y la mejora (pone a blanco y negro para aclarar y mejorar la letra) asi mismo para mejorar la calidad del ocr
def preprocesar_imagen(pil_image):
    """Mejora la imagen antes de aplicar OCR"""
    
    # Convertir de PIL a OpenCV (RGB → BGR → Gray)
    image = np.array(pil_image)
    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)  # OpenCV usa BGR
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Escalar si es una imagen de baja resolución (mejora OCR en letras pequeñas)
    if gray.shape[0] < 1000 or gray.shape[1] < 1000:
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    # Filtro bilateral para eliminar ruido conservando bordes
    gray = cv2.bilateralFilter(gray, 9, 75, 75)

    # Umbralización adaptativa (mejor que binarización fija)
    binarizada = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        cv2.THRESH_BINARY, 31, 10
    )

    # Convertir de nuevo a PIL
    pil_preprocessed = Image.fromarray(binarizada)
    return pil_preprocessed

#le aplica el ocr a la imagen
def aplicar_ocr_pdf(pdf_path):
    images = convert_from_path(pdf_path, poppler_path=POPPLER_PATH)
    texto_extraido = "\n".join([pytesseract.image_to_string(img) for img in images])
    return texto_extraido

#verifica si el pdf es valido y que no este corrupto de alguna manera 
def es_pdf_valido(pdf_path):
    """Verifica si un PDF puede abrirse sin errores."""
    try:
        with open(pdf_path, "rb") as file:
            PyPDF2.PdfReader(file)
        return True
    except Exception:
        return False

#verifica si el pdf ya tiene ocr, si no lo tiene se le aplica, si lo tiene se deja el documento igual 
def tiene_ocr(pdf_path):
    """Verifica si un PDF ya tiene OCR."""
    try:
        with open(pdf_path, "rb") as file:
            reader = PyPDF2.PdfReader(file)
            for page in reader.pages:
                text = page.extract_text()
                if text and text.strip():
                    return True
    except Exception as e:
        print(f"Error al leer {pdf_path}: {e}")
        return False  
    return False

#procesa pagina por pagina de un documento para aplicarle el ocr
def procesar_pagina(image, index, temp_folder):
    """Aplica OCR a una imagen y la guarda como PDF."""
    temp_pdf_path = os.path.join(temp_folder, f"page_{index}.pdf")
    image = preprocesar_imagen(image)
    pdf_data = pytesseract.image_to_pdf_or_hocr(image, lang="spa", extension="pdf")
    
    with open(temp_pdf_path, "wb") as f:
        f.write(pdf_data)
    
    return temp_pdf_path


def pdf_imagen_a_pdf_ocr(pdf_path):
    """Convierte un PDF de imágenes a un PDF con OCR."""
    print(f"Procesando PDF: {pdf_path}")
    #Crear carpeta temporal en la misma ubicación del archivo PDF
    pdf_dir = os.path.dirname(pdf_path)
    pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
    temp_folder = os.path.join(pdf_dir, f"temp_{pdf_name}")
    os.makedirs(temp_folder, exist_ok=True)
    print(f" Carpeta temporal creada: {temp_folder}")
    # Convertir PDF a imágenes
    images = convert_from_path(pdf_path, poppler_path=POPPLER_PATH)

    # Aplicar OCR en paralelo
    with ThreadPoolExecutor() as executor:
        temp_pdf_paths = list(executor.map(lambda args: procesar_pagina(*args), 
                                           [(image, i, temp_folder) for i, image in enumerate(images)]))

    # Combinar los PDFs en un solo archivo
    temp_output_pdf = os.path.join(pdf_dir, f"temp_{pdf_name}.pdf")
    try:
        pdf_merger = PyPDF2.PdfMerger()
        for temp_pdf in sorted(temp_pdf_paths):
            pdf_merger.append(temp_pdf)
        pdf_merger.write(temp_output_pdf)
        pdf_merger.close()
        print(f"PDF con OCR generado: {temp_output_pdf}")
    except Exception as e:
        print(f" Error generando PDF con OCR: {e}")
        shutil.rmtree(temp_folder)
        return # evita seguir si falla

    # Verificar que se haya generado correctamente
    if not os.path.exists(temp_output_pdf) or os.path.getsize(temp_output_pdf) == 0:
        print("⚠️ PDF generado está vacío. No se reemplazará el original.")
        shutil.rmtree(temp_folder)
        return

    # Reemplazar el original
    try:
        os.remove(pdf_path)  # Borrar el original primero (importante si estaba bloqueado)
        shutil.move(temp_output_pdf, pdf_path)
        print(f" PDF original reemplazado por versión con OCR: {pdf_path}")
    except Exception as e:
        print(f" Error al reemplazar el archivo original: {e}")
        return

    # Eliminar carpeta temporal
    shutil.rmtree(temp_folder)
    print(f"Carpeta temporal eliminada: {temp_folder}")


#función principal para procesar el archivo 
def procesar_pdf(file_path):
    resultados = []
    if not es_pdf_valido(file_path):
        return [{"filename": file_path, "message": "Archivo corrupto, no procesado"}]
    '''
    if tiene_ocr(file_path):
        resultados.append({
            "filename": os.path.basename(file_path),
            "message": "El PDF ya contiene texto. No se aplica OCR."
        })
    else:
        print("El PDF no contiene texto. Aplicando OCR...")
        pdf_imagen_a_pdf_ocr(file_path)
        resultados.append({
            "filename": f"ocr_{os.path.basename(file_path)}",
            "message": "OCR aplicado, pero no se detectó texto. Verificar archivo."
        })
    '''
    print("El PDF no contiene texto. Aplicando OCR...")
    pdf_imagen_a_pdf_ocr(file_path)
    
    resultados.append({
        "filename": f"{os.path.basename(file_path)}",
        "message": "OCR aplicado, pero no se detectó texto. Verificar archivo." 
    })   
    return resultados


#normaliza los metadatos para que sean más faciles de encontrar 
def normalizar(texto):
    """Normaliza texto: quita tildes, espacios extra, pasa a minúsculas y aplica sinónimos"""
    if not texto:
        return ""
    texto = texto.lower().strip()
    texto = unicodedata.normalize('NFKD', texto)
    texto = ''.join([c for c in texto if not unicodedata.combining(c)])
    return sinonimos.get(texto, texto)


