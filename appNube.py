import os
from flask import Flask, render_template, request, redirect, url_for
import mysql.connector
from datetime import datetime, timedelta

# NUEVAS IMPORTACIONES PARA LA NUBE
import cloudinary
import cloudinary.uploader

app = Flask(__name__)
app.secret_key = "super_secreto_bodega"

# ==========================================
# CONFIGURACIÓN DE CLOUDINARY (FOTOS EN LA NUBE)
# ==========================================
# Reemplaza estos datos con los de tu panel de Cloudinary
cloudinary.config(
  cloud_name = "dxkrhdljz",
  api_key = "634847558949229",
  api_secret = "wy_CbHDnHupNr7mES6jvU1iXHbI",
  secure = True
)

# ==========================================
# CONFIGURACIÓN DE TU BASE DE DATOS MYSQL
# ==========================================
DB_CONFIG = {
    'host': 'bomwnxr5gjbommztspn6-mysql.services.clever-cloud.com',
    'user': 'u6i0hfqztfsh9bqe',
    'password': 's2T0OaYv5PgrkIr7Wt23',
    'database': 'bomwnxr5gjbommztspn6',
    'port': 3306
}

def obtener_conexion():
    return mysql.connector.connect(**DB_CONFIG)

@app.route('/')
def index():
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM tblEntregasResp2 WHERE TRIM(UPPER(rem_estatus)) IN ('PENDIENTE', 'PENDIENTE PARCIAL')")
    pedidos = cursor.fetchall()
    
    cursor.close()
    conexion.close()
    return render_template('index.html', pedidos=pedidos)

@app.route('/pedido/<int:num_viaje>')
def detalle_pedido(num_viaje):
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM tblEntregasResp2 WHERE num_viaje = %s", (num_viaje,))
    pedido = cursor.fetchone()
    
    cursor.execute("SELECT unidad_id, unidad_nombre FROM unidades ORDER BY unidad_id")
    unidades = cursor.fetchall()
    
    cursor.execute("SELECT nombre FROM empleados ORDER BY nombre")
    empleados = cursor.fetchall()
    
    productos_lista = []
    if pedido and pedido['rem_productos']:
        texto_productos = pedido['rem_productos']
        
        if '|' in texto_productos:
            productos_brutos = texto_productos.split('|')
        else:
            texto_temp = texto_productos.replace('\n', ',').replace('\r', ',')
            productos_brutos = texto_temp.split(',')
            
        productos_lista = [prod.strip() for prod in productos_brutos if prod.strip()]

    cursor.close()
    conexion.close()
    return render_template('detalle.html', pedido=pedido, productos=productos_lista, unidades=unidades, empleados=empleados)

@app.route('/procesar_salida', methods=['POST'])
def procesar_salida():
    num_viaje = request.form.get('num_viaje')
    minutos_estimados = int(request.form.get('minutos_estimados'))
    
    indices_cargados = request.form.getlist('productos_seleccionados')
    
    datos_unidad = request.form.get('unidad')
    unidad_num, unidad_nombre = datos_unidad.split('|')
    unidad_chofer = request.form.get('chofer')
    
    # ==========================================
    # NUEVA LÓGICA: SUBIR FOTO A CLOUDINARY
    # ==========================================
    foto = request.files.get('evidencia')
    ruta_foto = ""
    if foto and foto.filename != '':
        # Esto manda la foto a internet automáticamente
        respuesta_nube = cloudinary.uploader.upload(foto)
        # Aquí obtenemos el link seguro (https://...) que nos regresa Cloudinary
        ruta_foto = respuesta_nube.get("secure_url")

    ahora = datetime.now()
    hora_salida_str = ahora.strftime('%H:%M:%S')
    tiempo_regreso = ahora + timedelta(minutes=minutos_estimados)
    hora_regreso_str = tiempo_regreso.strftime('%H:%M:%S')

    conexion = obtener_conexion()
    
    cursor_lectura = conexion.cursor(dictionary=True)
    cursor_lectura.execute("SELECT rem_productos, rem_productos_originales FROM tblEntregasResp2 WHERE num_viaje = %s", (num_viaje,))
    viaje_original = cursor_lectura.fetchone()
    cursor_lectura.close()

    texto_original = viaje_original['rem_productos']
    texto_historico = viaje_original['rem_productos_originales'] if viaje_original['rem_productos_originales'] else texto_original

    if '|' in texto_original:
        productos_brutos = texto_original.split('|')
    else:
        texto_temp = texto_original.replace('\n', ',').replace('\r', ',')
        productos_brutos = texto_temp.split(',')
        
    productos_originales_lista = [prod.strip() for prod in productos_brutos if prod.strip()]
    
    productos_cargados = []
    productos_pendientes = []
    
    for i, prod in enumerate(productos_originales_lista):
        if str(i) in indices_cargados:
            productos_cargados.append(prod)
        else:
            productos_pendientes.append(prod)

    texto_cargados = "|\n".join(productos_cargados)
    texto_pendientes = "|\n".join(productos_pendientes)

    if productos_pendientes:
        nuevo_estatus_original = 'ENTREGA PARCIAL'
    else:
        nuevo_estatus_original = 'TRANSITO'

    cursor = conexion.cursor()
    
    if productos_pendientes:
        consulta_clon = """
            INSERT INTO tblEntregasResp2 (
                fecha, dia, mes, year, rem_num, rem_serie, rem_hora,
                entrega_hoy, fechaprogramada, cliente_nombre, cliente_domicilio,
                cliente_zona, rem_importe, rem_tipopago, rem_tipoviaje,
                rem_pesokg, empleado, cli_telefono, cli_mail, rem_fecha_entrega,
                rem_productos, rem_estatus, rem_productos_originales,
                unidad_num, unidad_nombre, unidad_chofer, comentarios
            )
            SELECT
                fecha, dia, mes, year, rem_num, rem_serie, rem_hora,
                entrega_hoy, fechaprogramada, cliente_nombre, cliente_domicilio,
                cliente_zona, rem_importe, rem_tipopago, rem_tipoviaje,
                rem_pesokg, empleado, cli_telefono, cli_mail, rem_fecha_entrega,
                %s, 'PENDIENTE PARCIAL', %s,
                '', '', '', 'Creado por faltante de entrega parcial'
            FROM tblEntregasResp2
            WHERE num_viaje = %s
        """
        cursor.execute(consulta_clon, (texto_pendientes, texto_historico, num_viaje))

    consulta_update = """
        UPDATE tblEntregasResp2 
        SET rem_estatus = %s, 
            foto_evidencia = %s,
            rem_horadesalida = %s,
            rem_horaregresoestimadocma = %s,
            unidad_num = %s,
            unidad_nombre = %s,
            unidad_chofer = %s,
            rem_productos = %s,
            rem_productos_originales = %s
        WHERE num_viaje = %s
    """
    cursor.execute(consulta_update, (
        nuevo_estatus_original, ruta_foto, hora_salida_str, hora_regreso_str, 
        unidad_num, unidad_nombre, unidad_chofer, 
        texto_cargados, texto_historico, num_viaje
    ))
    
    conexion.commit()
    cursor.close()
    conexion.close()
    
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)