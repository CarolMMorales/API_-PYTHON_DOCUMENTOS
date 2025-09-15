from io import BytesIO
import hashlib
from PIL import Image
from flask import send_file
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from pdf2image import convert_from_bytes

# Ruta a poppler (actualízala si cambia de ubicación)
POPPLER_PATH = r"C:\Users\cmorales\Downloads\poppler-24.08.0\Library\bin"

def calcular_hash(pdf_bytes):
    return hashlib.sha256(pdf_bytes).hexdigest()

def crear_pagina_firma(nombre_firmante, fecha_firma, hash_sha):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.setFont("Helvetica", 12)
    c.drawString(100, 750, "FIRMA ELECTRÓNICA")
    c.drawString(100, 730, f"Firmado por: {nombre_firmante}")
    c.drawString(100, 710, f"Fecha: {fecha_firma}")
    c.drawString(100, 690, f"Hash SHA-256: {hash_sha}")
    c.drawString(100, 670, "Este documento ha sido firmado electrónicamente.")
    c.save()
    buffer.seek(0)
    return buffer

def aplicar_restriccion_edicion(pdf_input: BytesIO) -> BytesIO:
    reader = PdfReader(pdf_input)
    writer = PdfWriter()

    for page in reader.pages:
        writer.add_page(page)

    # Encriptar sin requerir contraseña para abrir, pero con edición bloqueada
    writer.encrypt(
        user_password="",  # sin contraseña de apertura
        owner_password="bloqueofirma123",  # clave interna de protección
        permissions_flag=4  # permite imprimir, no editar
    )

    output = BytesIO()
    writer.write(output)
    output.seek(0)
    return output

def firmar_pdf_simple(pdf_bytes, firmante, fecha):
    # Calcular el hash del contenido original
    hash_sha = calcular_hash(pdf_bytes)

    # Crear página de firma electrónica
    pagina_firma_pdf = crear_pagina_firma(firmante, fecha, hash_sha)
    pagina_firma_bytes = pagina_firma_pdf.getvalue()

    # Unir documento original + página de firma
    pdf_completo = BytesIO()
    merger = PdfMerger()
    merger.append(BytesIO(pdf_bytes))
    merger.append(BytesIO(pagina_firma_bytes))
    merger.write(pdf_completo)
    merger.close()
    pdf_completo.seek(0)

    # Convertir PDF final a imágenes (1 imagen por página)
    imagenes = convert_from_bytes(pdf_completo.read(), dpi=200, poppler_path=POPPLER_PATH)
    print(f"[INFO] Se convirtieron {len(imagenes)} páginas a imagen.")

    # Crear nuevo PDF solo con imágenes (no editable)
    salida = BytesIO()
    c = canvas.Canvas(salida, pagesize=letter)

    for img in imagenes:
        img_io = BytesIO()
        img.save(img_io, format='PNG')
        img_io.seek(0)
        image_reader = ImageReader(img_io)
        c.drawImage(image_reader, 0, 0, width=letter[0], height=letter[1])
        c.showPage()

    c.save()
    salida.seek(0)

    # Aplicar protección contra edición
    pdf_protegido = aplicar_restriccion_edicion(salida)
    return pdf_protegido, hash_sha

