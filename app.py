import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
import mysql.connector
from datetime import datetime, timedelta
import cloudinary
import cloudinary.uploader
import requests 

app = Flask(__name__)
app.secret_key = "super_secreto_bodega"

# Hacemos que la sesión dure 30 días para no hartar a los choferes
app.permanent_session_lifetime = timedelta(days=30)

# ==========================================
# CONFIGURACIÓN DE SEGURIDAD (PIN MAESTRO)
# ==========================================
PIN_ACCESO = "2026" 

# ==========================================
# CONFIGURACIÓN DE CLOUDINARY (FOTOS EN LA NUBE)
# ==========================================
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

# ==========================================
# BARRERA DE SEGURIDAD (CANDADO)
# ==========================================
@app.before_request
def verificar_login():
    rutas_permitidas = ['login', 'static']
    if request.endpoint not in rutas_permitidas and not session.get('logeado'):
        return redirect(url_for('login'))

# ==========================================
# RUTAS DE LA APLICACIÓN
# ==========================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        pin_ingresado = request.form.get('pin')
        if pin_ingresado == PIN_ACCESO:
            session.permanent = True
            session['logeado'] = True
            return redirect(url_for('index'))
        else:
            flash("PIN incorrecto. Intenta de nuevo.", "danger")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logeado', None)
    return redirect(url_for('login'))

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
    
    campos_fotos = ['evidencia', 'evidencia2', 'evidencia3', 'evidencia4']
    urls_subidas = []

    for campo in campos_fotos:
        foto = request.files.get(campo)
        if foto and foto.filename != '':
            respuesta_nube = cloudinary.uploader.upload(foto)
            urls_subidas.append(respuesta_nube.get("secure_url"))

    ruta_foto_final = "|\n".join(urls_subidas) if urls_subidas else ""

    ahora = datetime.now()
    hora_salida_str = ahora.strftime('%H:%M:%S')
    tiempo_regreso = ahora + timedelta(minutes=minutos_estimados)
    hora_regreso_str = tiempo_regreso.strftime('%H:%M:%S')

    conexion = obtener_conexion()
    
    cursor_lectura = conexion.cursor(dictionary=True)
    cursor_lectura.execute("SELECT rem_productos, rem_productos_originales, cliente_nombre, cli_telefono, rem_serie FROM tblEntregasResp2 WHERE num_viaje = %s", (num_viaje,))
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
        nuevo_estatus_original, ruta_foto_final, hora_salida_str, hora_regreso_str, 
        unidad_num, unidad_nombre, unidad_chofer, 
        texto_cargados, texto_historico, num_viaje
    ))
    
    conexion.commit()
    cursor.close()
    conexion.close()

    # ==========================================
    # DETERMINAR TELÉFONO DE SUCURSAL SEGÚN SERIE
    # ==========================================
    serie = viaje_original.get('rem_serie', '')
    letra = serie[0].upper() if serie else ''

    if letra == 'A':
        telefono_sucursal = "7544740046"
    else:
        # Serie B, C o cualquier otra
        telefono_sucursal = "7544741035"

    # ==========================================
    # CONEXIÓN DIRECTA CON MAKE.COM (WHATSAPP)
    # ==========================================
    datos_webhook = {
    "num_viaje": num_viaje,
    "cliente_nombre": viaje_original['cliente_nombre'],
    "telefono_cliente": viaje_original['cli_telefono'],
    "chofer": unidad_chofer,
    "vehiculo": unidad_nombre,
    "minutos_estimados": minutos_estimados,
    "estatus": nuevo_estatus_original,
    "evidencias": ruta_foto_final,
    "telefono_sucursal": telefono_sucursal,
    "hora_salida": ahora.strftime('%H:%M')
    }
    
    try:
        url_make = "https://hook.us2.make.com/yaoan84hqutqwghstajxz0ji4bm7gkkt"
        requests.post(url_make, json=datos_webhook, timeout=5)
    except Exception as e:
        print(f"Error al comunicar con Make: {e}")

    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

