#importacion de librerias
from flask import Flask, request, jsonify
import os, sys
import PyPDF2
import glob
from datetime import datetime
import json 

sys.path.append(os.getcwd())
# Importamos las funciones de metadata_extractor
from MetadataExtractor import (
    procesar_archivo,
    extraer_texto,
    texto_pobre,
    extraer_texto_con_ocr
)

from OCR import(
    es_pdf_valido,
    tiene_ocr,
    procesar_archivo,
    pdf_imagen_a_pdf_ocr,
    procesar_pdf
)

from FirmaDigital import(
    firmar_pdf_simple,
    send_file
)

#importamos funcion de chatgpt_extractor
from ChatgptExtractor import extraer_metadatos_y_resumen_con_gpt

app = Flask(__name__)

#pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'
os.environ["TESSDATA_PREFIX"] = '/usr/share/tesseract-ocr/4.00/tessdata'
POPPLER_PATH = '/usr/bin' 


#Ruta para utilizar el api en la funcion de convertir pdf imagen a pdf con ocr 
@app.route('/procesar-pdf-ruta', methods=['POST'])
def procesar_pdf_desde_ruta():
    """Recibe una lista de archivos o carpetas y los procesa."""
    data = request.json
    print("Datos recibidos:", data)

    if 'files' not in data or not isinstance(data['files'], list):
        return jsonify({"error": "No se envió una lista válida de archivos"}), 400

    resultados = []

    for archivo in data['files']:
        file_path = archivo.get('file_path')

        if not file_path or not os.path.exists(file_path):
            print(f"Error: El archivo no existe o la ruta no es válida: {file_path}")
            resultados.append({"file_path": file_path, "error": "El archivo no existe o la ruta no es válida"})
            continue

        # 📂 Si `file_path` es una carpeta, buscar todos los PDFs dentro
        if os.path.isdir(file_path):
            pdf_files = glob.glob(os.path.join(file_path, "*.pdf"))  # Lista de PDFs en la carpeta
            if not pdf_files:
                resultados.append({"folder": file_path, "error": "No se encontraron archivos PDF en la carpeta."})
                continue

            for pdf in pdf_files:
                print(f"Procesando en este computador: {pdf} ")
                resultado = procesar_pdf(pdf)
                resultados.extend(resultado)

        else:
            # 📄 Si `file_path` es un archivo PDF individual, procesarlo normalmente
            print(f"Procesando en este computador: {file_path} ")
            resultado = procesar_pdf(file_path)
            resultados.extend(resultado)

    print("Resultados del procesamiento:", resultados)
    return jsonify(resultados)

#Ruta para utilizar el api en la función de extracción de metadatos con (metadata_extrator_v1) 
@app.route('/extraer-metadata', methods=['POST'])
def extraer_metadata_desde_ruta():
    """Extrae metadatos definidos por el usuario desde archivos o carpetas."""
    data = request.json
    if 'files' not in data or not isinstance(data['files'], list):
        return jsonify({"error": "No se envió una lista válida de archivos"}), 400

    resultados = []
    for archivo in data['files']:
        file_path = archivo.get('file_path')
        campos = archivo.get('campos', [])

        if not file_path or not os.path.exists(file_path):
            resultados.append({"file_path": file_path, "error": "El archivo o carpeta no existe"})
            continue

        if os.path.isdir(file_path):
            for item in os.listdir(file_path):
                full_path = os.path.join(file_path, item)
                if os.path.isfile(full_path):
                    metadata = procesar_archivo(full_path, campos)
                    metadata_list = [f"{k}: {v}" for k, v in metadata.items()]
                    resultados.append({"file_path": full_path, "metadata": metadata_list})
        else:
            metadata = procesar_archivo(file_path, campos)
            metadata_list = [f"{k}: {v}" for k, v in metadata.items()]
            resultados.append({"file_path": file_path, "metadata": metadata_list})

    print("Resultados del procesamiento:", resultados)
    return jsonify(resultados)

#Ruta para consumir la funcion de extracción de metadatos y generar resumen con OpenAI


@app.route('/extraer-metadatos-gpt', methods=['POST'])
def extraer_metadatos_gpt():
    data = request.json
    archivos = data.get("files")
    print("Datos recibidos:", archivos, data)

    if not archivos or not isinstance(archivos, list):
        return jsonify({"error": "Se debe enviar una lista 'files' con los documentos"}), 400

    # Validar tokens
    try:
        token_entrada = int(data.get("token_entrada"))
        token_salida = int(data.get("token_salida"))
        if token_entrada <= 0 or token_salida <= 0:
            raise ValueError
        if token_entrada + token_salida > 128000:
            return jsonify({
                "error": "La suma de token_entrada y token_salida no debe superar 128000 para GPT-4 Turbo."
            }), 400
    except (ValueError, TypeError):
        return jsonify({
            "error": "Los valores de 'token_entrada' y 'token_salida' deben ser números enteros positivos."
        }), 400
    print(f" Tokens recibidos - Entrada: {token_entrada}, Salida: {token_salida}")
    resultados = []
    for archivo in archivos:
        file_path = archivo.get("file_path")
        campos = archivo.get("campos", [])
        incluir_resumen = archivo.get("incluir_resumen", True)

        if isinstance(incluir_resumen, str):
            incluir_resumen = incluir_resumen.lower() == "true"
        else:
            incluir_resumen = bool(incluir_resumen)

        if not file_path or not os.path.exists(file_path):
            resultados.append({"file_path": file_path, "error": "Ruta inválida o inexistente"})
            continue

        texto = extraer_texto(file_path)
        if texto_pobre(texto):
            texto = extraer_texto_con_ocr(file_path)

        if not texto.strip():
            resultados.append({"file_path": file_path, "error": "No se pudo extraer texto"})
            continue

        resultado_raw = extraer_metadatos_y_resumen_con_gpt(
            texto,
            token_entrada,
            token_salida,
            campos,
            incluir_resumen=incluir_resumen
        )

        # Limpieza y parseo seguro del resultado
        texto_limpio = resultado_raw.replace("“", "\"").replace("”", "\"").replace("‘", "'").replace("’", "'").strip()

        if not texto_limpio.startswith("["):
            texto_limpio = "[" + texto_limpio
        if not texto_limpio.endswith("]"):
            texto_limpio += "]"

        try:
            resultado = json.loads(texto_limpio)
            salida = {
                "file_path": file_path,
                "metadata": [item for item in resultado if not item.lower().startswith("resumen:")]
            }

            resumen_item = next((item for item in resultado if item.lower().startswith("resumen:")), None)
            if resumen_item:
                salida["resumen"] = resumen_item.replace("resumen:", "").strip()

            resultados.append(salida)
        except Exception as e:
            resultados.append({
                "file_path": file_path,
                "error": "Respuesta de GPT no es JSON válido",
                "resultado_raw": resultado_raw,
                "detalle": str(e)
            })

    print("Resultados del procesamiento:", resultados)
    return jsonify(resultados)

#Ruta ocr para expedientes
@app.route('/procesar-expedientes-masivos', methods=['POST'])
def procesar_expedientes_masivos():
    """Recibe una lista de archivos o carpetas y los procesa."""
    data = request.json
    print("Datos recibidos:", data)

    if 'files' not in data or not isinstance(data['files'], list):
        return jsonify({"error": "No se envió una lista válida de archivos"}), 400

    resultados = []

    for archivo in data['files']:
        file_path = archivo.get('file_path')

        if not file_path or not os.path.exists(file_path):
            print(f"Error: El archivo no existe o la ruta no es válida: {file_path}")
            resultados.append({"file_path": file_path, "error": "El archivo no existe o la ruta no es válida"})
            continue

        # 📂 Si `file_path` es una carpeta, buscar todos los PDFs dentro
        if os.path.isdir(file_path):
            pdf_files = glob.glob(os.path.join(file_path, "*.pdf"))  # Lista de PDFs en la carpeta
            if not pdf_files:
                resultados.append({"folder": file_path, "error": "No se encontraron archivos PDF en la carpeta."})
                continue

            for pdf in pdf_files:
                print(f"Procesando en este computador: {pdf} ")
                if not es_pdf_valido(pdf):
                    resultados.append({"file_path": pdf, "error": "PDF inválido o corrupto"})
                    continue

                # Aplicar OCR si no tiene
                if not tiene_ocr(pdf):
                    pdf_imagen_a_pdf_ocr(pdf)

                # Extraer info del archivo
                stat = os.stat(pdf)
                pdf_reader = PyPDF2.PdfReader(pdf)
                 # Obtener el nombre del documento sin la extensión
                nombre_documento = os.path.basename(pdf)  # Obtener solo el nombre del archivo
                nombre_documento_sin_extension = nombre_documento[:nombre_documento.rfind('.')]

                info = {
                    "nombre_documento": nombre_documento_sin_extension,
                    "file_path": pdf,
                    "fecha_creacion": datetime.fromtimestamp(stat.st_ctime).strftime("%d/%m/%Y %H:%M"),
                    "fecha_modificacion": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
                    "tamano": stat.st_size,
                    "paginas": len(pdf_reader.pages),
                    "extension": "pdf",
                    "pagina_inicial": 1,
                    "pagina_final": len(pdf_reader.pages)
                }
                resultados.append(info)

        else:
            # 📄 Si `file_path` es un archivo PDF individual, procesarlo normalmente
            print(f"Procesando en este computador: {file_path} ")
            if not es_pdf_valido(file_path):
                resultados.append({"file_path": file_path, "error": "PDF inválido o corrupto"})
                continue

            # Aplicar OCR si no tiene
            if not tiene_ocr(file_path):
                pdf_imagen_a_pdf_ocr(file_path)

            # Extraer info del archivo
            stat = os.stat(file_path)
            pdf_reader = PyPDF2.PdfReader(file_path)

            info = {
                "nombre_documento": os.path.basename(file_path),
                "file_path": file_path,
                "fecha_creacion": datetime.fromtimestamp(stat.st_ctime).strftime("%d/%m/%Y %H:%M"),
                "fecha_modificacion": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
                "tamano": stat.st_size,
                "paginas": len(pdf_reader.pages),
                "extension": "pdf",
                "pagina_inicial": 1,
                "pagina_final": len(pdf_reader.pages)
            }
            resultados.append(info)

    print("Resultados del procesamiento:", resultados)
    return jsonify(resultados)


#Ruta para Firma digital 

@app.route('/firmar-pdf', methods=['POST'])
def firmar_pdf_endpoint():
    data = request.json
    if not data:
        return jsonify({"error": "No se recibió JSON"}), 400

    file_path = data.get("file_path")
    firmante = data.get("firmante", "Desconocido")
    fecha = data.get("fecha", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "La ruta del archivo PDF es inválida o no existe"}), 400

    try:
        with open(file_path, "rb") as f:
            contenido_pdf = f.read()

        pdf_firmado, hash_sha = firmar_pdf_simple(contenido_pdf, firmante, fecha)

        base_nombre = os.path.splitext(os.path.basename(file_path))[0]
        nombre_salida = f"{base_nombre}_firmado.pdf"
        #ruta_base = r"C:\Firmados"
        #os.makedirs(ruta_base, exist_ok=True)
        ruta_base = os.path.dirname(file_path) 
        ruta_salida = os.path.join(ruta_base, nombre_salida)

        with open(ruta_salida, "wb") as f:
            f.write(pdf_firmado.read())

        resultado = {
            "archivo_firmado": nombre_salida,
            "fecha_firma": fecha,
            "hash_sha256": hash_sha,
            "ruta_guardado": ruta_salida
        }

        print(resultado)   # 👈 imprime en consola
        return jsonify([resultado])

        
    except Exception as e:
        return jsonify({"error": f"No se pudo firmar: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
