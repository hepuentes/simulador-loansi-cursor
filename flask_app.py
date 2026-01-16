import os
from collections import defaultdict
from functools import wraps
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
    abort,
    make_response,
)
from flask_wtf.csrf import CSRFProtect, CSRFError
from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta
import math
import hashlib
from werkzeug.security import generate_password_hash, check_password_hash
import json
import traceback
import time
import shutil
import sqlite3

# ============================================
# IMPORTS PARA SQLite (reemplazan JSON)
# ============================================
from db_helpers import (
    cargar_configuracion as cargar_config_db,
    guardar_configuracion as guardar_config_db,
    cargar_scoring as cargar_scoring_db,
    guardar_scoring as guardar_scoring_db,
    cargar_evaluaciones as cargar_evaluaciones_db,
    guardar_evaluacion as guardar_evaluacion_db,
    actualizar_evaluacion as actualizar_evaluacion_db,
    cargar_simulaciones as cargar_simulaciones_db,
    guardar_simulacion as guardar_simulacion_db,
    obtener_casos_comite,
    contar_casos_nuevos_asesor,
    obtener_usuario,
    crear_usuario,
    eliminar_linea_credito_db,
    eliminar_usuario_db,
    resolve_visible_usernames,
)

from db_helpers_scoring_linea import (
    obtener_lineas_credito_scoring,
    obtener_config_scoring_linea,
    guardar_config_scoring_linea,
    obtener_niveles_riesgo_linea,
    guardar_niveles_riesgo_linea,
    obtener_factores_rechazo_linea,
    guardar_factores_rechazo_linea,
    agregar_factor_rechazo_linea,
    eliminar_factor_rechazo,
    obtener_criterios_linea,
    guardar_criterio_linea,
    copiar_config_scoring,
    cargar_scoring_por_linea,
    invalidar_cache_scoring_linea,
    verificar_tablas_scoring_linea,
    crear_config_scoring_linea_defecto,
)

# ============================================
# SISTEMA DE PERMISOS GRANULARES
# ============================================
from permisos import (
    inicializar_permisos,
    tiene_permiso,
    tiene_alguno_de,
    tiene_todos,
    requiere_permiso,
    requiere_alguno_de,
    requiere_rol,
    obtener_permisos_usuario_actual,
    invalidar_cache_permisos,
)

# FUNCIONES DE ESTADOS DE CRÉDITO (desembolso/desistido)
from db_helpers_estados import (
    marcar_desembolsado,
    marcar_desistido,
    revertir_estado_final,
    obtener_casos_por_estado_final,
    obtener_estadisticas_estados,
    obtener_resumen_asesor,
    obtener_caso_completo,
)

# FUNCIONES PARA DASHBOARD
from db_helpers_dashboard import obtener_estadisticas_por_rol, obtener_resumen_navbar
import logging

# ============================================
# LOGGING PARA ERRORES CRÍTICOS (desarrollo)
# ============================================
# Solo nivel ERROR - no genera archivos, va a consola de PythonAnywhere
logging.basicConfig(
    level=logging.ERROR,  # Solo errores graves (no INFO ni DEBUG)
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ============================================
# MODO DEBUG PARA SQLITE (producción)
# ============================================
# Cambia a True para ver logs detallados de operaciones SQLite
SQLITE_DEBUG = True


def log_db_operation(operation, details="", level="INFO"):
    """
    Logger específico para operaciones de base de datos.
    Facilita debugging en producción.

    Args:
        operation (str): Nombre de la operación (ej: "CARGAR_EVALUACIONES")
        details (str): Detalles adicionales
        level (str): INFO, WARNING, ERROR
    """
    if not SQLITE_DEBUG and level == "INFO":
        return

    timestamp = datetime.now().strftime("%H:%M:%S")
    prefix = {"INFO": "🔵", "WARNING": "⚠️", "ERROR": "❌"}.get(level, "ℹ️")

    message = f"{prefix} [{timestamp}] SQLite-{operation}"
    if details:
        message += f": {details}"

    print(message)  # Va a logs de PythonAnywhere


# ============================================
# FUNCIONES HELPER SQLITE - DB OPERATIONS
# ============================================


def registrar_auditoria(usuario, accion, descripcion, detalles=None):
    """
    Registra una acción de auditoría en el sistema.
    Por ahora hace logging, pero puede extenderse para guardar en BD.
    
    Args:
        usuario (str): Usuario que realizó la acción
        accion (str): Tipo de acción (ej: "SCORING_CONFIG_UPDATE")
        descripcion (str): Descripción de la acción
        detalles (str): Detalles adicionales en formato JSON (opcional)
    """
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"📝 AUDITORÍA [{timestamp}] Usuario: {usuario} | Acción: {accion} | {descripcion}"
        if detalles:
            log_message += f" | Detalles: {detalles}"
        print(log_message)
        
        # Opcionalmente, guardar en tabla de auditoría si existe
        try:
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "loansi.db")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Verificar si existe la tabla de auditoría
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='auditoria'")
            if cursor.fetchone():
                cursor.execute("""
                    INSERT INTO auditoria (usuario, accion, descripcion, detalles, fecha)
                    VALUES (?, ?, ?, ?, ?)
                """, (usuario, accion, descripcion, detalles, timestamp))
                conn.commit()
            conn.close()
        except Exception as e:
            # Si falla guardar en BD, solo loggeamos (no es crítico)
            pass
            
    except Exception as e:
        print(f"⚠️ Error en auditoría: {e}")


def leer_evaluaciones_db():
    """
    Lee todas las evaluaciones desde SQLite.
    Retorna lista de diccionarios con las evaluaciones.
    """
    try:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "loansi.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM evaluaciones
            ORDER BY fecha_creacion DESC
        """
        )

        rows = cursor.fetchall()
        conn.close()

        evaluaciones = []
        for row in rows:
            evaluacion = dict(row)

            # Deserializar campos JSON
            if evaluacion.get("resultado"):
                try:
                    evaluacion["resultado"] = json.loads(evaluacion["resultado"])
                except:
                    pass

            if evaluacion.get("criterios_evaluados"):
                try:
                    evaluacion["criterios_evaluados"] = json.loads(
                        evaluacion["criterios_evaluados"]
                    )
                except:
                    evaluacion["criterios_evaluados"] = []

            if evaluacion.get("criterios_detalle"):
                try:
                    evaluacion["criterios_detalle"] = json.loads(
                        evaluacion["criterios_detalle"]
                    )
                except:
                    evaluacion["criterios_detalle"] = []

            if evaluacion.get("valores_criterios"):
                try:
                    evaluacion["valores_criterios"] = json.loads(
                        evaluacion["valores_criterios"]
                    )
                except:
                    evaluacion["valores_criterios"] = {}

            if evaluacion.get("decision_admin"):
                try:
                    evaluacion["decision_admin"] = json.loads(
                        evaluacion["decision_admin"]
                    )
                except:
                    pass

            # Agregar cliente en formato legacy para compatibilidad
            if evaluacion.get("nombre_cliente") and evaluacion.get("cedula"):
                evaluacion["cliente"] = (
                    f"{evaluacion['nombre_cliente']} - CC {evaluacion['cedula']}"
                )
            elif evaluacion.get("nombre_cliente"):
                evaluacion["cliente"] = evaluacion["nombre_cliente"]

            # Convertir visto_por_asesor a bool
            evaluacion["visto_por_asesor"] = bool(evaluacion.get("visto_por_asesor", 0))

            # =====================================================================
            # CORRECCIÓN 2025-12-18: Extraer campos de decision_admin a nivel superior
            # Esto permite compatibilidad con frontend que busca ev.monto_aprobado
            # =====================================================================
            if evaluacion.get("decision_admin") and isinstance(
                evaluacion["decision_admin"], dict
            ):
                da = evaluacion["decision_admin"]

                # Extraer monto_aprobado si no existe en columna directa
                if da.get("monto_aprobado") and not evaluacion.get("monto_aprobado"):
                    evaluacion["monto_aprobado"] = da["monto_aprobado"]

                # Extraer nivel_riesgo_ajustado (puede venir con diferentes nombres)
                if not evaluacion.get("nivel_riesgo_ajustado"):
                    evaluacion["nivel_riesgo_ajustado"] = (
                        da.get("nivel_riesgo_ajustado")
                        or da.get("nivel_riesgo_modificado")
                        or da.get("nivel_ajustado")
                    )

                # Extraer justificación
                if not evaluacion.get("justificacion_modificacion"):
                    evaluacion["justificacion_modificacion"] = (
                        da.get("justificacion_modificacion")
                        or da.get("justificacion")
                        or da.get("comentario")
                    )

                # Extraer tasas
                if da.get("tasas_aplicadas") and not evaluacion.get(
                    "tasas_nivel_riesgo"
                ):
                    evaluacion["tasas_nivel_riesgo"] = da["tasas_aplicadas"]

            evaluaciones.append(evaluacion)

        log_db_operation(
            "LEER_EVALUACIONES", f"✅ Cargadas {len(evaluaciones)} evaluaciones"
        )
        return evaluaciones

    except Exception as e:
        log_db_operation("LEER_EVALUACIONES", f"❌ Error: {e}", "ERROR")
        import traceback

        traceback.print_exc()
        return []


def guardar_evaluacion_db(evaluacion):
    """
    Guarda una nueva evaluación en SQLite.
    Si ya existe (mismo timestamp), la actualiza.
    """
    try:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "loansi.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Verificar si ya existe
        cursor.execute(
            "SELECT id FROM evaluaciones WHERE timestamp = ?",
            (evaluacion["timestamp"],),
        )
        existe = cursor.fetchone()

        # Serializar campos JSON
        resultado_json = json.dumps(evaluacion.get("resultado", {}), ensure_ascii=False)
        criterios_json = json.dumps(
            evaluacion.get("criterios_evaluados", []), ensure_ascii=False
        )
        criterios_detalle_json = json.dumps(
            evaluacion.get("criterios_detalle", []), ensure_ascii=False
        )
        valores_criterios_json = (
            json.dumps(evaluacion.get("valores_criterios", {}), ensure_ascii=False)
            if evaluacion.get("valores_criterios")
            else None
        )
        decision_admin_json = (
            json.dumps(evaluacion.get("decision_admin"), ensure_ascii=False)
            if evaluacion.get("decision_admin")
            else None
        )

        # Serializar tasas_nivel_riesgo si existe (NUEVO 2025-12-18)
        tasas_json = (
            json.dumps(evaluacion.get("tasas_nivel_riesgo"), ensure_ascii=False)
            if evaluacion.get("tasas_nivel_riesgo")
            else None
        )

        if existe:
            # Actualizar - ACTUALIZADO 2025-12-18: Incluye columnas de modificación del comité
            cursor.execute(
                """
                UPDATE evaluaciones SET
                    asesor = ?,
                    nombre_cliente = ?,
                    cedula = ?,
                    tipo_credito = ?,
                    linea_credito = ?,
                    estado_desembolso = ?,
                    origen = ?,
                    resultado = ?,
                    criterios_evaluados = ?,
                    criterios_detalle = ?,
                    valores_criterios = ?,
                    nivel_riesgo = ?,
                    monto_solicitado = ?,
                    estado_comite = ?,
                    decision_admin = ?,
                    visto_por_asesor = ?,
                    fecha_visto_asesor = ?,
                    fecha_envio_comite = ?,
                    puntaje_datacredito = ?,
                    datacredito = ?,
                    monto_aprobado = ?,
                    nivel_riesgo_ajustado = ?,
                    justificacion_modificacion = ?,
                    tasas_nivel_riesgo = ?,
                    fecha_modificacion = CURRENT_TIMESTAMP
                WHERE timestamp = ?
            """,
                (
                    evaluacion.get("asesor"),
                    evaluacion.get("nombre_cliente"),
                    evaluacion.get("cedula"),
                    evaluacion.get("tipo_credito"),
                    evaluacion.get("linea_credito"),
                    evaluacion.get("estado_desembolso", "Pendiente"),
                    evaluacion.get("origen", "Automático"),
                    resultado_json,
                    criterios_json,
                    criterios_detalle_json,
                    valores_criterios_json,
                    evaluacion.get("nivel_riesgo"),
                    evaluacion.get("monto_solicitado"),
                    evaluacion.get("estado_comite"),
                    decision_admin_json,
                    1 if evaluacion.get("visto_por_asesor") else 0,
                    evaluacion.get("fecha_visto_asesor"),
                    evaluacion.get("fecha_envio_comite"),
                    evaluacion.get("puntaje_datacredito"),
                    evaluacion.get("datacredito"),
                    evaluacion.get("monto_aprobado"),
                    evaluacion.get("nivel_riesgo_ajustado"),
                    evaluacion.get("justificacion_modificacion"),
                    tasas_json,
                    evaluacion["timestamp"],
                ),
            )
            log_db_operation(
                "ACTUALIZAR_EVALUACION", f"✅ Timestamp: {evaluacion['timestamp']}"
            )
        else:
            # Insertar - ACTUALIZADO 2025-12-18: Incluye columnas de modificación del comité
            cursor.execute(
                """
                INSERT INTO evaluaciones (
                    timestamp, asesor, nombre_cliente, cedula, tipo_credito,
                    linea_credito, estado_desembolso, origen, resultado,
                    criterios_evaluados, criterios_detalle, valores_criterios,
                    nivel_riesgo, monto_solicitado, estado_comite,
                    decision_admin, visto_por_asesor, fecha_visto_asesor,
                    fecha_envio_comite, puntaje_datacredito, datacredito,
                    monto_aprobado, nivel_riesgo_ajustado, justificacion_modificacion,
                    tasas_nivel_riesgo
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    evaluacion["timestamp"],
                    evaluacion.get("asesor"),
                    evaluacion.get("nombre_cliente"),
                    evaluacion.get("cedula"),
                    evaluacion.get("tipo_credito"),
                    evaluacion.get("linea_credito"),
                    evaluacion.get("estado_desembolso", "Pendiente"),
                    evaluacion.get("origen", "Automático"),
                    resultado_json,
                    criterios_json,
                    criterios_detalle_json,
                    valores_criterios_json,
                    evaluacion.get("nivel_riesgo"),
                    evaluacion.get("monto_solicitado"),
                    evaluacion.get("estado_comite"),
                    decision_admin_json,
                    1 if evaluacion.get("visto_por_asesor") else 0,
                    evaluacion.get("fecha_visto_asesor"),
                    evaluacion.get("fecha_envio_comite"),
                    evaluacion.get("puntaje_datacredito"),
                    evaluacion.get("datacredito"),
                    evaluacion.get("monto_aprobado"),
                    evaluacion.get("nivel_riesgo_ajustado"),
                    evaluacion.get("justificacion_modificacion"),
                    tasas_json,
                ),
            )
            log_db_operation(
                "GUARDAR_EVALUACION",
                f"✅ Nueva evaluación: {evaluacion.get('nombre_cliente')}",
            )

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        log_db_operation("GUARDAR_EVALUACION", f"❌ Error: {e}", "ERROR")
        import traceback

        traceback.print_exc()
        return False


def actualizar_evaluacion_db(evaluacion):
    """
    Actualiza una evaluación existente en SQLite.
    Alias de guardar_evaluacion_db para compatibilidad.
    """
    return guardar_evaluacion_db(evaluacion)


# ============================================
# FUNCIONES HELPER PARA ZONA HORARIA COLOMBIA
# ============================================
def obtener_hora_colombia():
    """
    Retorna datetime en zona horaria de Colombia (UTC-5)
    Usado para GUARDAR timestamps con timezone correcto
    """
    tz_colombia = timezone(timedelta(hours=-5))
    return datetime.now(tz_colombia)


def obtener_hora_colombia_naive():
    """
    Retorna datetime en hora de Colombia pero SIN timezone (naive)
    Usado para COMPARACIONES con timestamps viejos que no tienen timezone
    """
    tz_colombia = timezone(timedelta(hours=-5))
    return datetime.now(tz_colombia).replace(tzinfo=None)


def formatear_fecha_colombia(fecha_iso):
    """
    Convierte ISO string a formato legible en Colombia con AM/PM
    Ejemplo: "2025-11-27 5:30 PM"
    Usado en templates via filtro Jinja
    """
    try:
        # Parsear fecha ISO
        if isinstance(fecha_iso, str):
            # Intentar con timezone
            if "+" in fecha_iso or "Z" in fecha_iso:
                fecha = datetime.fromisoformat(fecha_iso.replace("Z", "+00:00"))
            else:
                # Timestamp viejo sin timezone
                fecha = datetime.fromisoformat(fecha_iso)
                # Asumir que es hora Colombia
                tz_colombia = timezone(timedelta(hours=-5))
                fecha = fecha.replace(tzinfo=tz_colombia)
        else:
            fecha = fecha_iso

        # Convertir a zona horaria Colombia si tiene timezone
        if fecha.tzinfo is not None:
            tz_colombia = timezone(timedelta(hours=-5))
            fecha = fecha.astimezone(tz_colombia)

        # Formatear: "2025-11-27 5:30 PM"
        return fecha.strftime("%Y-%m-%d %I:%M %p")
    except Exception as e:
        # Si falla, retornar string original
        return str(fecha_iso)


def parsear_timestamp_naive(timestamp_str):
    """
    Parsea timestamp ISO string y retorna datetime naive en hora Colombia
    Maneja timestamps con y sin timezone de forma segura
    Usado para comparaciones (cálculo de horas de espera)
    """
    try:
        # Parsear timestamp
        if isinstance(timestamp_str, str):
            if "+" in timestamp_str or "Z" in timestamp_str:
                # Tiene timezone
                fecha = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            else:
                # No tiene timezone (timestamp viejo)
                fecha = datetime.fromisoformat(timestamp_str)
        else:
            fecha = timestamp_str

        # Si tiene timezone, convertir a Colombia y quitar tzinfo
        if fecha.tzinfo is not None:
            tz_colombia = timezone(timedelta(hours=-5))
            fecha = fecha.astimezone(tz_colombia).replace(tzinfo=None)

        return fecha
    except Exception as e:
        # Si falla, retornar fecha actual
        return obtener_hora_colombia_naive()


# ============================================
# RATE LIMITING PARA LOGIN CON PERSISTENCIA
# ============================================
# Archivo para persistir intentos de login (evita pérdida al recargar app)
LOGIN_ATTEMPTS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "login_attempts.json"
)

# CONSTANTES DE CONVERSIÓN TEMPORAL
# Conversión exacta semanas/mes: 52 semanas ÷ 12 meses = 4.333333...
SEMANAS_POR_MES = 52.0 / 12.0  # 4.333333... (valor exacto)

# Configuración de rate limiting
MAX_LOGIN_ATTEMPTS = 3  # Máximo 3 intentos
LOCKOUT_DURATION = timedelta(minutes=15)  # Bloqueo por 15 minutos
ATTEMPT_WINDOW = timedelta(minutes=5)  # Ventana de 5 minutos para contar intentos
CLEANUP_THRESHOLD = 30  # Limpiar archivo si supera 30 registros


def cargar_login_attempts():
    """
    Carga intentos de login desde archivo JSON.
    Limpia automáticamente registros antiguos (> 15 minutos).

    Returns:
        dict: {ip_address: [timestamp_str1, timestamp_str2, ...]}
    """
    try:
        if os.path.exists(LOGIN_ATTEMPTS_FILE):
            with open(LOGIN_ATTEMPTS_FILE, "r") as f:
                attempts = json.load(f)

            # Limpiar registros antiguos automáticamente
            now = datetime.now()
            cleaned_attempts = {}

            for ip, timestamps in attempts.items():
                # Filtrar solo timestamps recientes (dentro de LOCKOUT_DURATION)
                recent_timestamps = [
                    ts
                    for ts in timestamps
                    if (now - datetime.fromisoformat(ts)) < LOCKOUT_DURATION
                ]
                if recent_timestamps:
                    cleaned_attempts[ip] = recent_timestamps

            # Si se limpiaron registros, guardar archivo limpio
            if len(cleaned_attempts) < len(attempts):
                guardar_login_attempts(cleaned_attempts)
                print(
                    f"🧹 Limpieza automática: {len(attempts) - len(cleaned_attempts)} registros antiguos eliminados"
                )

            return cleaned_attempts
        else:
            return {}
    except Exception as e:
        print(f"⚠️ Error cargando login_attempts: {e}")
        return {}


def guardar_login_attempts(attempts):
    """
    Guarda intentos de login en archivo JSON.

    Args:
        attempts: dict {ip_address: [timestamp_str1, ...]}
    """
    try:
        # Limitar tamaño del archivo (free tier tiene límites de disco)
        if len(attempts) > CLEANUP_THRESHOLD:
            # Ordenar por timestamp más reciente y mantener solo los últimos 50
            sorted_attempts = {}
            for ip, timestamps in attempts.items():
                sorted_attempts[ip] = sorted(timestamps, reverse=True)[:10]
            attempts = sorted_attempts

        with open(LOGIN_ATTEMPTS_FILE, "w") as f:
            json.dump(attempts, f, indent=2)
    except Exception as e:
        print(f"⚠️ Error guardando login_attempts: {e}")


def check_rate_limit(ip_address):
    """
    Verifica si una IP está bloqueada por exceso de intentos de login.

    Returns:
        tuple: (is_blocked: bool, remaining_attempts: int, lockout_until: datetime or None)
    """
    now = datetime.now()
    attempts = cargar_login_attempts()

    if ip_address not in attempts:
        return (False, MAX_LOGIN_ATTEMPTS, None)

    # Convertir timestamps de string a datetime
    timestamps = [datetime.fromisoformat(ts) for ts in attempts[ip_address]]

    if not timestamps:
        return (False, MAX_LOGIN_ATTEMPTS, None)

    # loqueo basado en PRIMER intento, no en ventana móvil
    # Obtener el PRIMER intento fallido (el más antiguo)
    primer_intento = min(timestamps)

    # Calcular cuándo expira el bloqueo (15 minutos desde PRIMER intento)
    lockout_expiry = primer_intento + LOCKOUT_DURATION

    # Contar TODOS los intentos (no solo los de la ventana de 5 min)
    total_attempts = len(timestamps)

    # Si hay 5+ intentos Y aún no expira el bloqueo → BLOQUEADO
    if total_attempts >= MAX_LOGIN_ATTEMPTS:
        if now < lockout_expiry:
            # Aún está bloqueado
            minutes_remaining = int((lockout_expiry - now).total_seconds() / 60)
            logger.warning(
                f"🔒 IP {ip_address} bloqueada: {total_attempts} intentos, {minutes_remaining} min restantes"
            )
            return (True, 0, lockout_expiry)
        else:
            # Bloqueo expiró (pasaron 15 min desde primer intento) → limpiar todo
            clear_attempts(ip_address)
            logger.info(f"✅ Bloqueo expirado para IP {ip_address}, intentos limpiados")
            return (False, MAX_LOGIN_ATTEMPTS, None)

    # Si hay < 5 intentos, verificar si el primer intento ya expiró (limpieza automática)
    if now >= primer_intento + LOCKOUT_DURATION:
        # Han pasado 15+ minutos desde el primer intento → limpiar
        clear_attempts(ip_address)
        return (False, MAX_LOGIN_ATTEMPTS, None)

    # Aún no bloqueado, calcular intentos restantes
    remaining = MAX_LOGIN_ATTEMPTS - total_attempts
    return (False, remaining, None)


def es_ruta_publica(path=None):
    """
    Determina si una ruta es pública (no requiere autenticación).

    Solo son públicas:
    - / (simulador público)
    - /calcular (POST - resultado público)
    - /api/lineas-config (GET - API pública de configuración)

    Args:
        path: Ruta a verificar. Si es None, usa request.path

    Returns:
        bool: True si es ruta pública, False si es privada
    """
    if path is None:
        path = request.path

    # Rutas públicas explícitas (sin autenticación)
    rutas_publicas = [
        "/",  # Simulador público
        "/calcular",  # Resultado público (POST)
        "/api/lineas-config",  # API pública de config
    ]

    # Verificar coincidencia exacta
    return path in rutas_publicas


def record_failed_attempt(ip_address):
    """Registra un intento de login fallido con persistencia."""
    attempts = cargar_login_attempts()

    if ip_address not in attempts:
        attempts[ip_address] = []

    attempts[ip_address].append(datetime.now().isoformat())
    guardar_login_attempts(attempts)

    print(
        f"🔒 Intento fallido registrado para IP: {ip_address} (Total: {len(attempts[ip_address])})"
    )


def clear_attempts(ip_address):
    """Limpia los intentos de login de una IP específica."""
    attempts = cargar_login_attempts()

    if ip_address in attempts:
        del attempts[ip_address]
        guardar_login_attempts(attempts)
        print(f"✅ Intentos limpiados para IP: {ip_address}")


def cleanup_old_attempts():
    """
    Limpieza manual de registros antiguos (opcional, se llama automáticamente).
    Útil para ejecutar periódicamente si el archivo crece mucho.
    """
    attempts = cargar_login_attempts()
    now = datetime.now()
    cleaned = {}

    for ip, timestamps in attempts.items():
        recent = [
            ts
            for ts in timestamps
            if (now - datetime.fromisoformat(ts)) < LOCKOUT_DURATION
        ]
        if recent:
            cleaned[ip] = recent

    guardar_login_attempts(cleaned)
    print(f"🧹 Limpieza completa: {len(attempts) - len(cleaned)} IPs eliminadas")


# ============================================
# SISTEMA UNIFICADO DE BACKUP CON ROTACIÓN
# ============================================
def crear_backup_con_rotacion(archivo_origen, prefijo="backup", max_backups=7):
    """
    Crea backup automático con rotación.
    Mantiene solo los últimos max_backups archivos.
    """
    try:
        if not os.path.exists(archivo_origen):
            return True  # No hay nada que respaldar

        # Crear carpeta de backups
        backup_dir = os.path.join(os.path.dirname(archivo_origen), "backups")
        os.makedirs(backup_dir, exist_ok=True)

        # Crear backup con timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre_archivo = os.path.basename(archivo_origen)
        backup_file = os.path.join(
            backup_dir, f"{prefijo}_{timestamp}_{nombre_archivo}"
        )
        shutil.copy(archivo_origen, backup_file)

        # Rotación: eliminar backups antiguos
        patron = f"{prefijo}_*_{nombre_archivo}"
        backups = sorted(
            [
                f
                for f in os.listdir(backup_dir)
                if f.startswith(prefijo) and f.endswith(nombre_archivo)
            ]
        )

        while len(backups) > max_backups:
            archivo_a_eliminar = os.path.join(backup_dir, backups[0])
            os.remove(archivo_a_eliminar)
            backups.pop(0)

        return True
    except Exception as e:
        print(f"Error en backup: {str(e)}")
        return True  # No bloquear guardado por error de backup


def recuperar_desde_backup_mas_reciente():
    """
    Intenta recuperar la configuración desde el backup más reciente VÁLIDO.

    Returns:
        dict: Config recuperado si tiene éxito, None si falla
    """
    try:
        backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")

        if not os.path.exists(backup_dir):
            print("⚠️ Directorio de backups no existe")
            return None

        # Buscar todos los backups de config (ordenados por fecha, más reciente primero)
        backups = sorted(
            [
                f
                for f in os.listdir(backup_dir)
                if f.startswith("config_") and f.endswith("config.json")
            ],
            reverse=True,
        )

        if not backups:
            print("⚠️ No hay backups disponibles")
            return None

        print(
            f"🔍 Encontrados {len(backups)} backups, probando desde el más reciente..."
        )

        # Intentar cargar backups en orden (más reciente primero)
        for backup_file in backups:
            backup_path = os.path.join(backup_dir, backup_file)
            try:
                print(f"   Probando: {backup_file}")

                with open(backup_path, "r", encoding="utf-8") as f:
                    config = json.load(f)

                # Validar que el backup sea válido
                if not all(
                    k in config
                    for k in ["LINEAS_CREDITO", "COSTOS_ASOCIADOS", "USUARIOS"]
                ):
                    print(f"      ✗ Backup inválido (faltan claves)")
                    continue

                if not config["LINEAS_CREDITO"] or not config["USUARIOS"]:
                    print(f"      ✗ Backup inválido (vacío)")
                    continue

                # ✅ Backup válido encontrado
                print(f"      ✓ Backup válido")
                print(f"        Líneas: {len(config['LINEAS_CREDITO'])}")
                print(f"        Usuarios: {len(config['USUARIOS'])}")

                # Restaurar el backup al archivo principal
                import shutil

                shutil.copy(backup_path, CONFIG_FILE)
                print(f"✅ Config.json restaurado desde: {backup_file}")

                return config

            except json.JSONDecodeError:
                print(f"      ✗ Backup con error JSON")
                continue
            except Exception as e:
                print(f"      ✗ Error al leer backup: {str(e)}")
                continue

        print("⚠️ Ningún backup válido encontrado")
        return None

    except Exception as e:
        print(f"❌ Error al recuperar backup: {str(e)}")
        return None


app = Flask(__name__, static_folder="static")
app.config["WTF_CSRF_ENABLED"] = True
csrf = CSRFProtect(app)
app.secret_key = "clave_segura_loansi"

# Sistema de contraseña más seguro usando hash
SALT = "loansi_salt_security"

# CONFIGURACIÓN DE SEGURIDAD DE SESIONES
app.secret_key = "clave_segura_loansi"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=1)  # 1 hora por seguridad
app.config["SESSION_COOKIE_SECURE"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["WTF_CSRF_TIME_LIMIT"] = None  # Sin límite - evita expiración prematura
app.config["WTF_CSRF_SSL_STRICT"] = False  # Para PythonAnywhere

# ============================================
# INICIALIZAR SISTEMA DE PERMISOS GRANULARES
# ============================================
try:
    inicializar_permisos(app)
    print("✅ Sistema de permisos granulares inicializado")
except Exception as e:
    print(f"⚠️ Error inicializando permisos (las tablas pueden no existir aún): {e}")
    print("   Ejecuta primero: python migracion_permisos.py")


# Context processor para inyectar resumen_navbar en todas las vistas
@app.context_processor
def inject_navbar_stats():
    """
    Inyecta resumen_navbar en todas las plantillas automáticamente.
    Solo se ejecuta si el usuario está autenticado.
    """
    if session.get("autorizado") and session.get("username"):
        try:
            resumen = obtener_resumen_navbar(
                session.get("rol", "asesor"), session.get("username")
            )
            return {"resumen_navbar": resumen}
        except Exception as e:
            print(f"⚠️ Error al obtener resumen navbar: {e}")
            return {"resumen_navbar": {"items": []}}
    return {"resumen_navbar": {"items": []}}


@app.context_processor
def inject_permissions():
    """Inyectar funciones de permisos en todos los templates."""
    return {
        "tiene_permiso": tiene_permiso,
        "tiene_alguno_de": tiene_alguno_de,
    }


# DECORATOR PARA PREVENIR CACHÉ Y VALIDAR SESIÓN ACTIVA
def no_cache_and_check_session(f):
    """
    Decorator que previene caché del navegador y valida sesión activa.
    Aplica headers HTTP que fuerzan al navegador a NO cachear la página.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Validar que la sesión siga activa
        if not session.get("autorizado"):
            session.clear()
            # Solo mostrar flash si venimos de una ruta privada (no en público)
            if request.referrer and (
                "admin" in request.referrer
                or "simulador" in request.referrer
                or "scoring" in request.referrer
            ):
                flash(
                    "Tu sesión ha expirado. Por favor, inicia sesión nuevamente.",
                    "warning",
                )
            return redirect(url_for("login"))

        # Validar tiempo de sesión con última actividad
        if session.permanent:
            now = datetime.now()
            last_activity = session.get("last_activity")

            # Si existe última actividad, verificar si ha expirado
            if last_activity:
                last_activity_time = datetime.fromisoformat(last_activity)
                # Si pasaron más de 1 hora (3600 segundos), expiró
                if (now - last_activity_time).total_seconds() > 3600:  # 3600 = 1 hora
                    session.clear()
                    flash(
                        "Tu sesión ha expirado por inactividad. Por favor, inicia sesión nuevamente.",
                        "warning",
                    )
                    return redirect(url_for("login"))

            # Actualizar última actividad
            session["last_activity"] = now.isoformat()

        # Ejecutar la función original
        response = make_response(f(*args, **kwargs))

        # Headers para prevenir caché (crítico para botón "atrás")
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "-1"

        return response

    return decorated_function


# Ruta ABSOLUTA al archivo JSON donde se guardará la configuración
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# Ruta ABSOLUTA al archivo JSON donde se guardaba la configuración de seguros
# DEPRECATED 2025-12-19: Solo se usa para migración inicial a SQLite
SEGUROS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seguros.json")

# Ruta ABSOLUTA al archivo JSON donde se guardará la configuración de scoring
SCORING_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scoring.json")

# Ruta ABSOLUTA al archivo JSON de evaluaciones para auditoría
# EVALUACIONES_LOG - DEPRECATED: Ahora usa SQLite
# EVALUACIONES_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'evaluaciones_log.json')

# Ruta ABSOLUTA al archivo JSON de historial de simulaciones
# SIMULACIONES_LOG - DEPRECATED: Ahora usa SQLite
# SIMULACIONES_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'simulaciones_log.json')

# ============================================================================
# FUNCIONES AUXILIARES DE LECTURA/ESCRITURA EVALUACIONES
# ============================================================================


def leer_evaluaciones():
    """
    Lee evaluaciones desde SQLite (reemplaza lectura de JSON).
    MIGRADO A SQLite - Mantiene misma API para compatibilidad.
    Usado por: detalle_evaluacion(), mis_casos_comite(), comite_credito()

    CORREGIDO 2025-12-18: Ahora usa leer_evaluaciones_db() local que tiene
    procesamiento completo (deserialización JSON, campos legacy, etc.)
    """
    try:
        return leer_evaluaciones_db()
    except Exception as e:
        log_db_operation("LEER_EVALUACIONES", f"ERROR: {e}", level="ERROR")
        logger.error(f"Error al leer evaluaciones: {e}")
        return []


def guardar_evaluaciones(evaluaciones):
    """
    Guarda evaluaciones en SQLite (reemplaza guardado en JSON).
    MIGRADO A SQLite - Wrapper para mantener compatibilidad.

    NOTA: Esta función recibe lista completa pero SQLite guarda una por una.
    Se recomienda usar guardar_evaluacion_db() directamente para nuevas evaluaciones.
    """
    try:
        log_db_operation(
            "GUARDAR_EVALUACIONES", f"Guardando {len(evaluaciones)} evaluaciones"
        )

        # Por compatibilidad, guardar cada evaluación
        for ev in evaluaciones:
            guardar_evaluacion_db(ev)

        log_db_operation("GUARDAR_EVALUACIONES", "✅ Guardadas exitosamente")
        return True
    except Exception as e:
        log_db_operation("GUARDAR_EVALUACIONES", f"ERROR: {e}", level="ERROR")
        logger.error(f"Error al guardar evaluaciones: {e}")
        return False


def leer_simulaciones():
    """
    Lee simulaciones desde SQLite (reemplaza lectura de JSON).
    MIGRADO A SQLite - Mantiene misma API para compatibilidad.
    """
    try:
        log_db_operation("LEER_SIMULACIONES", "Cargando desde SQLite")
        simulaciones = cargar_simulaciones_db()
        log_db_operation(
            "LEER_SIMULACIONES", f"✅ Cargadas {len(simulaciones)} simulaciones"
        )
        return simulaciones
    except Exception as e:
        log_db_operation("LEER_SIMULACIONES", f"ERROR: {e}", level="ERROR")
        logger.error(f"Error al leer simulaciones: {e}")
        return []


def guardar_simulacion(datos_simulacion):
    """
    Guarda una simulación individual en el historial.
    MIGRADO A SQLite 2025-12-18: Ya no usa SIMULACIONES_LOG JSON
    """
    try:
        # MIGRADO A SQLite - usar guardar_simulacion_db()
        resultado = guardar_simulacion_db(datos_simulacion)

        if resultado:
            print(
                f"✅ Simulación guardada en SQLite: {datos_simulacion.get('cliente')} - ${datos_simulacion.get('monto')}"
            )
            return True
        else:
            print(f"⚠️ Error al guardar simulación en SQLite")
            return False
    except Exception as e:
        print(f"❌ Error guardando simulación: {e}")
        import traceback

        traceback.print_exc()
        return False


def obtener_simulaciones_asesor(username):
    """
    Obtiene todas las simulaciones de un asesor específico.
    Ordenadas de más reciente a más antigua.
    """
    try:
        simulaciones = leer_simulaciones()

        # Filtrar por asesor
        simulaciones_asesor = [s for s in simulaciones if s.get("asesor") == username]

        # Ordenar por timestamp (más reciente primero)
        simulaciones_asesor.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        return simulaciones_asesor
    except Exception as e:
        print(f"❌ Error obteniendo simulaciones del asesor {username}: {e}")
        return []


def obtener_simulaciones_cliente(cedula):
    """
    Obtiene todas las simulaciones de un cliente específico (por cédula).
    Ordenadas de más reciente a más antigua.
    """
    try:
        simulaciones = leer_simulaciones()

        # Filtrar por cédula
        simulaciones_cliente = [s for s in simulaciones if s.get("cedula") == cedula]

        # Ordenar por timestamp (más reciente primero)
        simulaciones_cliente.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        return simulaciones_cliente
    except Exception as e:
        print(f"❌ Error obteniendo simulaciones del cliente {cedula}: {e}")
        return []


#  SISTEMA DE CACHÉ COMPLETO
config_cache = None
last_config_load_time = 0
CACHE_DURATION = 300  # 5 minutos en segundos

# Variables globales de caché para scoring (SQLite)
scoring_cache = None
last_scoring_load_time = 0

LINEAS_CREDITO_CACHE = None
COSTOS_ASOCIADOS_CACHE = None
USUARIOS_CACHE = None

SEGUROS_CONFIG_CACHE = None
last_seguros_load_time = 0

SCORING_CONFIG_CACHE = None
last_scoring_load_time = 0


# Cargar configuración de seguros CON CACHÉ
# MIGRADO A SQLite 2025-12-19: Ya no usa seguros.json, ahora usa config general en SQLite
def cargar_configuracion_seguros():
    """
    Carga configuración de seguros desde SQLite (dentro de config general).

    MIGRADO A SQLite 2025-12-19: Los seguros ahora se guardan como parte de
    la configuración general en la clave 'SEGUROS'.
    """
    global SEGUROS_CONFIG_CACHE, last_seguros_load_time

    try:
        current_time = time.time()

        # Usar caché si es válido
        if (
            SEGUROS_CONFIG_CACHE
            and (current_time - last_seguros_load_time) < CACHE_DURATION
        ):
            return SEGUROS_CONFIG_CACHE

        # MIGRADO A SQLite - Cargar desde config general
        config = cargar_config_db()

        if config and "SEGUROS" in config:
            seguros_config = config["SEGUROS"]
        else:
            # Si no existe en SQLite, intentar migrar desde JSON
            seguros_config = _migrar_seguros_json_a_sqlite()

        # Actualizar caché
        SEGUROS_CONFIG_CACHE = seguros_config
        last_seguros_load_time = current_time

        #  VALIDAR RANGOS DE SEGURO
        advertencias = validar_rangos_seguros(
            seguros_config.get("SEGURO_VIDA", []),
            edad_min_permitida=18,
            edad_max_permitida=84,
        )

        if advertencias:
            print("=" * 60)
            print("⚠️ ADVERTENCIAS EN RANGOS DE SEGURO:")
            for adv in advertencias:
                print(f"  {adv}")
            print("=" * 60)
        else:
            print("✅ Validación de rangos de seguros: OK (sin gaps ni overlaps)")

        return seguros_config

    except Exception as e:
        print(f"Error al cargar configuración de seguros: {str(e)}")
        import traceback

        traceback.print_exc()
        return {
            "SEGURO_VIDA": [
                {
                    "id": 1,
                    "edad_min": 18,
                    "edad_max": 30,
                    "costo": 1200,
                    "descripcion": "18 a 30 años",
                },
                {
                    "id": 2,
                    "edad_min": 31,
                    "edad_max": 50,
                    "costo": 1400,
                    "descripcion": "31 a 50 años",
                },
                {
                    "id": 3,
                    "edad_min": 51,
                    "edad_max": 69,
                    "costo": 2500,
                    "descripcion": "51 a 69 años",
                },
                {
                    "id": 4,
                    "edad_min": 70,
                    "edad_max": 84,
                    "costo": 6000,
                    "descripcion": "70 a 84 años",
                },
            ]
        }


def _migrar_seguros_json_a_sqlite():
    """
    Función auxiliar para migrar seguros.json a SQLite (una sola vez).
    Se ejecuta automáticamente si no existe 'SEGUROS' en la config de SQLite.

    CORREGIDO 2025-12-19: Verifica directamente en configuracion_sistema
    """
    # PRIMERO verificar si ya existe en SQLite (verificación directa)
    try:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "loansi.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT valor FROM configuracion_sistema WHERE clave = 'SEGUROS'"
        )
        row = cursor.fetchone()
        conn.close()

        if row:
            seguros_existente = json.loads(row[0])
            # Verificar que tiene datos válidos (no solo estructura vacía)
            if seguros_existente:
                seguro_vida = seguros_existente.get("SEGURO_VIDA", [])
                if isinstance(seguro_vida, list) and len(seguro_vida) > 0:
                    # Ya existe en SQLite con datos válidos, retornar sin migrar
                    print("✅ Seguros ya existen en SQLite, no se migra")
                    return seguros_existente
    except Exception as e:
        print(f"⚠️ Error verificando seguros existentes: {e}")

    print("🔄 Migrando seguros.json a SQLite (primera vez)...")

    seguros_config = None

    # Intentar cargar desde JSON existente (si existe)
    if os.path.exists(SEGUROS_FILE):
        try:
            with open(SEGUROS_FILE, "r") as f:
                seguros_config = json.load(f)
            print(f"✅ Leído seguros.json existente")
        except Exception as e:
            print(f"⚠️ seguros.json no disponible, usando valores predeterminados")

    # Si no hay JSON o falló, usar configuración predeterminada
    if not seguros_config:
        seguros_config = {
            "SEGURO_VIDA": [
                {
                    "id": 1,
                    "edad_min": 18,
                    "edad_max": 30,
                    "costo": 1200,
                    "descripcion": "18 a 30 años",
                },
                {
                    "id": 2,
                    "edad_min": 31,
                    "edad_max": 50,
                    "costo": 1400,
                    "descripcion": "31 a 50 años",
                },
                {
                    "id": 3,
                    "edad_min": 51,
                    "edad_max": 69,
                    "costo": 2500,
                    "descripcion": "51 a 69 años",
                },
                {
                    "id": 4,
                    "edad_min": 70,
                    "edad_max": 84,
                    "costo": 6000,
                    "descripcion": "70 a 84 años",
                },
            ]
        }
        print("ℹ️ Usando configuración de seguros predeterminada")

    # Convertir formato viejo (dict) a nuevo (lista) si es necesario
    seguro_vida = seguros_config.get("SEGURO_VIDA", {})
    if isinstance(seguro_vida, dict) and not isinstance(seguro_vida, list):
        # Formato viejo: {"hasta_45": 759, "hasta_59": 982, "mas_60": 1014}
        seguros_config["SEGURO_VIDA"] = [
            {
                "id": 1,
                "edad_min": 18,
                "edad_max": 45,
                "costo": seguro_vida.get("hasta_45", 900),
                "descripcion": "Hasta 45 años",
            },
            {
                "id": 2,
                "edad_min": 46,
                "edad_max": 59,
                "costo": seguro_vida.get("hasta_59", 1100),
                "descripcion": "46 a 59 años",
            },
            {
                "id": 3,
                "edad_min": 60,
                "edad_max": 84,
                "costo": seguro_vida.get("mas_60", 1250),
                "descripcion": "60 años o más",
            },
        ]
        print("🔄 Convertido formato viejo de seguros a formato nuevo")

    # Guardar en SQLite
    try:
        config = cargar_config_db() or {}
        config["SEGUROS"] = seguros_config
        guardar_config_db(config)
        print("✅ Seguros migrados a SQLite exitosamente")
    except Exception as e:
        print(f"❌ Error al migrar seguros a SQLite: {e}")

    return seguros_config


#  Guardar configuración de seguros CON INVALIDACIÓN DE CACHÉ
# MIGRADO A SQLite 2025-12-19: Ya no usa seguros.json
def guardar_configuracion_seguros(seguros_config):
    """
    Guarda configuración de seguros en SQLite (dentro de config general).

    MIGRADO A SQLite 2025-12-19: Los seguros ahora se guardan como parte de
    la configuración general en la clave 'SEGUROS'.
    """
    global SEGUROS_CONFIG_CACHE, last_seguros_load_time
    try:
        # MIGRADO A SQLite - Guardar en config general
        config = cargar_config_db() or {}
        config["SEGUROS"] = seguros_config
        guardar_config_db(config)

        # Invalidar caché para forzar recarga
        SEGUROS_CONFIG_CACHE = None
        last_seguros_load_time = 0

        print("✅ Configuración de seguros guardada en SQLite")
        return True
    except Exception as e:
        print(f"❌ Error al guardar configuración de seguros: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


#  Cargar configuración de scoring CON CACHÉ
# 🔍 VALIDACIÓN DE RANGOS DE CRITERIOS DE SCORING
def validar_rangos_criterio(criterio_id, criterio_config):
    """
    Valida que los rangos de un criterio no tengan gaps y cubran todo el espectro.
    Retorna lista de advertencias (vacía si todo OK).
    """
    advertencias = []
    rangos = criterio_config.get("rangos", [])

    if not rangos:
        return advertencias

    # Ordenar rangos por min
    rangos_ordenados = sorted(rangos, key=lambda r: float(r.get("min", 0)))

    # Validar que no haya gaps entre rangos consecutivos
    for i in range(len(rangos_ordenados) - 1):
        rango_actual = rangos_ordenados[i]
        rango_siguiente = rangos_ordenados[i + 1]

        max_actual = float(rango_actual.get("max", 0))
        min_siguiente = float(rango_siguiente.get("min", 0))

        # Permitir gap de 0.1 por decimales (ej: 30.0 a 30.1)
        if min_siguiente - max_actual > 0.1:
            advertencias.append(
                f"⚠️ Gap detectado en '{criterio_config.get('nombre', criterio_id)}': "
                f"rango termina en {max_actual} pero siguiente empieza en {min_siguiente}"
            )

    # Validar que rangos cubran desde min_campo hasta max_campo
    min_campo = criterio_config.get("min", 0)
    max_campo = criterio_config.get("max", 999999)

    primer_rango_min = float(rangos_ordenados[0].get("min", 0))
    ultimo_rango_max = float(rangos_ordenados[-1].get("max", 0))

    if primer_rango_min > min_campo + 0.1:
        advertencias.append(
            f"⚠️ '{criterio_config.get('nombre', criterio_id)}': "
            f"rangos empiezan en {primer_rango_min} pero campo min es {min_campo}"
        )

    if ultimo_rango_max < max_campo - 0.1 and max_campo != 999999:
        advertencias.append(
            f"⚠️ '{criterio_config.get('nombre', criterio_id)}': "
            f"rangos terminan en {ultimo_rango_max} pero campo max es {max_campo}"
        )

    return advertencias


def validar_rangos_seguros(
    rangos_seguros, edad_min_permitida=18, edad_max_permitida=84
):
    """
    Valida que los rangos de seguro no tengan gaps ni solapamientos.

    Detecta:
    - Gaps (huecos): Edades sin cobertura
    - Overlaps (solapamientos): Edades cubiertas por múltiples rangos
    - Cobertura incompleta: No cubren edad mínima o máxima permitida

    Args:
        rangos_seguros: Lista de rangos desde SQLite (config['SEGUROS']['SEGURO_VIDA'])
        edad_min_permitida: Edad mínima que debe tener cobertura (default: 18)
        edad_max_permitida: Edad máxima que debe tener cobertura (default: 84)

    Returns:
        list: Lista de advertencias (vacía si todo está OK)
    """
    advertencias = []

    if not rangos_seguros or len(rangos_seguros) == 0:
        return ["⚠️ No hay rangos de seguro configurados"]

    # Ordenar por edad_min
    rangos_ordenados = sorted(rangos_seguros, key=lambda x: x.get("edad_min", 0))

    # Verificar que el primer rango empiece en edad_min_permitida o antes
    if rangos_ordenados[0]["edad_min"] > edad_min_permitida:
        advertencias.append(
            f"⚠️ GAP: No hay cobertura desde edad {edad_min_permitida} "
            f"hasta {rangos_ordenados[0]['edad_min'] - 1}"
        )

    # Verificar gaps y solapamientos entre rangos consecutivos
    for i in range(len(rangos_ordenados) - 1):
        rango_actual = rangos_ordenados[i]
        rango_siguiente = rangos_ordenados[i + 1]

        # Detectar gap (hueco)
        if rango_actual["edad_max"] + 1 < rango_siguiente["edad_min"]:
            advertencias.append(
                f"⚠️ GAP: Falta cobertura entre edad {rango_actual['edad_max'] + 1} "
                f"y {rango_siguiente['edad_min'] - 1}"
            )

        # Detectar overlap (solapamiento)
        if rango_actual["edad_max"] >= rango_siguiente["edad_min"]:
            advertencias.append(
                f"⚠️ OVERLAP: Rangos se solapan en edad {rango_siguiente['edad_min']} "
                f"(Rango {i+1}: {rango_actual['edad_min']}-{rango_actual['edad_max']}, "
                f"Rango {i+2}: {rango_siguiente['edad_min']}-{rango_siguiente['edad_max']})"
            )

    # Verificar que el último rango cubra hasta edad_max_permitida o después
    if rangos_ordenados[-1]["edad_max"] < edad_max_permitida:
        advertencias.append(
            f"⚠️ GAP: No hay cobertura desde edad {rangos_ordenados[-1]['edad_max'] + 1} "
            f"hasta {edad_max_permitida}"
        )

    return advertencias


def agrupar_criterios_por_seccion(criterios, secciones):
    """
    Agrupa criterios por sección para facilitar renderizado en templates.

    Args:
        criterios: dict de criterios {id: {nombre, peso, seccion, ...}}
        secciones: list de secciones [{id, nombre, color, icono, ...}]

    Returns:
        list de dicts: [{seccion: {...}, criterios: [{id, ...}, ...]}, ...]
    """
    resultado = []

    for seccion in secciones:
        seccion_id = seccion.get("id", "otros")
        criterios_de_seccion = []

        for criterio_id, criterio in criterios.items():
            criterio_seccion = criterio.get("seccion", "otros")
            if criterio_seccion == seccion_id:
                criterios_de_seccion.append({"id": criterio_id, **criterio})

        # Ordenar por campo 'orden'
        criterios_de_seccion.sort(key=lambda x: x.get("orden", 999))

        if criterios_de_seccion:  # Solo incluir secciones con criterios
            resultado.append({"seccion": seccion, "criterios": criterios_de_seccion})

    return resultado


def cargar_configuracion_scoring(linea_credito=None):
    """
    Carga configuración de scoring desde SQLite.

    ACTUALIZADO: Ahora soporta configuración por línea de crédito.

    Args:
        linea_credito: Nombre de la línea (opcional). Si se especifica,
                      intenta cargar configuración específica de la línea.

    Returns:
        dict: Configuración de scoring
    """
    global scoring_cache, last_scoring_load_time

    # Si se especifica línea, intentar cargar configuración específica
    if linea_credito:
        try:
            # Verificar si existen tablas de scoring multi-línea
            if verificar_tablas_scoring_linea():
                config_linea = cargar_scoring_por_linea(linea_credito)
                if config_linea:
                    logger.info(
                        f"✅ Usando configuración de scoring para: {linea_credito}"
                    )
                    return config_linea
                else:
                    logger.info(
                        f"⚠️ Línea {linea_credito} sin config específica, usando global"
                    )
        except Exception as e:
            logger.warning(f"Error cargando scoring por línea: {e}, usando global")

    # Fallback: configuración global (código existente)
    current_time = time.time()

    try:
        # Verificar caché (5 minutos)
        if scoring_cache and (current_time - last_scoring_load_time) < CACHE_DURATION:
            return scoring_cache

        # Cargar desde SQLite
        scoring = cargar_scoring_db()

        # Actualizar caché
        scoring_cache = scoring
        last_scoring_load_time = current_time

        return scoring

    except Exception as e:
        logger.error(f"❌ Error al cargar scoring desde SQLite: {e}")

        # Usar caché si existe
        if scoring_cache:
            return scoring_cache

        # Configuración predeterminada mínima
        return {"configuracion_por_linea": {}, "criterios": {}}


#  Guardar configuración de scoring CON INVALIDACIÓN DE CACHÉ
def guardar_configuracion_scoring(scoring_config):
    global scoring_cache, last_scoring_load_time, SCORING_CONFIG_CACHE
    """
    Guarda configuración de scoring en SQLite.

    MIGRADO A SQLite: Ya no guarda en scoring.json.
    CORREGIDO 2025-12-20: Ahora también invalida SCORING_CONFIG_CACHE
    """
    global scoring_cache, last_scoring_load_time, SCORING_CONFIG_CACHE

    try:
        # Guardar en SQLite
        guardar_scoring_db(scoring_config)

        # Actualizar AMBOS cachés (CORREGIDO 2025-12-20)
        scoring_cache = scoring_config
        SCORING_CONFIG_CACHE = scoring_config  # LÍNEA CRÍTICA AGREGADA
        last_scoring_load_time = time.time()

        print(f"✅ Scoring guardado y cachés actualizados")

        return True

    except Exception as e:
        logger.error(f"❌ Error al guardar scoring en SQLite: {e}")
        return False


def parse_currency_value(value_str):
    """
    NORMALIZACIÓN ROBUSTA DE VALORES MONETARIOS
    Maneja: "1.000.000", "1000000", "1,000,000", "$1.000.000"
    Retorna: int o float limpio

    Args:
        value_str: String con el valor monetario (puede tener separadores)

    Returns:
        float: Valor limpio como número

    Examples:
        >>> parse_currency_value("1.000.000")
        1000000.0
        >>> parse_currency_value("$2,500.50")
        2500.5
    """
    try:
        if not value_str or (isinstance(value_str, str) and value_str.strip() == ""):
            return 0.0

        # Convertir a string si no lo es
        value_str = str(value_str)

        # Eliminar símbolos de moneda y espacios
        cleaned = value_str.replace("$", "").replace(" ", "").strip()

        # Eliminar TODOS los separadores de miles (puntos y comas)
        cleaned = cleaned.replace(".", "").replace(",", "")

        # Convertir a float
        result = float(cleaned)

        return result if result >= 0 else 0.0

    except (ValueError, TypeError, AttributeError) as e:
        print(f"⚠️ Error parseando valor monetario '{value_str}': {str(e)}")
        return 0.0


# ============================================
# REGISTRO DE EVALUACIONES PARA AUDITORÍA
# ============================================
def registrar_evaluacion_scoring(
    username,
    cliente_info,
    scoring_result,
    valores_criterios=None,
    resultados_detalle=None,
    form_values=None,
):
    """
    Registra evaluaciones de scoring en SQLite para auditoría.
    MIGRADO A SQLite - Ya no usa evaluaciones_log.json

    Guarda información completa para el modal [VER DETALLE]:
    - Cédula separada del nombre
    - Puntaje DataCrédito
    - Criterios evaluados con detalle (puntaje y peso)
    - Simulación del crédito (si existe)
    """
    try:
        # Extraer nombre y cédula del campo cliente_info
        # Formato esperado: "nombre - cc cedula" o "nombre - CC cedula"
        nombre_cliente = cliente_info
        cedula = None

        if " - cc " in cliente_info.lower():
            partes = cliente_info.split(" - ")
            if len(partes) >= 2:
                nombre_cliente = partes[0].strip()
                cedula_parte = partes[1].strip()
                # Extraer solo números de la cédula
                cedula = "".join(filter(str.isdigit, cedula_parte))

        # Construir registro base
        registro = {
            "timestamp": scoring_result.get(
                "timestamp", obtener_hora_colombia().isoformat()
            ),
            "asesor": username,
            "cliente": cliente_info,  # Mantener formato completo para compatibilidad
            "nombre_cliente": nombre_cliente,  # Nombre separado
            "cedula": cedula,  # Cédula separada
            "tipo_credito": scoring_result.get("tipo_credito", "No especificado"),
            "linea_credito": scoring_result.get(
                "tipo_credito", "No especificado"
            ),  # Alias para modal
            "estado_desembolso": "Pendiente",
            "origen": scoring_result.get("origen", "Automático"),
            "estado_comite": scoring_result.get("estado_comite", None),
            "nivel_riesgo": scoring_result[
                "level"
            ],  # Nivel en raíz para aprobar_comite()
            "resultado": {
                "score": scoring_result["score"],
                "score_normalizado": scoring_result["score_normalizado"],
                "nivel": scoring_result["level"],
                "aprobado": scoring_result["aprobado"],
                "rechazo_automatico": scoring_result.get("rechazo_automatico"),
            },
        }

        # Agregar puntaje DataCrédito
        if valores_criterios and "puntaje_datacredito" in valores_criterios:
            registro["datacredito"] = int(valores_criterios["puntaje_datacredito"])
            registro["puntaje_datacredito"] = int(
                valores_criterios["puntaje_datacredito"]
            )

        # Agregar criterios evaluados con detalle ORDENADOS (para el modal)
        if resultados_detalle:
            # Cargar configuración de scoring para obtener el orden de criterios
            scoring_config = cargar_configuracion_scoring()
            criterios_config = scoring_config.get("criterios", {})

            # Crear lista ordenada de criterios (mantiene el orden de scoring.json)
            criterios_detalle_ordenados = []

            for criterio_id in criterios_config.keys():
                if criterio_id in resultados_detalle:
                    datos = resultados_detalle[criterio_id]

                    # El valor ya viene formateado correctamente desde resultados_detalle
                    valor_mostrar = datos.get("valor", "N/A")

                    criterios_detalle_ordenados.append(
                        {
                            "nombre": datos.get("nombre", criterio_id),
                            "puntaje": datos.get("puntos_ponderados", 0),
                            "peso": datos.get("peso", 0),
                            "valor": valor_mostrar,
                            "descripcion": datos.get("descripcion", "N/A"),
                        }
                    )

            registro["criterios_detalle"] = criterios_detalle_ordenados

        # Agregar monto solicitado si existe
        if form_values and "monto_solicitado" in form_values:
            try:
                monto = (
                    form_values.get("monto_solicitado", "")
                    .replace("$", "")
                    .replace(".", "")
                    .replace(",", "")
                    .strip()
                )
                if monto:
                    registro["monto_solicitado"] = int(monto)
            except (ValueError, TypeError):
                pass  # No agregar si el valor no es válido

        # Agregar razón de comité si aplica
        if scoring_result.get("requiere_comite"):
            registro["razon_comite"] = scoring_result.get(
                "razon_comite", "Sin información"
            )

        # MIGRADO A SQLite: Guardar usando db_helpers
        print(
            f"🔵 [REGISTRO] Guardando evaluación en SQLite: {registro.get('nombre_cliente')}"
        )
        guardar_evaluacion_db(registro)
        print(f"🔵 [REGISTRO] ✅ Evaluación guardada exitosamente")

        return True
    except Exception as e:
        print(f"❌ Error registrando evaluación en SQLite: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


# Cargar configuración de seguros al iniciar la aplicación
SEGUROS_CONFIG = cargar_configuracion_seguros()


#  Cargar configuración CON CACHÉ
def cargar_configuracion():
    """
    Carga configuración desde SQLite con sistema de caché.

    MIGRADO A SQLite: Ya no usa config.json, ahora usa base de datos.
    Mantiene el mismo comportamiento y API para compatibilidad.
    """
    global config_cache, last_config_load_time, LINEAS_CREDITO_CACHE, COSTOS_ASOCIADOS_CACHE, USUARIOS_CACHE

    try:
        current_time = time.time()

        # Verificar si existe caché válido (5 minutos)
        if config_cache and (current_time - last_config_load_time) < CACHE_DURATION:
            return config_cache

        # Cargar desde SQLite usando db_helpers
        config = cargar_config_db()

        # Actualizar caché
        config_cache = config
        last_config_load_time = current_time
        LINEAS_CREDITO_CACHE = config.get("LINEAS_CREDITO", {}).copy()
        COSTOS_ASOCIADOS_CACHE = config.get("COSTOS_ASOCIADOS", {}).copy()
        USUARIOS_CACHE = config.get("USUARIOS", {}).copy()

        return config

    except Exception as e:
        logger.error(f"❌ Error al cargar configuración desde SQLite: {e}")

        # Si hay caché viejo, usarlo
        if config_cache:
            logger.warning("⚠️ Usando caché antiguo de configuración")
            return config_cache

        # Si no hay caché, crear configuración predeterminada
        logger.warning("⚠️ Creando configuración predeterminada")
        return crear_configuracion_predeterminada()


#  Guardar configuración CON INVALIDACIÓN DE CACHÉ
def guardar_configuracion(config):
    """
    Guarda configuración en SQLite.

    MIGRADO A SQLite: Ya no guarda en config.json.
    """
    global config_cache, last_config_load_time, LINEAS_CREDITO_CACHE, COSTOS_ASOCIADOS_CACHE, USUARIOS_CACHE

    try:
        # Guardar en SQLite usando db_helpers
        guardar_config_db(config)

        # Actualizar caché
        config_cache = config
        last_config_load_time = time.time()
        LINEAS_CREDITO_CACHE = config.get("LINEAS_CREDITO", {}).copy()
        COSTOS_ASOCIADOS_CACHE = config.get("COSTOS_ASOCIADOS", {}).copy()
        USUARIOS_CACHE = config.get("USUARIOS", {}).copy()

        return True

    except Exception as e:
        logger.error(f"❌ Error al guardar configuración en SQLite: {e}")
        return False


# Crear configuración predeterminada
def crear_configuracion_predeterminada():
    config = {
        "LINEAS_CREDITO": {
            "LoansiFlex": {
                "descripcion": "Crédito de libre inversión.",
                "monto_min": 1000000,
                "monto_max": 20000000,
                "plazo_min": 12,
                "plazo_max": 60,
                "tasa_mensual": 1.8851,
                "aval_porcentaje": 0.10,
                "plazo_tipo": "meses",
                "tasa_anual": 25.12,
            },
            "Microflex": {
                "descripcion": "Crédito informal semanal.",
                "monto_min": 80000,
                "monto_max": 200000,
                "plazo_min": 4,
                "plazo_max": 8,
                "tasa_mensual": 1.9189,
                "aval_porcentaje": 0.00,
                "plazo_tipo": "semanas",
                "tasa_anual": 25.62,
            },
        },
        "COSTOS_ASOCIADOS": {
            "LoansiFlex": {
                "Pagaré Digital": 2800,
                "Carta de Instrucción": 2800,
                "Custodia TVE": 5600,
                "Consulta Datacrédito": 11000,
                "Registro garantías mobiliarias (RGM)": 63070,
            },
            "Microflex": {
                "Pagaré Digital": 2800,
                "Carta de Instrucción": 2800,
                "Consulta Datacrédito": 11000,
            },
        },
        "USUARIOS": {
            "admin": {
                "password_hash": generate_password_hash("admin", method="scrypt"),
                "rol": "admin",
            }
        },
    }
    guardar_configuracion(config)
    return config


try:
    # Cargar configuración al iniciar la aplicación
    config = cargar_configuracion()
    LINEAS_CREDITO = config["LINEAS_CREDITO"]
    COSTOS_ASOCIADOS = config["COSTOS_ASOCIADOS"]
    USUARIOS = config.get(
        "USUARIOS",
        {
            "admin": {
                "password_hash": generate_password_hash("admin", method="scrypt"),
                "rol": "admin",
            }
        },
    )

    # Inicializar variables de caché
    LINEAS_CREDITO_CACHE = LINEAS_CREDITO.copy()
    COSTOS_ASOCIADOS_CACHE = COSTOS_ASOCIADOS.copy()
    USUARIOS_CACHE = USUARIOS.copy()

except Exception as e:
    print(f"ERROR CRÍTICO al inicializar variables globales: {str(e)}")
    config = crear_configuracion_predeterminada()
    LINEAS_CREDITO = config["LINEAS_CREDITO"]
    COSTOS_ASOCIADOS = config["COSTOS_ASOCIADOS"]
    USUARIOS = config["USUARIOS"]

    #  Inicializar variables de caché también en caso de error
    LINEAS_CREDITO_CACHE = LINEAS_CREDITO.copy()
    COSTOS_ASOCIADOS_CACHE = COSTOS_ASOCIADOS.copy()
    USUARIOS_CACHE = USUARIOS.copy()


def calcular_edad_desde_fecha(fecha_nacimiento_str, fecha_referencia=None):
    """
    Calcula edad exacta desde fecha de nacimiento.

    Args:
        fecha_nacimiento_str: String en formato 'YYYY-MM-DD'
        fecha_referencia: datetime o None (usa fecha actual)

    Returns:
        int: Edad en años completos
    """
    from datetime import datetime

    try:
        if isinstance(fecha_nacimiento_str, str):
            fecha_nac = datetime.strptime(fecha_nacimiento_str, "%Y-%m-%d")
        else:
            fecha_nac = fecha_nacimiento_str

        if fecha_referencia is None:
            fecha_ref = datetime.now()
        elif isinstance(fecha_referencia, str):
            fecha_ref = datetime.strptime(fecha_referencia, "%Y-%m-%d")
        else:
            fecha_ref = fecha_referencia

        edad = fecha_ref.year - fecha_nac.year

        # Ajustar si aún no ha cumplido años este año
        if (fecha_ref.month, fecha_ref.day) < (fecha_nac.month, fecha_nac.day):
            edad -= 1

        return edad
    except Exception as e:
        print(f"❌ Error calculando edad: {e}")
        return 0


def meses_entre_fechas(fecha_inicio, fecha_fin):
    """
    Calcula meses completos entre dos fechas (puede incluir decimales)

    Returns:
        float: Meses exactos entre fechas
    """
    from datetime import datetime

    if isinstance(fecha_inicio, str):
        fecha_inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d")
    if isinstance(fecha_fin, str):
        fecha_fin = datetime.strptime(fecha_fin, "%Y-%m-%d")

    años = fecha_fin.year - fecha_inicio.year
    meses = fecha_fin.month - fecha_inicio.month
    dias = fecha_fin.day - fecha_inicio.day

    total_meses = años * 12 + meses + (dias / 30.0)  # Aproximación
    return max(0, total_meses)


def calcular_seguro_anual(edad_cliente, monto_solicitado, plazo_meses):

    global SEGUROS_CONFIG
    millones = monto_solicitado / 1_000_000
    rangos = SEGUROS_CONFIG.get("SEGURO_VIDA", [])

    # Función auxiliar para buscar tarifa según edad
    def obtener_tarifa_por_edad(edad):
        """Retorna la tarifa mensual según la edad del cliente"""
        if not isinstance(rangos, list):
            # Compatibilidad con estructura antigua
            if edad <= 45:
                return 900
            elif edad <= 59:
                return 1100
            else:
                return 1250
        else:
            # Nueva estructura: buscar en rangos
            for rango in rangos:
                if rango["edad_min"] <= edad <= rango["edad_max"]:
                    return rango["costo"]
            return 900  # Default si no encuentra

    #  LÓGICA DE SALTO DE RANGO
    # Paso 1: Calcular edad al FINAL del crédito
    años_credito = math.ceil(plazo_meses / 12)  # Redondear hacia arriba
    edad_final = edad_cliente + años_credito

    # Paso 2: Obtener tarifa para edad INICIAL
    tarifa_inicial = obtener_tarifa_por_edad(edad_cliente)

    # Paso 3: Obtener tarifa para edad FINAL
    tarifa_final = obtener_tarifa_por_edad(edad_final)

    # Paso 4: Usar la tarifa MÁS ALTA (conservador)
    tarifa_mensual = max(tarifa_inicial, tarifa_final)

    # 📊 DEBUG: Logging para auditoría (opcional - puedes comentar estas líneas)
    if tarifa_inicial != tarifa_final:
        print(f"⚠️ SALTO DE RANGO DETECTADO:")
        print(f"   Edad inicial: {edad_cliente} años → Tarifa: ${tarifa_inicial}")
        print(
            f"   Edad final: {edad_final} años ({años_credito} años de crédito) → Tarifa: ${tarifa_final}"
        )
        print(f"   ✅ Tarifa aplicada: ${tarifa_mensual} (la más alta)")

    # Cálculo proporcional al plazo exacto
    años_exactos = plazo_meses / 12
    seguro_calculado = tarifa_mensual * millones * 12 * años_exactos
    return int(round(seguro_calculado))  # Redondear a número entero


def calcular_seguro_proporcional_fecha(
    fecha_nacimiento_str, monto_solicitado, plazo_meses, fecha_inicio_credito=None
):
    """
    Calcula seguro con distribución proporcional según fecha de nacimiento exacta.
    Cobra tarifa de cada rango solo por los meses que el cliente está en ese rango.

    Args:
        fecha_nacimiento_str: String 'YYYY-MM-DD' con fecha de nacimiento
        monto_solicitado: Monto del crédito
        plazo_meses: Plazo en meses (puede ser decimal)
        fecha_inicio_credito: Fecha de inicio (default: hoy)

    Returns:
        int: Seguro total proporcional
    """
    from datetime import datetime, timedelta

    global SEGUROS_CONFIG

    try:
        # Parsear fecha de nacimiento
        if isinstance(fecha_nacimiento_str, str):
            fecha_nac = datetime.strptime(fecha_nacimiento_str, "%Y-%m-%d")
        else:
            fecha_nac = fecha_nacimiento_str

        # Fecha de inicio del crédito
        if fecha_inicio_credito is None:
            fecha_inicio = datetime.now()
        elif isinstance(fecha_inicio_credito, str):
            fecha_inicio = datetime.strptime(fecha_inicio_credito, "%Y-%m-%d")
        else:
            fecha_inicio = fecha_inicio_credito

        # Fecha fin del crédito - usar relativedelta para precisión exacta
        # Soporta meses con decimales separando parte entera y fracción
        meses_enteros = int(plazo_meses)  # Parte entera (ej: 12 de 12.5)
        dias_fraccion = int(
            (plazo_meses - meses_enteros) * 30.44
        )  # Fracción en días (ej: 0.5 meses ≈ 15 días)

        fecha_fin = (
            fecha_inicio
            + relativedelta(months=meses_enteros)
            + timedelta(days=dias_fraccion)
        )

        # Edad inicial
        edad_inicial = calcular_edad_desde_fecha(fecha_nac, fecha_inicio)

        # Función auxiliar para obtener tarifa por edad
        def obtener_tarifa_por_edad(edad):
            rangos = SEGUROS_CONFIG.get("SEGURO_VIDA", [])
            if not isinstance(rangos, list):
                # Fallback estructura antigua
                if edad <= 45:
                    return 900
                elif edad <= 59:
                    return 1100
                else:
                    return 1250

            for rango in rangos:
                if rango["edad_min"] <= edad <= rango["edad_max"]:
                    return rango["costo"]
            return 900  # Default

        # Encontrar todos los cumpleaños durante el crédito
        cumpleaños_durante = []
        edad_cursor = edad_inicial

        for i in range(1, 15):  # Buffer máximo 15 años
            # Fecha del próximo cumpleaños
            fecha_cumple = datetime(
                year=fecha_inicio.year + i, month=fecha_nac.month, day=fecha_nac.day
            )

            # Ajustar si el cumpleaños ya pasó este año
            if fecha_cumple <= fecha_inicio:
                continue

            if fecha_cumple > fecha_fin:
                break

            cumpleaños_durante.append(
                {"fecha": fecha_cumple, "edad_nueva": edad_inicial + i}
            )

        # Construir periodos según cumpleaños
        periodos = []
        fecha_actual = fecha_inicio
        edad_actual = edad_inicial

        for cumple in cumpleaños_durante:
            # Periodo antes del cumpleaños
            meses_periodo = meses_entre_fechas(fecha_actual, cumple["fecha"])
            tarifa = obtener_tarifa_por_edad(edad_actual)

            periodos.append(
                {"meses": meses_periodo, "edad": edad_actual, "tarifa": tarifa}
            )

            # Avanzar al siguiente periodo
            fecha_actual = cumple["fecha"]
            edad_actual = cumple["edad_nueva"]

        # Periodo final (desde último cumpleaños hasta fin de crédito)
        meses_final = meses_entre_fechas(fecha_actual, fecha_fin)
        tarifa_final = obtener_tarifa_por_edad(edad_actual)
        periodos.append(
            {"meses": meses_final, "edad": edad_actual, "tarifa": tarifa_final}
        )

        # Calcular seguro total proporcional
        millones = monto_solicitado / 1_000_000
        seguro_total = 0

        print(f"🔍 CÁLCULO PROPORCIONAL DE SEGURO:")
        print(f"   Fecha nacimiento: {fecha_nac.strftime('%d/%m/%Y')}")
        print(f"   Edad inicial: {edad_inicial} años")
        print(f"   Plazo: {plazo_meses} meses")

        for periodo in periodos:
            # Fórmula simplificada: tarifa_mensual * millones * meses
            seguro_periodo = periodo["tarifa"] * millones * periodo["meses"]
            seguro_total += seguro_periodo

            print(
                f"   • {periodo['meses']:.1f} meses a edad {periodo['edad']} (${periodo['tarifa']}/millón/mes) = ${seguro_periodo:,.0f}"
            )

        print(f"   ✅ Seguro total: ${seguro_total:,.0f}")

        return int(round(seguro_total))

    except Exception as e:
        print(f"❌ Error en cálculo proporcional de seguro: {e}")
        import traceback

        traceback.print_exc()

        # Log estructurado del error
        logger.error(f"Error crítico en cálculo de seguro: {e}", exc_info=True)

        # Si falla cálculo proporcional, retornar 0 y alertar
        print(f"❌ ERROR CRÍTICO: No se pudo calcular seguro proporcional")
        print(f"   Revisar fecha nacimiento: {fecha_nacimiento_str}")
        flash("Error al calcular seguro de vida. Contacte al administrador.", "danger")
        return 0


def formatear_monto(valor):
    """
    Formatea valor monetario anteponiendo $ y usando separador de miles.

    Args:
        valor: int, float o string con el valor monetario

    Returns:
        str: Valor formateado como "$1.000.000"
    """
    try:
        # Normalizar string con separadores a float
        if isinstance(valor, str):
            v = valor.replace(".", "").replace(",", ".")
            num = float(v)
        else:
            num = float(valor)

        # Convertir a entero si no tiene decimales
        num_fmt = int(num) if float(num).is_integer() else num

        return "$" + formatear_con_miles(num_fmt)
    except Exception as e:
        print(f"⚠️ Error formateando monto '{valor}': {str(e)}")
        return "$0"


def formatear_con_miles(numero):
    """
    Formatea números con separador de miles (punto) y decimales (coma).
    Estándar colombiano para valores monetarios.

    - Enteros: Sin decimales (ej: "187.039")
    - Decimales: Con 2 decimales (ej: "2.800,00")

    Args:
        numero: int o float

    Returns:
        str: Número formateado con estilo colombiano

    Examples:
        >>> formatear_con_miles(187039)
        '187.039'
        >>> formatear_con_miles(2800.0)
        '2.800,00'
        >>> formatear_con_miles(2800.50)
        '2.800,50'
    """
    try:
        # Convertir a float para evaluación
        num = float(numero)

        # Detectar si es entero o tiene decimales significativos
        if num == int(num):
            # Es un número entero → SIN decimales (como las cuotas)
            formatted = f"{int(num):,}".replace(",", ".")
        else:
            # Tiene decimales → CON 2 decimales (como costos)
            formatted = (
                f"{num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            )

        return formatted

    except (ValueError, TypeError):
        return "0"


def calcular_cuota(monto_total, tasa_mensual, plazo_meses):
    """
    Calcula la cuota mensual de un préstamo usando amortización francesa.
    Sistema de cuota fija mensual (SIN decimales, como Finsoftek).

    Fórmula: Cuota = (P * i) / (1 - (1 + i)^-n)
    Donde:
    - P = monto_total (capital a financiar)
    - i = tasa_mensual (decimal, ej: 0.017992 para 1.7992%)
    - n = plazo_meses

    Args:
        monto_total: Monto total a financiar (float)
        tasa_mensual: Tasa mensual en DECIMAL (float, ej: 0.017992)
        plazo_meses: Plazo en meses (int o float)

    Returns:
        int: Cuota mensual ENTERA (sin decimales), redondeada

    Example:
        >>> calcular_cuota(2000000, 0.018204, 12)
        187039
    """
    if tasa_mensual == 0:
        # Si no hay interés, dividir monto entre plazo
        return int(round(monto_total / plazo_meses))

    # Fórmula de amortización francesa
    cuota = (monto_total * tasa_mensual) / (1 - (1 + tasa_mensual) ** -plazo_meses)

    # REDONDEO ESTÁNDAR A NÚMERO ENTERO
    # round() de Python usa redondeo bancario, pero para valores con .5
    # En la práctica, coincide con el redondeo estándar en la mayoría de casos
    return int(round(cuota))


def redirigir_a_pagina_permitida():
    """
    Redirige al usuario a una página según sus permisos.
    Orden de preferencia: dashboard > simulador > login
    """
    if session.get("autorizado"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


# --------------------- RUTAS PÚBLICAS (CLIENTES) ---------------------


@app.route("/")
def home():
    """Página principal - Simulador para clientes"""
    # Limpiar flash messages de sesión (no aplican en público)
    session.pop("_flashes", None)

    global LINEAS_CREDITO_CACHE

    # Usar caché o cargar si no existe
    if not LINEAS_CREDITO_CACHE:
        config = cargar_configuracion()
        LINEAS_CREDITO_CACHE = config["LINEAS_CREDITO"]

    return render_template("cliente/formulario.html", lineas=LINEAS_CREDITO_CACHE)


@app.route("/api/csrf-token", methods=["GET"])
def api_csrf_token():
    """
    Endpoint para obtener CSRF token fresco.
    Permite que JavaScript actualice el token antes de submit.
    """
    from flask_wtf.csrf import generate_csrf

    return jsonify({"csrf_token": generate_csrf()})


@app.route("/api/lineas-config", methods=["GET"])
def api_lineas_config():
    """API para obtener configuración actualizada de líneas de crédito"""
    try:
        config = cargar_configuracion()
        lineas = config["LINEAS_CREDITO"]

        # Retornar solo la config necesaria para el frontend
        config_frontend = {}
        for nombre, datos in lineas.items():
            config_frontend[nombre] = {
                "permite_desembolso_neto": datos.get("permite_desembolso_neto", True),
                "desembolso_por_defecto": datos.get(
                    "desembolso_por_defecto", "completo"
                ),
            }

        # Crear response con headers no-cache
        response = jsonify(config_frontend)
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    except Exception as e:
        print(f"❌ Error en API lineas-config: {str(e)}")
        return jsonify({"error": "Error al cargar configuración"}), 500


@app.route("/api/session-status", methods=["GET"])
def api_session_status():
    """
    API para verificar si la sesión del usuario está activa.
    Retorna 200 si está activa, 401 si expiró.
    """
    if not session.get("autorizado"):
        return jsonify({"status": "expired"}), 401

    # Verificar última actividad si existe
    if session.permanent and session.get("last_activity"):
        last_activity = datetime.fromisoformat(session["last_activity"])
        if (datetime.now() - last_activity).total_seconds() > 28800:  # 8 horas
            session.clear()
            return jsonify({"status": "expired"}), 401

    return jsonify({"status": "active"}), 200


@app.route("/calcular", methods=["POST"])
def calcular_cliente():
    """Cálculo de simulación para clientes (sin mostrar costos)"""
    try:
        global LINEAS_CREDITO_CACHE, COSTOS_ASOCIADOS_CACHE

        if not LINEAS_CREDITO_CACHE:
            config = cargar_configuracion()
            LINEAS_CREDITO_CACHE = config["LINEAS_CREDITO"]
            COSTOS_ASOCIADOS_CACHE = config["COSTOS_ASOCIADOS"]

        # Capturar valores del formulario para preservarlos en caso de error
        tipo_credito = request.form.get("tipo_credito", "")
        monto_str = request.form.get("monto", "")
        plazo_str = request.form.get("plazo", "")
        fecha_nacimiento = request.form.get("fecha_nacimiento", "")
        desembolso_completo = request.form.get("desembolso_completo", "")

        if not tipo_credito or tipo_credito not in LINEAS_CREDITO_CACHE:
            flash("Tipo de crédito inválido", "danger")
            return render_template(
                "cliente/formulario.html",
                lineas=LINEAS_CREDITO_CACHE,
                tipo_credito_sel=tipo_credito,
                monto_ingresado=monto_str,
                plazo_ingresado=plazo_str,
                fecha_nacimiento_ingresada=fecha_nacimiento,
                desembolso_sel=desembolso_completo,
            )

        datos = LINEAS_CREDITO_CACHE[tipo_credito]

        # Validar monto
        monto_str_limpio = monto_str.replace(".", "")
        try:
            monto_solicitado = float(monto_str_limpio)
        except:
            flash("Monto inválido. Ingrese solo números.", "danger")
            return render_template(
                "cliente/formulario.html",
                lineas=LINEAS_CREDITO_CACHE,
                tipo_credito_sel=tipo_credito,
                monto_ingresado=monto_str,
                plazo_ingresado=plazo_str,
                fecha_nacimiento_ingresada=fecha_nacimiento,
                desembolso_sel=desembolso_completo,
            )

        #  VALIDACIÓN ESPECÍFICA POR LÍNEA
        if not (datos["monto_min"] <= monto_solicitado <= datos["monto_max"]):
            monto_min_fmt = f"{datos['monto_min']:,.0f}".replace(",", ".")
            monto_max_fmt = f"{datos['monto_max']:,.0f}".replace(",", ".")
            flash(
                f"El monto para {tipo_credito} debe estar entre ${monto_min_fmt} y ${monto_max_fmt}",
                "warning",
            )
            return render_template(
                "cliente/formulario.html",
                lineas=LINEAS_CREDITO_CACHE,
                tipo_credito_sel=tipo_credito,
                monto_ingresado=monto_str,
                plazo_ingresado=plazo_str,
                fecha_nacimiento_ingresada=fecha_nacimiento,
                desembolso_sel=desembolso_completo,
            )

        # Validar plazo
        try:
            plazo = int(plazo_str)
        except:
            flash("Plazo inválido. Ingrese solo números.", "danger")
            return render_template(
                "cliente/formulario.html",
                lineas=LINEAS_CREDITO_CACHE,
                tipo_credito_sel=tipo_credito,
                monto_ingresado=monto_str,
                plazo_ingresado=plazo_str,
                fecha_nacimiento_ingresada=fecha_nacimiento,
                desembolso_sel=desembolso_completo,
            )

        #  VALIDACIÓN ESPECÍFICA DE PLAZO
        if not (datos["plazo_min"] <= plazo <= datos["plazo_max"]):
            flash(
                f"El plazo para {tipo_credito} debe estar entre {datos['plazo_min']} y {datos['plazo_max']} {datos['plazo_tipo']}",
                "warning",
            )
            return render_template(
                "cliente/formulario.html",
                lineas=LINEAS_CREDITO_CACHE,
                tipo_credito_sel=tipo_credito,
                monto_ingresado=monto_str,
                plazo_ingresado=plazo_str,
                fecha_nacimiento_ingresada=fecha_nacimiento,
                desembolso_sel=desembolso_completo,
            )

        #  Validar fecha de nacimiento y calcular edad
        from datetime import datetime

        try:
            if not fecha_nacimiento:
                flash("Debe ingresar su fecha de nacimiento", "warning")
                return render_template(
                    "cliente/formulario.html",
                    lineas=LINEAS_CREDITO_CACHE,
                    tipo_credito_sel=tipo_credito,
                    monto_ingresado=monto_str,
                    plazo_ingresado=plazo_str,
                    fecha_nacimiento_ingresada=fecha_nacimiento,
                    desembolso_sel=desembolso_completo,
                )

            fecha_nac_dt = datetime.strptime(fecha_nacimiento, "%Y-%m-%d")
            edad_cliente = calcular_edad_desde_fecha(fecha_nacimiento)

            if edad_cliente < 18 or edad_cliente > 84:
                flash(
                    "Debes tener entre 18 y 84 años para solicitar el crédito",
                    "warning",
                )
                return render_template(
                    "cliente/formulario.html",
                    lineas=LINEAS_CREDITO_CACHE,
                    tipo_credito_sel=tipo_credito,
                    monto_ingresado=monto_str,
                    plazo_ingresado=plazo_str,
                    fecha_nacimiento_ingresada=fecha_nacimiento,
                    desembolso_sel=desembolso_completo,
                )
        except ValueError:
            flash("Fecha de nacimiento inválida", "danger")
            return render_template(
                "cliente/formulario.html",
                lineas=LINEAS_CREDITO_CACHE,
                tipo_credito_sel=tipo_credito,
                monto_ingresado=monto_str,
                plazo_ingresado=plazo_str,
                fecha_nacimiento_ingresada=fecha_nacimiento,
                desembolso_sel=desembolso_completo,
            )

        tasa_mensual_decimal = datos["tasa_mensual"] / 100
        tasa_mensual_mostrar = datos["tasa_mensual"]
        tasa_efectiva_anual = datos["tasa_anual"]

        plazo_en_meses = (
            plazo if datos["plazo_tipo"] == "meses" else plazo / SEMANAS_POR_MES
        )
        seguro_vida = calcular_seguro_proporcional_fecha(
            fecha_nacimiento, monto_solicitado, plazo_en_meses
        )
        aval = int(round(monto_solicitado * datos["aval_porcentaje"]))
        costos_actuales = COSTOS_ASOCIADOS_CACHE[tipo_credito]

        # Costos totales
        total_costos = sum(costos_actuales.values()) + seguro_vida + aval

        # Modalidad de desembolso
        # Checkbox solo envía valor si está marcado
        desembolso_completo = request.form.get("desembolso_completo") == "on"
        print(f"🔍 DEBUG desembolso_completo: {desembolso_completo}")
        print(f"🔍 DEBUG form data: {request.form.get('desembolso_completo')}")

        if desembolso_completo:
            # MODALIDAD A: Cliente recibe monto solicitado, costos se financian
            monto_total_financiar = monto_solicitado + total_costos
            monto_a_desembolsar = monto_solicitado
        else:
            # MODALIDAD B: Costos se descuentan del desembolso
            monto_total_financiar = monto_solicitado
            monto_a_desembolsar = monto_solicitado - total_costos

            # Validación: monto a desembolsar debe ser positivo
            if monto_a_desembolsar <= 0:
                flash(
                    f"Los costos (${formatear_con_miles(total_costos)}) superan el monto solicitado. Aumenta el monto o selecciona 'Recibir monto completo'.",
                    "warning",
                )
                return redirect(url_for("home"))

        cuota = calcular_cuota(
            monto_total_financiar, tasa_mensual_decimal, plazo_en_meses
        )

        # Determinar tipo de cuota según configuración, no por nombre
        if datos["plazo_tipo"] == "semanas":
            cuota = int(
                round(cuota / SEMANAS_POR_MES)
            )  # Convertir cuota mensual a semanal (52/12 = 4.333...)
            tipo_cuota = "Cuota semanal fija"
            dias_para_pago = 7
        else:  # meses
            tipo_cuota = "Cuota mensual fija"
            dias_para_pago = 30

        primer_pago = (datetime.now() + timedelta(days=dias_para_pago)).strftime(
            "%d/%m/%Y"
        )

        return render_template(
            "cliente/resultado.html",
            tipo_credito=tipo_credito,
            monto_solicitado=formatear_con_miles(monto_solicitado),
            monto_original=formatear_con_miles(monto_solicitado),
            monto_a_desembolsar=formatear_con_miles(monto_a_desembolsar),
            desembolso_completo=desembolso_completo,
            cuota=formatear_con_miles(cuota),
            tipo_cuota=tipo_cuota,
            plazo=plazo,
            plazo_tipo=datos["plazo_tipo"],
            tasa_efectiva_anual=tasa_efectiva_anual,
            tasa_mensual=tasa_mensual_mostrar,
            primer_pago=primer_pago,
        )

    except Exception as e:
        logger.error(f"Error en simulador cliente: {e}", exc_info=True)
        flash(f"Error al calcular: {str(e)}", "danger")
        return redirect(url_for("home"))


# --------------------- SISTEMA CON LOGIN ---------------------


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    # Verificar rate limiting
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    if client_ip:
        client_ip = client_ip.split(",")[
            0
        ].strip()  # Obtener la IP real si está detrás de proxy

    is_blocked, remaining_attempts, lockout_until = check_rate_limit(client_ip)

    if is_blocked:
        minutes_remaining = int((lockout_until - datetime.now()).total_seconds() / 60)
        flash(
            f"⛔ Demasiados intentos fallidos. Tu IP está bloqueada temporalmente. Intenta nuevamente en {minutes_remaining} minutos."
        )
        return render_template(
            "login.html", error=f"Bloqueado por {minutes_remaining} minutos"
        )

    try:
        username = request.form.get("username", "")
        input_password = request.form.get("password", "")

        #  Usar caché de usuarios
        global USUARIOS_CACHE
        if not USUARIOS_CACHE:
            config = cargar_configuracion()
            USUARIOS_CACHE = config["USUARIOS"]

        #  Verificar con check_password_hash (SEGURIDAD)
        if username in USUARIOS_CACHE and check_password_hash(
            USUARIOS_CACHE[username]["password_hash"], input_password
        ):
            # Regenerar session ID para prevenir session fixation
            session.clear()

            #  Marcar sesión como permanente para activar timeout
            session.permanent = True

            session["autorizado"] = True
            session["username"] = username

            # Guardar nombre completo en sesión (para mostrar en navbar)
            session["nombre_completo"] = USUARIOS_CACHE[username].get(
                "nombre_completo", ""
            )

            # Normalización robusta del rol - AHORA guarda rol real
            role_raw = str(USUARIOS_CACHE[username].get("rol", "")).strip().lower()

            # Lista de roles válidos
            roles_validos = [
                "admin",
                "asesor",
                "supervisor",
                "auditor",
                "gerente",
                "admin_tecnico",
                "comite_credito",
            ]

            # Normalizar alias de admin
            if role_raw in {
                "admin",
                "administrador",
                "administrator",
                "root",
                "superuser",
            }:
                role = "admin"
            elif role_raw in roles_validos:
                role = role_raw
            else:
                role = "asesor"  # Fallback para roles desconocidos

            session["rol"] = role

            # Inicializar última actividad para tracking de sesión
            session["last_activity"] = datetime.now().isoformat()

            # Limpiar intentos fallidos tras login exitoso
            clear_attempts(client_ip)

            print(
                f"✅ Login exitoso: {session.get('nombre_completo') or username} ({role})"
            )

            # Redirección según rol después del login
            # TODOS los roles van al dashboard, desde ahí acceden a sus funciones
            if role in ["admin", "admin_tecnico"]:
                return redirect(url_for("admin"))
            else:
                # comite_credito y demás roles van al dashboard
                return redirect(url_for("dashboard"))

        # Registrar intento fallido
        record_failed_attempt(client_ip)

        _, remaining, _ = check_rate_limit(client_ip)

        if remaining > 0:
            error_msg = (
                f"Usuario o contraseña incorrectos. Te quedan {remaining} intento(s)."
            )
        else:
            error_msg = "Usuario o contraseña incorrectos. Próximo intento fallido bloqueará tu IP por 15 minutos."

        return render_template("login.html", error=error_msg)
    except Exception as e:
        return f"Error al procesar login: {str(e)}"


# Ruta de logout
@app.route("/logout")
def logout():
    """Cerrar sesión, limpiar caché y redirigir al login"""
    session.clear()

    #  Crear respuesta con headers que fuerzan limpieza de caché
    # NOTA: NO usar Clear-Site-Data - causa freezing en Chrome móvil (Chromium bug #762417)
    response = make_response(redirect(url_for("login")))
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "-1"

    # Expirar la cookie de sesión explícitamente
    response.set_cookie("session", "", expires=0, httponly=True, samesite="Lax")

    return response


# --------------------- DASHBOARD PERSONALIZADO ---------------------


@app.route("/dashboard")
@no_cache_and_check_session
def dashboard():
    """Dashboard personalizado por rol"""
    if not session.get("autorizado"):
        return redirect(url_for("login"))

    rol = session.get("rol", "asesor")
    username = session.get("username")

    # Obtener estadísticas según rol
    stats = obtener_estadisticas_por_rol(rol, session.get("username"))

    # Obtener resumen para navbar
    resumen_navbar = obtener_resumen_navbar(rol, username)

    # Mapeo de templates por rol
    templates_por_rol = {
        "admin": "dashboards/admin_tecnico.html",  # Admin usa el mismo que admin_tecnico
        "admin_tecnico": "dashboards/admin_tecnico.html",
        "supervisor": "dashboards/supervisor.html",
        "auditor": "dashboards/auditor.html",
        "gerente": "dashboards/gerente.html",
        "comite_credito": "dashboards/comite_credito.html",
        "asesor": "dashboards/asesor.html",
    }

    # Obtener template o usar asesor por defecto
    template = templates_por_rol.get(rol, "dashboards/asesor.html")

    return render_template(template, stats=stats, resumen_navbar=resumen_navbar)


# --------------------- RUTAS PARA ASESORES ---------------------


@app.route("/capacidad_pago")
@no_cache_and_check_session
def capacidad_pago():
    if not session.get("autorizado"):
        return redirect(url_for("login"))

    # Verificar permiso (separado de sim_usar)
    if not tiene_permiso("cap_usar"):
        flash("No tienes permiso para acceder a Capacidad de Pago", "warning")
        return redirigir_a_pagina_permitida()

    return render_template("asesor/capacidad_pago.html")


@app.route("/simulador")
@no_cache_and_check_session
def simulador_asesor():
    # Verificar permiso
    if not tiene_permiso("sim_usar"):
        flash("No tienes permiso para acceder al simulador", "warning")
        return redirigir_a_pagina_permitida()

    global LINEAS_CREDITO_CACHE
    if not LINEAS_CREDITO_CACHE:
        config = cargar_configuracion()
        LINEAS_CREDITO_CACHE = config["LINEAS_CREDITO"]

    # Detectar si viene de un caso aprobado
    timestamp_caso = request.args.get("caso")
    datos_caso = None
    warning_linea = None

    if timestamp_caso:
        try:
            print(f"🔍 Simulador: Cargando datos del caso {timestamp_caso}")

            # Cargar evaluaciones
            evaluaciones = leer_evaluaciones()

            # Buscar el caso
            caso_encontrado = None
            for ev in evaluaciones:
                if ev.get("timestamp") == timestamp_caso:
                    caso_encontrado = ev
                    break

            if caso_encontrado:
                # Determinar monto a usar (prioridad: aprobado > solicitado)
                monto_prellenar = None
                if caso_encontrado.get("decision_admin", {}).get("monto_aprobado"):
                    monto_prellenar = caso_encontrado["decision_admin"][
                        "monto_aprobado"
                    ]
                elif caso_encontrado.get("monto_aprobado"):
                    monto_prellenar = caso_encontrado["monto_aprobado"]
                else:
                    monto_prellenar = caso_encontrado.get("monto_solicitado")

                # Determinar línea de crédito
                linea_caso = caso_encontrado.get(
                    "linea_credito"
                ) or caso_encontrado.get("tipo_credito")

                # Validar que la línea existe en config actual
                if linea_caso not in LINEAS_CREDITO_CACHE:
                    warning_linea = f"⚠️ La línea de crédito '{linea_caso}' ya no está disponible. Se usará 'LoansiFlex' como alternativa."
                    linea_caso = "LoansiFlex"  # Fallback

                # Determinar nivel de riesgo (prioridad: ajustado > calculado)
                nivel_riesgo = None
                if caso_encontrado.get("decision_admin", {}).get(
                    "nivel_riesgo_ajustado"
                ):
                    nivel_riesgo = caso_encontrado["decision_admin"][
                        "nivel_riesgo_ajustado"
                    ]
                elif caso_encontrado.get("nivel_riesgo"):
                    nivel_riesgo = caso_encontrado["nivel_riesgo"]
                elif caso_encontrado.get("resultado", {}).get("nivel"):
                    nivel_riesgo = caso_encontrado["resultado"]["nivel"]

                # Obtener tasas según nivel de riesgo
                tasas_dinamicas = None
                if nivel_riesgo and linea_caso:
                    tasas_dinamicas = obtener_tasa_por_nivel_riesgo(
                        nivel_riesgo, linea_caso
                    )

                datos_caso = {
                    "monto": monto_prellenar,
                    "linea": linea_caso,
                    "nivel_riesgo": nivel_riesgo,
                    "tasas": tasas_dinamicas,
                    "cliente": caso_encontrado.get("nombre_cliente")
                    or caso_encontrado.get("cliente"),
                    "cedula": caso_encontrado.get("cedula"),
                }

                print(
                    f"✅ Datos del caso cargados: Monto={monto_prellenar}, Línea={linea_caso}, Nivel={nivel_riesgo}"
                )

            else:
                # Intentar cargar desde sesión (para casos de scoring automático recién calculados)
                print(f"❌ Caso {timestamp_caso} no encontrado en SQLite")
                print(f"🔍 Buscando en session['ultimo_scoring']...")

                ultimo_scoring = session.get("ultimo_scoring")
                if ultimo_scoring and ultimo_scoring.get("timestamp") == timestamp_caso:
                    print(f"✅ Caso encontrado en sesión (scoring automático)")

                    # Extraer datos del scoring guardado en sesión
                    monto_prellenar = int(ultimo_scoring.get("monto_solicitado", 0))
                    linea_caso = ultimo_scoring.get(
                        "tipo_credito"
                    ) or ultimo_scoring.get("linea_credito")
                    nivel_riesgo = ultimo_scoring.get("nivel_riesgo")

                    # Validar que la línea existe
                    if linea_caso not in LINEAS_CREDITO_CACHE:
                        warning_linea = f"⚠️ La línea de crédito '{linea_caso}' ya no está disponible. Se usará 'LoansiFlex' como alternativa."
                        linea_caso = "LoansiFlex"

                    # Obtener tasas según nivel de riesgo
                    tasas_dinamicas = None
                    if nivel_riesgo and linea_caso:
                        tasas_dinamicas = obtener_tasa_por_nivel_riesgo(
                            nivel_riesgo, linea_caso
                        )

                    datos_caso = {
                        "monto": monto_prellenar,
                        "linea": linea_caso,
                        "nivel_riesgo": nivel_riesgo,
                        "tasas": tasas_dinamicas,
                        "cliente": ultimo_scoring.get("nombre_cliente"),
                        "cedula": None,  # Scoring automático no captura cédula actualmente
                    }

                    print(
                        f"✅ Datos del caso cargados desde sesión: Monto={monto_prellenar}, Línea={linea_caso}, Nivel={nivel_riesgo}"
                    )
                else:
                    print(f"❌ Caso {timestamp_caso} no encontrado en sesión tampoco")
                    flash("Caso no encontrado", "warning")

        except Exception as e:
            print(f"❌ Error al cargar datos del caso: {str(e)}")
            import traceback

            traceback.print_exc()

    return render_template(
        "asesor/simulador.html",
        lineas=LINEAS_CREDITO_CACHE,
        datos_caso=datos_caso,
        warning_linea=warning_linea,
    )


@app.route("/guardar_simulacion", methods=["POST"])
@no_cache_and_check_session
def guardar_simulacion_endpoint():
    """
    Endpoint para guardar una simulación en el historial.
    Llamado desde el simulador cuando el asesor calcula una cuota.
    """
    try:
        data = request.get_json()

        # Validar datos requeridos
        campos_requeridos = [
            "cliente",
            "cedula",
            "monto",
            "plazo",
            "tasa_ea",
            "cuota_mensual",
            "linea_credito",
        ]
        for campo in campos_requeridos:
            if campo not in data:
                return jsonify({"error": f"Falta el campo {campo}"}), 400

        # Construir objeto de simulación
        simulacion = {
            "timestamp": obtener_hora_colombia().isoformat(),
            "asesor": session.get("username", "unknown"),
            "cliente": data["cliente"],
            "cedula": data["cedula"],
            "monto": data["monto"],
            "plazo": data["plazo"],
            "linea_credito": data["linea_credito"],
            "tasa_ea": data["tasa_ea"],
            "tasa_mensual": data.get("tasa_mensual"),
            "cuota_mensual": data["cuota_mensual"],
            "nivel_riesgo": data.get("nivel_riesgo"),
            "aval": data.get("aval"),
            "seguro": data.get("seguro"),
            "plataforma": data.get("plataforma"),
            "total_financiar": data.get("total_financiar"),
        }

        # Guardar simulación
        if guardar_simulacion(simulacion):
            return (
                jsonify(
                    {"success": True, "message": "Simulación guardada correctamente"}
                ),
                200,
            )
        else:
            return jsonify({"error": "Error al guardar simulación"}), 500

    except Exception as e:
        print(f"❌ Error en guardar_simulacion_endpoint: {str(e)}")
        import traceback

        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/historial_simulaciones")
@no_cache_and_check_session
def historial_simulaciones():
    # Verificar permiso
    if not tiene_alguno_de(["sim_hist_propio", "sim_hist_equipo", "sim_hist_todos"]):
        flash("No tienes permiso para ver el historial", "warning")
        return redirigir_a_pagina_permitida()
    """
    Vista del historial de simulaciones.
    Filtra según scope del usuario (propio/equipo/todos).
    """
    try:
        from db_helpers import (
            resolve_visible_usernames,
            obtener_simulaciones_por_asesores,
        )

        username = session.get("username")
        permisos = obtener_permisos_usuario_actual()

        # Resolver qué usuarios puede ver
        scope_info = resolve_visible_usernames(username, permisos, "simulaciones")
        scope = scope_info["scope"]
        usernames_visibles = scope_info.get("usernames_visibles")

        # Obtener simulaciones según scope
        if scope == "todos":
            # Sin filtro - obtener todas
            simulaciones = leer_simulaciones()  # Función correcta que carga todas
        elif usernames_visibles:
            # Filtrar por lista de usuarios
            simulaciones = obtener_simulaciones_por_asesores(usernames_visibles)
        else:
            # Lista vacía = 0 resultados
            simulaciones = []

        # Filtro por asesor específico (desde query string)
        filtro_asesor = request.args.get("asesor", "").strip()
        if filtro_asesor and simulaciones:
            simulaciones = [s for s in simulaciones if s.get("asesor") == filtro_asesor]

        # Agrupar por cliente para estadísticas
        clientes_simulados = {}
        for sim in simulaciones:
            cedula = sim.get("cedula")
            if cedula and cedula not in clientes_simulados:
                clientes_simulados[cedula] = {
                    "nombre": sim.get("cliente"),
                    "cedula": cedula,
                    "total_simulaciones": 0,
                    "ultima_fecha": sim.get("timestamp"),
                }
            if cedula:
                clientes_simulados[cedula]["total_simulaciones"] += 1

        return render_template(
            "asesor/historial_simulaciones.html",
            simulaciones=simulaciones,
            clientes=list(clientes_simulados.values()),
            scope=scope,  # Para mostrar indicador en UI
        )
    except Exception as e:
        print(f"❌ Error en historial_simulaciones: {str(e)}")
        import traceback

        traceback.print_exc()
        flash("Error al cargar historial de simulaciones", "danger")
        return redirect(url_for("simulador_asesor"))


@app.route("/api/simulaciones_cliente/<cedula>")
@no_cache_and_check_session
def api_simulaciones_cliente(cedula):
    """
    API para obtener simulaciones de un cliente específico.
    Usado en el modal de detalle de cliente.
    Respeta el scope del usuario.
    """
    try:
        from db_helpers import resolve_visible_usernames

        username = session.get("username")
        permisos = obtener_permisos_usuario_actual()

        # Resolver scope
        scope_info = resolve_visible_usernames(username, permisos, "simulaciones")
        usernames_visibles = scope_info.get("usernames_visibles")

        # Obtener simulaciones del cliente
        simulaciones = obtener_simulaciones_cliente(cedula)

        # Filtrar si no tiene acceso a todos
        if usernames_visibles is not None:
            simulaciones = [
                s for s in simulaciones if s.get("asesor") in usernames_visibles
            ]

        return jsonify({"simulaciones": simulaciones, "total": len(simulaciones)}), 200
    except Exception as e:
        print(f"❌ Error en api_simulaciones_cliente: {str(e)}")
        return jsonify({"error": str(e)}), 500


def obtener_aval_dinamico(
    monto_solicitado, tipo_credito, datos_linea, scoring_result=None
):
    """
    Calcula el aval dinámico basado en el nivel de riesgo del scoring.
    Si no hay scoring disponible, usa el aval fijo de la línea de crédito.
    Siempre retorna un número entero (sin decimales).
    """
    try:
        # Si scoring_result tiene aval dinámico calculado, usarlo directamente
        if (
            scoring_result
            and isinstance(scoring_result, dict)
            and "aval_dinamico" in scoring_result
        ):
            if scoring_result["aval_dinamico"]:
                aval_porcentaje = scoring_result["aval_dinamico"]["porcentaje"]
                return int(round(monto_solicitado * aval_porcentaje))

        # Si scoring_result tiene puntaje pero no aval_dinamico, calcularlo
        if (
            scoring_result
            and isinstance(scoring_result, dict)
            and "score_normalizado" in scoring_result
        ):
            puntaje_scoring = scoring_result["score_normalizado"]
        else:
            # Sin scoring disponible → usar aval fijo
            return int(round(monto_solicitado * datos_linea["aval_porcentaje"]))

        scoring_config = cargar_configuracion_scoring()

        # Buscar nivel de riesgo según puntaje REAL
        nivel_riesgo = None
        for nivel in scoring_config.get("niveles_riesgo", []):
            if nivel["min"] <= puntaje_scoring <= nivel["max"]:
                nivel_riesgo = nivel
                break

        if (
            nivel_riesgo
            and "aval_por_producto" in nivel_riesgo
            and tipo_credito in nivel_riesgo["aval_por_producto"]
        ):

            aval_porcentaje = nivel_riesgo["aval_por_producto"][tipo_credito]
            return int(round(monto_solicitado * aval_porcentaje))

        # Fallback: aval fijo
        return int(round(monto_solicitado * datos_linea["aval_porcentaje"]))

    except Exception as e:
        print(f"ERROR en obtener_aval_dinamico: {str(e)}")
        return int(round(monto_solicitado * datos_linea["aval_porcentaje"]))


def obtener_tasa_por_nivel_riesgo(nivel_riesgo, linea_credito):
    """
    Obtiene las tasas de interés según el nivel de riesgo y línea de crédito.
    
    ACTUALIZADO: Ahora usa primero el scoring multi-línea, con fallback al sistema antiguo.

    Parámetros:
        nivel_riesgo: str - "Alto Riesgo", "Moderado", "Bajo Riesgo", etc.
        linea_credito: str - "LoansiFlex", "LoansiMoto", etc.

    Retorna:
        dict - {
            'tasa_anual': float,
            'tasa_mensual': float,
            'color': str,
            'aval_porcentaje': float (opcional)
        }
        o None si no se encuentra
    """
    try:
        if not nivel_riesgo or not linea_credito:
            print(
                f"⚠️ obtener_tasa_por_nivel_riesgo: Parámetros inválidos (nivel={nivel_riesgo}, linea={linea_credito})"
            )
            return None

        # Normalizar nombre del nivel para comparación
        nivel_norm = nivel_riesgo.lower().strip()

        # ============================================
        # PASO 1: Intentar obtener de scoring multi-línea
        # ============================================
        try:
            scoring_linea = cargar_scoring_por_linea(linea_credito)
            if scoring_linea and scoring_linea.get("niveles_riesgo"):
                niveles = scoring_linea["niveles_riesgo"]
                
                for nivel in niveles:
                    nombre_nivel = nivel.get("nombre", "").lower().strip()
                    
                    # Comparación flexible
                    if (
                        nombre_nivel == nivel_norm
                        or ("alto" in nombre_nivel and "alto" in nivel_norm)
                        or ("moderado" in nombre_nivel and "moderado" in nivel_norm)
                        or ("bajo" in nombre_nivel and "bajo" in nivel_norm)
                        or ("rescate" in nombre_nivel and "rescate" in nivel_norm)
                    ):
                        # El scoring multi-línea tiene tasa_ea directamente
                        tasa_ea = nivel.get("tasa_ea", 25)
                        tasa_mensual = nivel.get("tasa_nominal_mensual", 1.88)
                        
                        print(
                            f"✅ Tasas multi-línea encontradas para {linea_credito}/{nombre_nivel}: "
                            f"{tasa_ea}% EA / {tasa_mensual}% mensual"
                        )
                        return {
                            "tasa_anual": tasa_ea,
                            "tasa_mensual": tasa_mensual,
                            "color": nivel.get("color", "#999999"),
                            "aval_porcentaje": nivel.get("aval_porcentaje", 0.10),
                        }
                
                print(f"⚠️ Nivel '{nivel_riesgo}' no encontrado en scoring multi-línea de {linea_credito}")
        except Exception as e:
            print(f"⚠️ Error consultando scoring multi-línea: {e}")

        # ============================================
        # PASO 2: Fallback al sistema antiguo (tasas_por_producto)
        # ============================================
        scoring_config = cargar_configuracion_scoring()
        niveles_riesgo = scoring_config.get("niveles_riesgo", [])

        for nivel in niveles_riesgo:
            nombre_nivel = nivel.get("nombre", "").lower().strip()

            # Comparación flexible
            if (
                nombre_nivel == nivel_norm
                or ("alto" in nombre_nivel and "alto" in nivel_norm)
                or ("moderado" in nombre_nivel and "moderado" in nivel_norm)
                or ("bajo" in nombre_nivel and "bajo" in nivel_norm)
            ):
                # Buscar tasas para la línea de crédito específica (formato antiguo)
                tasas_por_producto = nivel.get("tasas_por_producto", {})

                if linea_credito in tasas_por_producto:
                    tasas = tasas_por_producto[linea_credito]
                    print(
                        f"✅ Tasas (legacy) encontradas: {tasas['tasa_anual']}% EA / {tasas['tasa_mensual']}% mensual"
                    )
                    return {
                        "tasa_anual": tasas["tasa_anual"],
                        "tasa_mensual": tasas["tasa_mensual"],
                        "color": nivel.get("color", "#999999"),
                    }

        print(f"⚠️ Nivel de riesgo '{nivel_riesgo}' no encontrado en ninguna configuración")
        return None

    except Exception as e:
        print(f"❌ ERROR en obtener_tasa_por_nivel_riesgo: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


@app.route("/calcular_asesor", methods=["POST"])
@no_cache_and_check_session
def calcular_asesor():
    try:
        global LINEAS_CREDITO_CACHE, COSTOS_ASOCIADOS_CACHE

        if not LINEAS_CREDITO_CACHE or not COSTOS_ASOCIADOS_CACHE:
            config = cargar_configuracion()
            LINEAS_CREDITO_CACHE = config["LINEAS_CREDITO"]
            COSTOS_ASOCIADOS_CACHE = config["COSTOS_ASOCIADOS"]

        # Capturar valores del formulario para preservarlos en caso de error
        tipo_credito = request.form.get("tipo_credito", "")
        monto_str_original = request.form.get("monto", "")
        plazo_str = request.form.get("plazo", "")
        fecha_nacimiento = request.form.get("fecha_nacimiento", "")
        modalidad_desembolso = request.form.get("modalidad_desembolso", "completo")

        if not tipo_credito or tipo_credito not in LINEAS_CREDITO_CACHE:
            flash("Tipo de crédito inválido", "danger")
            return render_template(
                "asesor/simulador.html",
                lineas=LINEAS_CREDITO_CACHE,
                tipo_credito_sel=tipo_credito,
                monto_ingresado=monto_str_original,
                plazo_ingresado=plazo_str,
                fecha_nacimiento_ingresada=fecha_nacimiento,
                modalidad_sel=modalidad_desembolso,
            )

        datos = LINEAS_CREDITO_CACHE[tipo_credito]

        #  DEFINIR TASAS ANTES DE CUALQUIER VALIDACIÓN
        tasa_efectiva_anual = datos.get("tasa_anual", 0)
        tasa_nominal_mensual = datos.get("tasa_mensual", 0)

        # Validar monto
        monto_str = monto_str_original.replace(".", "").replace(",", "")
        try:
            monto_solicitado = float(monto_str)
            if monto_solicitado <= 0 or monto_solicitado > 100000000:
                flash(f"El monto debe estar entre $1 y $100.000.000", "warning")
                return render_template(
                    "asesor/simulador.html",
                    lineas=LINEAS_CREDITO_CACHE,
                    tipo_credito_sel=tipo_credito,
                    monto_ingresado=monto_str_original,
                    plazo_ingresado=plazo_str,
                    fecha_nacimiento_ingresada=fecha_nacimiento,
                    modalidad_sel=modalidad_desembolso,
                )
        except (ValueError, TypeError):
            flash("Monto inválido. Ingrese solo números.", "danger")
            return render_template(
                "asesor/simulador.html",
                lineas=LINEAS_CREDITO_CACHE,
                tipo_credito_sel=tipo_credito,
                monto_ingresado=monto_str_original,
                plazo_ingresado=plazo_str,
                fecha_nacimiento_ingresada=fecha_nacimiento,
                modalidad_sel=modalidad_desembolso,
            )

        # VALIDACIÓN ESPECÍFICA POR LÍNEA DE CRÉDITO
        if not (datos["monto_min"] <= monto_solicitado <= datos["monto_max"]):
            monto_min_fmt = f"{datos['monto_min']:,.0f}".replace(",", ".")
            monto_max_fmt = f"{datos['monto_max']:,.0f}".replace(",", ".")
            flash(
                f"El monto para {tipo_credito} debe estar entre ${monto_min_fmt} y ${monto_max_fmt}",
                "warning",
            )
            return render_template(
                "asesor/simulador.html",
                lineas=LINEAS_CREDITO_CACHE,
                tipo_credito_sel=tipo_credito,
                monto_ingresado=monto_str_original,
                plazo_ingresado=plazo_str,
                fecha_nacimiento_ingresada=fecha_nacimiento,
                modalidad_sel=modalidad_desembolso,
            )

        # Validar plazo
        try:
            plazo = int(plazo_str)
            if plazo <= 0 or plazo > 120:
                flash("El plazo debe estar entre 1 y 120", "warning")
                return render_template(
                    "asesor/simulador.html",
                    lineas=LINEAS_CREDITO_CACHE,
                    tipo_credito_sel=tipo_credito,
                    monto_ingresado=monto_str_original,
                    plazo_ingresado=plazo_str,
                    fecha_nacimiento_ingresada=fecha_nacimiento,
                    modalidad_sel=modalidad_desembolso,
                )
        except (ValueError, TypeError, KeyError):
            flash("Plazo inválido. Ingrese solo números.", "danger")
            return render_template(
                "asesor/simulador.html",
                lineas=LINEAS_CREDITO_CACHE,
                tipo_credito_sel=tipo_credito,
                monto_ingresado=monto_str_original,
                plazo_ingresado=plazo_str,
                fecha_nacimiento_ingresada=fecha_nacimiento,
                modalidad_sel=modalidad_desembolso,
            )

        # VALIDACIÓN ESPECÍFICA DE PLAZO POR LÍNEA
        if not (datos["plazo_min"] <= plazo <= datos["plazo_max"]):
            plazo_tipo_texto = datos["plazo_tipo"]
            flash(
                f"El plazo para {tipo_credito} debe estar entre {datos['plazo_min']} y {datos['plazo_max']} {plazo_tipo_texto}",
                "warning",
            )
            return render_template(
                "asesor/simulador.html",
                lineas=LINEAS_CREDITO_CACHE,
                tipo_credito_sel=tipo_credito,
                monto_ingresado=monto_str_original,
                plazo_ingresado=plazo_str,
                fecha_nacimiento_ingresada=fecha_nacimiento,
                modalidad_sel=modalidad_desembolso,
            )

        # Validar fecha de nacimiento y calcular edad
        from datetime import datetime

        try:
            if not fecha_nacimiento:
                flash("Debe ingresar la fecha de nacimiento del cliente", "warning")
                return render_template(
                    "asesor/simulador.html",
                    lineas=LINEAS_CREDITO_CACHE,
                    tipo_credito_sel=tipo_credito,
                    monto_ingresado=monto_str_original,
                    plazo_ingresado=plazo_str,
                    fecha_nacimiento_ingresada=fecha_nacimiento,
                    modalidad_sel=modalidad_desembolso,
                )

            fecha_nac_dt = datetime.strptime(fecha_nacimiento, "%Y-%m-%d")
            edad_cliente = calcular_edad_desde_fecha(fecha_nacimiento)

            if edad_cliente < 18 or edad_cliente > 84:
                flash(
                    "El cliente debe tener entre 18 y 84 años para solicitar el crédito",
                    "warning",
                )
                return render_template(
                    "asesor/simulador.html",
                    lineas=LINEAS_CREDITO_CACHE,
                    tipo_credito_sel=tipo_credito,
                    monto_ingresado=monto_str_original,
                    plazo_ingresado=plazo_str,
                    fecha_nacimiento_ingresada=fecha_nacimiento,
                    modalidad_sel=modalidad_desembolso,
                )
        except ValueError:
            flash("Fecha de nacimiento inválida", "danger")
            return render_template(
                "asesor/simulador.html",
                lineas=LINEAS_CREDITO_CACHE,
                tipo_credito_sel=tipo_credito,
                monto_ingresado=monto_str_original,
                plazo_ingresado=plazo_str,
                fecha_nacimiento_ingresada=fecha_nacimiento,
                modalidad_sel=modalidad_desembolso,
            )

        # Intentar obtener tasas según nivel de riesgo si viene de caso
        timestamp_caso = request.form.get(
            "timestamp_caso"
        )  # Campo oculto desde simulador.html
        tasas_aplicadas = None
        nivel_usado = None

        if timestamp_caso:
            try:
                # Cargar caso para obtener nivel de riesgo
                evaluaciones = leer_evaluaciones()
                caso = next(
                    (
                        ev
                        for ev in evaluaciones
                        if ev.get("timestamp") == timestamp_caso
                    ),
                    None,
                )

                if caso:
                    # Determinar nivel (prioridad: ajustado > calculado)
                    if caso.get("decision_admin", {}).get("nivel_riesgo_ajustado"):
                        nivel_usado = caso["decision_admin"]["nivel_riesgo_ajustado"]
                    elif caso.get("nivel_riesgo"):
                        nivel_usado = caso["nivel_riesgo"]
                    elif caso.get("resultado", {}).get("nivel"):
                        nivel_usado = caso["resultado"]["nivel"]

                    # Obtener tasas dinámicas
                    if nivel_usado:
                        tasas_aplicadas = obtener_tasa_por_nivel_riesgo(
                            nivel_usado, tipo_credito
                        )

                        if tasas_aplicadas:
                            print(
                                f"✅ Usando tasas dinámicas: {tasas_aplicadas['tasa_anual']}% EA (Nivel: {nivel_usado})"
                            )
            except Exception as e:
                print(f"⚠️ No se pudieron obtener tasas dinámicas: {str(e)}")

        # Aplicar tasas (dinámicas si existen, sino fijas del producto)
        if tasas_aplicadas:
            tasa_mensual_decimal = tasas_aplicadas["tasa_mensual"] / 100
            tasa_mensual_mostrar = tasas_aplicadas["tasa_mensual"]
            tasa_efectiva_anual = tasas_aplicadas["tasa_anual"]
        else:
            tasa_mensual_decimal = datos["tasa_mensual"] / 100
            tasa_mensual_mostrar = datos["tasa_mensual"]
            tasa_efectiva_anual = datos["tasa_anual"]

        plazo_en_meses = (
            plazo if datos["plazo_tipo"] == "meses" else plazo / SEMANAS_POR_MES
        )

        seguro_vida = calcular_seguro_proporcional_fecha(
            fecha_nacimiento, monto_solicitado, plazo_en_meses
        )

        scoring_guardado = session.get("ultimo_scoring")
        scoring_valido = None

        if scoring_guardado and scoring_guardado.get("tipo_credito") == tipo_credito:
            scoring_valido = scoring_guardado

        aval = obtener_aval_dinamico(
            monto_solicitado, tipo_credito, datos, scoring_valido
        )

        costos_actuales = COSTOS_ASOCIADOS_CACHE[tipo_credito].copy()
        costos_actuales["Aval"] = aval
        costos_actuales["Seguro de Vida"] = seguro_vida

        # Costos totales
        total_costos = sum(costos_actuales.values())

        # Modalidad de desembolso
        desembolso_completo = (
            request.form.get("modalidad_desembolso", "completo") == "completo"
        )

        if desembolso_completo:
            # MODALIDAD A: Cliente recibe monto solicitado, costos se financian
            monto_total_financiar = monto_solicitado + total_costos
            monto_a_desembolsar = monto_solicitado
        else:
            # MODALIDAD B: Costos se descuentan del desembolso
            monto_total_financiar = monto_solicitado
            monto_a_desembolsar = monto_solicitado - total_costos

            # Validación: monto a desembolsar debe ser positivo
            if monto_a_desembolsar <= 0:
                flash(
                    f"Los costos (${formatear_con_miles(total_costos)}) superan el monto solicitado. Aumenta el monto o selecciona 'Desembolso completo'.",
                    "danger",
                )
                return redirect(url_for("simulador_asesor"))

        tasa_mensual_decimal = tasa_nominal_mensual / 100
        tasa_mensual_mostrar = tasa_nominal_mensual
        cuota = calcular_cuota(
            monto_total_financiar, tasa_mensual_decimal, plazo_en_meses
        )

        tipo_cuota = "Cuota mensual"
        dias_para_pago = 30

        if datos["plazo_tipo"] == "semanas":
            # Conversión cuota mensual → semanal usando constante precisa
            cuota = int(round(cuota / SEMANAS_POR_MES))  # 52/12 = 4.333...
            tipo_cuota = "Cuota semanal"
            dias_para_pago = 7

        # CÁLCULO CORRECTO DE TEA (Tasa Efectiva Anual)
        # Fórmula: TEA = ((Monto Total Pagado / Monto Solicitado) ^ (12/plazo) - 1) * 100
        # Esta fórmula considera la composición de intereses anualizada

        monto_total_pagado = cuota * plazo_en_meses

        try:
            if plazo_en_meses > 0 and monto_solicitado > 0:
                # Factor de anualización
                # TEA = ((1 + tasa_mensual_decimal)^12 - 1) × 100
                # La TEA se deriva de la tasa mensual aplicada, no de la relación monto pagado/solicitado

                tasa_mensual_para_tea = (
                    tasa_nominal_mensual / 100
                )  # Convertir % a decimal
                tasa_efectiva_real = (math.pow(1 + tasa_mensual_para_tea, 12) - 1) * 100

                # La TEA siempre debe ser mayor que la tasa nominal anual (por capitalización)
                # Validar que TEA sea razonable (entre TNA y TNA + 5%)
                if tasa_efectiva_real < tasa_efectiva_anual or tasa_efectiva_real > (
                    tasa_efectiva_anual + 5
                ):
                    print(
                        f"⚠️ TEA calculada: {tasa_efectiva_real:.2f}% (TNA: {tasa_efectiva_anual}%)"
                    )
            else:
                tasa_efectiva_real = tasa_efectiva_anual  # Fallback a tasa nominal

        except (ZeroDivisionError, ValueError, OverflowError) as e:
            print(f"⚠️ Error calculando TEA: {str(e)}")
            tasa_efectiva_real = tasa_efectiva_anual  # Fallback a tasa nominal

        # Log para auditoría
        print(
            f"📊 TEA calculada: {tasa_efectiva_real:.2f}% (Nominal: {tasa_efectiva_anual}%)"
        )

        diferencia_tasa = tasa_efectiva_real - tasa_efectiva_anual

        costos_formateados = {
            nombre: formatear_con_miles(valor)
            for nombre, valor in costos_actuales.items()
        }

        # ========================================
        # GUARDAR SIMULACIÓN EN HISTORIAL
        # (Solo si viene de un caso prellenado con datos de cliente)
        # ========================================
        timestamp_caso = request.form.get(
            "timestamp_caso"
        )  # Viene de campo oculto si es prellenado
        nombre_cliente = request.form.get(
            "nombre_cliente"
        )  # Viene de campo oculto si es prellenado
        cedula_cliente = request.form.get(
            "cedula_cliente"
        )  # Viene de campo oculto si es prellenado

        if timestamp_caso and nombre_cliente and cedula_cliente:
            # Construir objeto de simulación
            simulacion = {
                "timestamp": obtener_hora_colombia().isoformat(),
                "asesor": session.get("username", "unknown"),
                "cliente": nombre_cliente,
                "cedula": cedula_cliente,
                "monto": int(monto_solicitado),
                "plazo": plazo,
                "linea_credito": tipo_credito,
                "tasa_ea": tasa_efectiva_anual,
                "tasa_mensual": tasa_mensual_mostrar,
                "cuota_mensual": int(cuota),
                "nivel_riesgo": request.form.get("nivel_riesgo"),  # Si viene prellenado
                "aval": costos_actuales.get("aval", 0),
                "seguro": costos_actuales.get("seguro", 0),
                "plataforma": costos_actuales.get("plataforma", 0),
                "total_financiar": int(monto_total_financiar),
                "caso_origen": timestamp_caso,  # Referencia al caso de scoring
                "modalidad_desembolso": "completo" if desembolso_completo else "neto",
            }

            # Guardar simulación
            guardar_simulacion(simulacion)
            print(
                f"✅ Simulación guardada en historial: {nombre_cliente} - ${int(monto_solicitado)}"
            )

        return render_template(
            "asesor/resultado.html",
            tipo_credito=tipo_credito,
            monto_solicitado=formatear_con_miles(monto_solicitado),
            monto_a_desembolsar=formatear_con_miles(monto_a_desembolsar),
            desembolso_completo=desembolso_completo,
            costos=costos_formateados,
            total_costos=formatear_con_miles(total_costos),
            monto_total=formatear_con_miles(monto_total_financiar),
            cuota=formatear_con_miles(cuota),
            tipo_cuota=tipo_cuota,
            plazo=plazo,
            plazo_tipo=datos["plazo_tipo"],
            tasa_efectiva_anual=tasa_efectiva_anual,
            tasa_mensual=tasa_mensual_mostrar,
            tasa_efectiva_real=round(tasa_efectiva_real, 2),
            diferencia_tasa=round(diferencia_tasa, 2),
        )

    except Exception as e:
        logger.error(f"Error en simulador asesor: {e}", exc_info=True)
        flash(f"Error al calcular: {str(e)}", "danger")
        return redirect(url_for("simulador_asesor"))


# --------------------- RUTAS PARA ADMINISTRADOR ---------------------
@app.route("/admin/capacidad/guardar", methods=["POST"])
def admin_capacidad_guardar():
    """
    Guarda los parámetros de capacidad de pago en SQLite.
    MIGRADO A SQLite 2025-12-19: Ya no usa config.json.
    Versión mejorada con validaciones completas y soporte para 3 límites.
    Solo accesible para rol admin.
    """
    # Requiere cfg_cap_editar o cfg_params_editar (retrocompatibilidad)
    if not session.get("autorizado") or not tiene_alguno_de(
        ["cfg_cap_editar", "cfg_params_editar"]
    ):
        flash("No tienes permiso para editar parámetros", "warning")
        return redirect(url_for("admin"))

    try:
        data = request.get_json()

        # Validar datos recibidos
        limite_conservador = int(data.get("limite_conservador", 30))
        limite_maximo = int(data.get("limite_maximo", 35))
        limite_absoluto = int(data.get("limite_absoluto", 40))

        # Validar rangos
        if not (10 <= limite_conservador <= 50):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Límite conservador debe estar entre 10% y 50%",
                    }
                ),
                400,
            )
        if not (10 <= limite_maximo <= 50):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Límite máximo debe estar entre 10% y 50%",
                    }
                ),
                400,
            )
        if not (10 <= limite_absoluto <= 60):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Límite absoluto debe estar entre 10% y 60%",
                    }
                ),
                400,
            )

        # Validar orden lógico
        if not (limite_conservador <= limite_maximo <= limite_absoluto):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Los límites deben estar en orden: conservador ≤ máximo ≤ absoluto",
                    }
                ),
                400,
            )

        # Cargar configuración actual
        config = cargar_configuracion()

        # Actualizar parámetros
        config["PARAMETROS_CAPACIDAD_PAGO"] = {
            "limite_conservador": limite_conservador,
            "limite_maximo": limite_maximo,
            "limite_absoluto": limite_absoluto,
            "descripcion_conservador": data.get(
                "descripcion_conservador",
                "Recomendado para créditos de libre inversión",
            ),
            "descripcion_maximo": data.get(
                "descripcion_maximo", "Límite máximo con scoring alto"
            ),
            "descripcion_absoluto": data.get(
                "descripcion_absoluto", "Solo casos excepcionales"
            ),
            "notas": data.get("notas", ""),
        }

        # Guardar configuración
        guardar_configuracion(config)

        # Limpiar caché (si existe)
        try:
            cache.delete("config")
        except:
            pass

        print(
            f"✅ Parámetros de capacidad actualizados por admin: {limite_conservador}%, {limite_maximo}%, {limite_absoluto}%"
        )

        return jsonify(
            {"success": True, "message": "Parámetros guardados correctamente"}
        )

    except Exception as e:
        print(f"❌ Error al guardar parámetros de capacidad: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/admin")
@no_cache_and_check_session
def admin():
    """Panel de administración con validación exhaustiva de datos"""
    # Validar por permisos de configuración o gestión de usuarios
    if not tiene_alguno_de(
        [
            "admin_panel_acceso",
            "cfg_sco_editar",
            "cfg_tasas_editar",
            "cfg_params_editar",
            "usr_crear",
            "usr_permisos",
        ]
    ):
        flash("No tienes permisos para acceder al panel de administración", "warning")
        return redirigir_a_pagina_permitida()

    try:
        global LINEAS_CREDITO_CACHE, COSTOS_ASOCIADOS_CACHE, USUARIOS_CACHE, SEGUROS_CONFIG_CACHE, SCORING_CONFIG_CACHE

        # CORRECCIÓN 2025-12-23: SIEMPRE recargar desde DB para reflejar cambios
        # Antes usaba "if not CACHE" que causaba datos desactualizados
        config = cargar_configuracion()
        LINEAS_CREDITO_CACHE = config["LINEAS_CREDITO"]
        COSTOS_ASOCIADOS_CACHE = config["COSTOS_ASOCIADOS"]
        USUARIOS_CACHE = config["USUARIOS"]

        # SIEMPRE recargar seguros desde DB
        SEGUROS_CONFIG_CACHE = cargar_configuracion_seguros()

        # SIEMPRE recargar scoring desde DB
        SCORING_CONFIG_CACHE = cargar_configuracion_scoring()

        # Formatear costos
        costos_formateados = {}
        for tipo, costos in COSTOS_ASOCIADOS_CACHE.items():
            costos_formateados[tipo] = {
                nombre: formatear_con_miles(valor) for nombre, valor in costos.items()
            }

        # Extraer datos de scoring
        scoring_criterios = SCORING_CONFIG_CACHE.get("criterios", {})
        niveles_riesgo = SCORING_CONFIG_CACHE.get("niveles_riesgo", [])

        # VALIDACIÓN CRÍTICA: Asegurar que seguros_config existe
        seguros_config_data = SEGUROS_CONFIG_CACHE.get("SEGURO_VIDA", [])

        # Compatibilidad: si es dict viejo, convertir a lista nueva
        if isinstance(seguros_config_data, dict):
            # Estructura antigua detectada, convertir a lista
            seguros_config_data = [
                {
                    "id": 1,
                    "edad_min": 18,
                    "edad_max": 45,
                    "costo": seguros_config_data.get("hasta_45", 900),
                    "descripcion": "Hasta 45 años",
                },
                {
                    "id": 2,
                    "edad_min": 46,
                    "edad_max": 59,
                    "costo": seguros_config_data.get("hasta_59", 1100),
                    "descripcion": "46 a 59 años",
                },
                {
                    "id": 3,
                    "edad_min": 60,
                    "edad_max": 100,
                    "costo": seguros_config_data.get("mas_60", 1250),
                    "descripcion": "60 años o más",
                },
            ]
            print(
                "⚠️ ADVERTENCIA: Estructura antigua de seguros detectada, convertida a nueva estructura"
            )
        elif not seguros_config_data:
            # Sin datos, crear por defecto
            seguros_config_data = [
                {
                    "id": 1,
                    "edad_min": 18,
                    "edad_max": 45,
                    "costo": 900,
                    "descripcion": "Hasta 45 años",
                },
                {
                    "id": 2,
                    "edad_min": 46,
                    "edad_max": 59,
                    "costo": 1100,
                    "descripcion": "46 a 59 años",
                },
                {
                    "id": 3,
                    "edad_min": 60,
                    "edad_max": 100,
                    "costo": 1250,
                    "descripcion": "60 años o más",
                },
            ]
            print("⚠️ ADVERTENCIA: seguros_config vacío, usando valores por defecto")

        #  LOGGING para debugging
        print(f"🔍 DEBUG admin(): seguros_config={seguros_config_data}")
        print(
            f"🔍 DEBUG admin(): costos_asociados keys={list(costos_formateados.keys())}"
        )
        print(f"🔍 DEBUG admin(): scoring_criterios count={len(scoring_criterios)}")

        return render_template(
            "admin/admin.html",
            usuarios=USUARIOS_CACHE,
            costos_asociados=costos_formateados,
            lineas_credito=LINEAS_CREDITO_CACHE,
            scoring_criterios=scoring_criterios,
            scoring_json=SCORING_CONFIG_CACHE,
            niveles_riesgo=niveles_riesgo,
            seguros_config=seguros_config_data,
        )

    except Exception as e:
        #  MANEJO DE ERRORES MEJORADO
        print(f"❌ ERROR CRÍTICO en /admin: {str(e)}")
        import traceback

        traceback.print_exc()
        flash(f"Error al cargar panel de administración: {str(e)}", "danger")
        return redirect(url_for("simulador_asesor"))


@app.route("/admin/lineas", methods=["POST"])
@no_cache_and_check_session
def actualizar_lineas_credito():
    if not tiene_permiso("cfg_tasas_editar"):
        flash("No tienes permiso para editar tasas de crédito", "warning")
        return redirect(url_for("admin"))

    try:
        tipo_credito = request.form.get("tipo_credito")

        config = cargar_configuracion()

        if tipo_credito not in config["LINEAS_CREDITO"]:
            flash(f"Tipo de crédito no válido: {tipo_credito}")
            return redirect(url_for("admin") + "#TasasCredito")

        tasa_anual = request.form.get("tasa_anual")
        if tasa_anual:
            try:
                tasa_anual = float(tasa_anual.replace(",", "."))

                # Conversión Tasa Efectiva Anual (E.A.) → Tasa Nominal Mensual
                # Fórmula: ((1 + Tasa_EA/100)^(1/12)) - 1
                tasa_mensual_decimal = ((1 + (tasa_anual / 100)) ** (1 / 12)) - 1
                tasa_mensual_porcentaje = tasa_mensual_decimal * 100

                config["LINEAS_CREDITO"][tipo_credito]["tasa_anual"] = tasa_anual
                config["LINEAS_CREDITO"][tipo_credito]["tasa_mensual"] = round(
                    tasa_mensual_porcentaje, 4
                )
            except ValueError:
                flash(f"Valor de tasa anual no válido: {tasa_anual}")
                return redirect(url_for("admin") + "#TasasCredito")

        if guardar_configuracion(config):
            flash("Tasas de crédito actualizadas correctamente")
        else:
            flash("Error al guardar configuración. Verifica permisos de escritura.")

        return redirect(url_for("admin") + "#TasasCredito")
    except Exception as e:
        flash(f"Error al actualizar tasas: {str(e)}")
        return redirect(url_for("admin") + "#TasasCredito")


@app.route("/admin/costos", methods=["POST"])
@no_cache_and_check_session
def actualizar_costos():
    """Actualiza costos asociados Y aval_porcentaje de una línea de crédito"""
    # Requiere cfg_costos_editar o cfg_tasas_editar (retrocompatibilidad)
    if not tiene_alguno_de(["cfg_costos_editar", "cfg_tasas_editar"]):
        flash("No tienes permiso para editar costos", "warning")
        return redirect(url_for("admin"))

    try:
        tipo_credito = request.form.get("tipo_credito")

        config = cargar_configuracion()

        if tipo_credito not in config["COSTOS_ASOCIADOS"]:
            flash("Tipo de crédito no válido")
            return redirect(url_for("admin") + "#CostosAsociados")

        # CORRECCIÓN BUG #4: Leer y guardar aval_porcentaje
        aval_str = request.form.get("aval_porcentaje", "")
        if aval_str:
            try:
                aval_porcentaje = float(aval_str.replace(",", ".")) / 100
                if tipo_credito in config.get("LINEAS_CREDITO", {}):
                    config["LINEAS_CREDITO"][tipo_credito][
                        "aval_porcentaje"
                    ] = aval_porcentaje
                    print(
                        f"✅ Aval actualizado para '{tipo_credito}': {aval_porcentaje * 100}%"
                    )
            except ValueError:
                print(f"⚠️ Valor de aval inválido: {aval_str}")

        nuevos_costos = {}
        index = 0
        while True:
            nombre_key = f"nombre_costo_{index}"
            valor_key = f"valor_costo_{index}"
            nombre = request.form.get(nombre_key)
            valor_str = request.form.get(valor_key)

            if not nombre and not valor_str:
                break

            if not nombre or not valor_str:
                flash(f"Costo {index+1}: Nombre o valor incompleto")
                return redirect(url_for("admin") + "#CostosAsociados")

            try:
                valor = float(valor_str.replace(".", "").replace(",", ""))
                if valor < 0:
                    flash(f"Costo {index+1}: Valor no puede ser negativo")
                    return redirect(url_for("admin") + "#CostosAsociados")
            except ValueError:
                flash(f"Costo {index+1}: Valor debe ser un número")
                return redirect(url_for("admin") + "#CostosAsociados")

            nuevos_costos[nombre] = valor
            index += 1

        config["COSTOS_ASOCIADOS"][tipo_credito] = nuevos_costos

        if guardar_configuracion(config):
            # Invalidar cachés
            global LINEAS_CREDITO_CACHE, COSTOS_ASOCIADOS_CACHE, config_cache, last_config_load_time
            LINEAS_CREDITO_CACHE = None
            COSTOS_ASOCIADOS_CACHE = None
            config_cache = None
            last_config_load_time = 0
            flash("Costos y aval actualizados correctamente")
        else:
            flash("Error al guardar configuración. Verifica permisos de escritura.")

        return redirect(url_for("admin") + "#CostosAsociados")
    except Exception as e:
        print(f"❌ Error en actualizar_costos: {str(e)}")
        flash(f"Error al actualizar costos: {str(e)}")
        return redirect(url_for("admin") + "#CostosAsociados")


@app.route("/admin/seguros", methods=["POST"])
@no_cache_and_check_session
def actualizar_seguros():
    # Requiere cfg_seguros_editar o cfg_tasas_editar (retrocompatibilidad)
    if not tiene_alguno_de(["cfg_seguros_editar", "cfg_tasas_editar"]):
        flash("No tienes permiso para editar seguros", "warning")
        return redirect(url_for("admin"))

    try:
        # Obtener todos los rangos del formulario
        rangos_nuevos = []
        i = 0

        while True:
            edad_min = request.form.get(f"edad_min_{i}")
            edad_max = request.form.get(f"edad_max_{i}")
            costo = request.form.get(f"costo_{i}")
            descripcion = request.form.get(f"descripcion_{i}")

            if not edad_min:  # No hay más rangos
                break

            try:
                edad_min = int(edad_min)
                edad_max = int(edad_max)
                costo = int(float(costo.replace(".", "").replace(",", "")))

                if edad_min < 18 or edad_max > 120:
                    flash("Las edades deben estar entre 18 y 120 años")
                    return redirect(url_for("admin") + "#Seguros")

                if edad_min >= edad_max:
                    flash("La edad mínima debe ser menor que la edad máxima")
                    return redirect(url_for("admin") + "#Seguros")

                if costo < 0:
                    flash("El costo no puede ser negativo")
                    return redirect(url_for("admin") + "#Seguros")

                rangos_nuevos.append(
                    {
                        "id": i + 1,
                        "edad_min": edad_min,
                        "edad_max": edad_max,
                        "costo": costo,
                        "descripcion": descripcion or f"{edad_min} a {edad_max} años",
                    }
                )

            except ValueError:
                flash(f"Error en rango {i+1}: valores inválidos")
                return redirect(url_for("admin") + "#Seguros")

            i += 1

        if not rangos_nuevos:
            flash("Debe haber al menos un rango de seguro")
            return redirect(url_for("admin") + "#Seguros")

        # Ordenar por edad_min
        rangos_nuevos.sort(key=lambda x: x["edad_min"])

        # Validar que no haya solapamientos
        for i in range(len(rangos_nuevos) - 1):
            if rangos_nuevos[i]["edad_max"] >= rangos_nuevos[i + 1]["edad_min"]:
                flash("Los rangos de edad no pueden solaparse")
                return redirect(url_for("admin") + "#Seguros")

        seguros_config = {"SEGURO_VIDA": rangos_nuevos}

        if guardar_configuracion_seguros(seguros_config):
            global SEGUROS_CONFIG
            SEGUROS_CONFIG = seguros_config
            flash("Configuración de seguros actualizada correctamente")
        else:
            flash("Error al guardar configuración de seguros")

    except Exception as e:
        print(f"❌ Error al actualizar seguros: {str(e)}")
        import traceback

        traceback.print_exc()
        flash(f"Error al actualizar seguros: {str(e)}")

    return redirect(url_for("admin") + "#Seguros")


@app.route("/admin/usuario/nuevo", methods=["POST"])
@no_cache_and_check_session
def crear_usuario():
    if not tiene_permiso("usr_crear"):
        return (
            jsonify(
                {"success": False, "error": "No tienes permiso para crear usuarios"}
            ),
            403,
        )

    try:
        nombre_completo = request.form.get("nombre_completo", "").strip()
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password")
        rol = request.form.get("rol")

        # Validaciones
        if not nombre_completo or not username or not password or not rol:
            flash("Todos los campos son obligatorios", "danger")
            return redirect(url_for("admin") + "#Usuarios")

        config = cargar_configuracion()

        if username in config["USUARIOS"]:
            flash("El usuario ya existe", "danger")
            return redirect(url_for("admin") + "#Usuarios")

        roles_validos = [
            "admin",
            "asesor",
            "supervisor",
            "auditor",
            "gerente",
            "admin_tecnico",
            "comite_credito",
        ]
        if rol not in roles_validos:
            flash("Rol inválido", "danger")
            return redirect(url_for("admin") + "#Usuarios")

        if len(password) < 6:
            flash("La contraseña debe tener al menos 6 caracteres", "danger")
            return redirect(url_for("admin") + "#Usuarios")

        # Validar username sin espacios
        if " " in username:
            flash("El nombre de usuario no puede contener espacios", "danger")
            return redirect(url_for("admin") + "#Usuarios")

        password_hash = generate_password_hash(password, method="scrypt")

        # Guardar con nombre_completo
        config["USUARIOS"][username] = {
            "password_hash": password_hash,
            "rol": rol,
            "nombre_completo": nombre_completo,
        }

        if guardar_configuracion(config):
            # Invalidar caché para que el nuevo usuario sea visible
            global USUARIOS_CACHE
            USUARIOS_CACHE = config["USUARIOS"].copy()
            flash(
                f"Usuario '{nombre_completo}' (@{username}) creado correctamente",
                "success",
            )
        else:
            flash("Error al guardar configuración", "danger")

    except Exception as e:
        flash(f"Error al crear usuario: {str(e)}")

    return redirect(url_for("admin") + "#Usuarios")


@app.route("/admin/usuario/cambiar-password", methods=["POST"])
@no_cache_and_check_session
def cambiar_password():
    if not tiene_permiso("usr_password"):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "No tienes permiso para cambiar contraseñas",
                }
            ),
            403,
        )

    try:
        username = request.form.get("username")
        new_password = request.form.get("new_password")

        if not username or not new_password:
            flash("Usuario y contraseña son obligatorios")
            return redirect(url_for("admin") + "#Usuarios")

        config = cargar_configuracion()

        if username not in config["USUARIOS"]:
            flash("Usuario no encontrado")
            return redirect(url_for("admin") + "#Usuarios")

        if len(new_password) < 6:
            flash("La contraseña debe tener al menos 6 caracteres")
            return redirect(url_for("admin") + "#Usuarios")

        password_hash = generate_password_hash(new_password, method="scrypt")

        config["USUARIOS"][username]["password_hash"] = password_hash

        if guardar_configuracion(config):
            flash("Contraseña actualizada correctamente")
        else:
            flash("Error al guardar configuración")

    except Exception as e:
        flash(f"Error al cambiar contraseña: {str(e)}")

    return redirect(url_for("admin") + "#Usuarios")


@app.route("/admin/usuario/eliminar", methods=["POST"])
@no_cache_and_check_session
def eliminar_usuario():
    if not tiene_permiso("usr_eliminar"):
        return (
            jsonify(
                {"success": False, "error": "No tienes permiso para eliminar usuarios"}
            ),
            403,
        )

    try:
        username = request.form.get("username")

        config = cargar_configuracion()

        if not username or username not in config["USUARIOS"]:
            flash("Usuario no válido")
            return redirect(url_for("admin") + "#Usuarios")

        if username == "admin":
            flash("No se puede eliminar el usuario administrador")
            return redirect(url_for("admin") + "#Usuarios")

        from db_helpers import eliminar_usuario_db

        if eliminar_usuario_db(username):
            # También actualizar config en memoria
            del config["USUARIOS"][username]
            flash("Usuario eliminado correctamente")
        else:
            flash("Error al eliminar usuario de la base de datos.")

        return redirect(url_for("admin") + "#Usuarios")

    except Exception as e:
        flash(f"Error al eliminar usuario: {str(e)}")
        return redirect(url_for("admin") + "#Usuarios")


@app.route("/admin/lineas/nueva", methods=["POST"])
@no_cache_and_check_session
def crear_nueva_linea_credito():
    # Requiere cfg_tasas_crear o cfg_tasas_editar (retrocompatibilidad)
    if not tiene_alguno_de(["cfg_tasas_crear", "cfg_tasas_editar"]):
        flash("No tienes permiso para crear líneas de crédito", "warning")
        return redirect(url_for("admin"))

    try:
        nombre_linea = request.form.get("nombre_linea", "").strip()
        descripcion = request.form.get("descripcion", "").strip()
        plazo_tipo = request.form.get("plazo_tipo", "meses")

        monto_min = float(
            request.form.get("monto_min", "0").replace(".", "").replace(",", "")
        )
        monto_max = float(
            request.form.get("monto_max", "0").replace(".", "").replace(",", "")
        )

        plazo_min = int(request.form.get("plazo_min", "1"))
        plazo_max = int(request.form.get("plazo_max", "12"))

        tasa_anual = float(request.form.get("tasa_anual", "25.12").replace(",", "."))
        aval_porcentaje = float(request.form.get("aval_porcentaje", "10")) / 100
        # Configuración de desembolso
        permite_desembolso_neto = request.form.get("permite_desembolso_neto") == "on"
        desembolso_por_defecto = request.form.get("desembolso_por_defecto", "completo")

        costo_pagare = float(request.form.get("costo_pagare", "2800").replace(".", ""))
        costo_carta = float(request.form.get("costo_carta", "2800").replace(".", ""))
        costo_datacredito = float(
            request.form.get("costo_datacredito", "11000").replace(".", "")
        )
        costo_custodia = float(
            request.form.get("costo_custodia", "5600").replace(".", "")
        )

        if not nombre_linea or not descripcion:
            flash("El nombre y descripción de la línea son obligatorios")
            return redirect(url_for("admin") + "#TasasCredito")

        config = cargar_configuracion()

        if nombre_linea in config["LINEAS_CREDITO"]:
            flash(f"Ya existe una línea de crédito con el nombre '{nombre_linea}'")
            return redirect(url_for("admin") + "#TasasCredito")

        if monto_min >= monto_max:
            flash("El monto mínimo debe ser menor que el monto máximo")
            return redirect(url_for("admin") + "#TasasCredito")

        if plazo_min >= plazo_max:
            flash("El plazo mínimo debe ser menor que el plazo máximo")
            return redirect(url_for("admin") + "#TasasCredito")

        tasa_mensual_porcentaje = tasa_anual / 12

        nueva_linea = {
            "descripcion": descripcion,
            "monto_min": int(monto_min),
            "monto_max": int(monto_max),
            "plazo_min": plazo_min,
            "plazo_max": plazo_max,
            "tasa_mensual": round(tasa_mensual_porcentaje, 4),
            "aval_porcentaje": aval_porcentaje,
            "plazo_tipo": plazo_tipo,
            "tasa_anual": tasa_anual,
            "permite_desembolso_neto": permite_desembolso_neto,
            "desembolso_por_defecto": desembolso_por_defecto,
        }

        config["LINEAS_CREDITO"][nombre_linea] = nueva_linea

        nuevos_costos = {
            "Pagaré Digital": costo_pagare,
            "Carta de Instrucción": costo_carta,
            "Consulta Datacrédito": costo_datacredito,
        }

        if costo_custodia > 0:
            nuevos_costos["Custodia TVE"] = costo_custodia

        config["COSTOS_ASOCIADOS"][nombre_linea] = nuevos_costos

        if not guardar_configuracion(config):
            flash("Error al guardar la configuración principal")
            return redirect(url_for("admin") + "#TasasCredito")

        # ============================================
        # CREAR CONFIGURACIÓN DE SCORING MULTI-LÍNEA
        # ============================================
        try:
            # Obtener el ID de la línea recién creada
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "loansi.db")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM lineas_credito WHERE nombre = ?", (nombre_linea,))
            linea_row = cursor.fetchone()
            conn.close()
            
            if linea_row:
                linea_id = linea_row[0]
                print(f"📦 Creando configuración de scoring para nueva línea: {nombre_linea} (ID: {linea_id})")
                
                # Crear configuración de scoring multi-línea por defecto
                if crear_config_scoring_linea_defecto(linea_id, tasa_anual):
                    print(f"✅ Configuración de scoring creada para {nombre_linea}")
                else:
                    flash(
                        "Advertencia: La línea se creó pero hubo un error al crear el scoring automático",
                        "warning"
                    )
            else:
                print(f"⚠️ No se encontró ID para la línea {nombre_linea}")
                flash(
                    "Advertencia: La línea se creó pero no se pudo configurar el scoring automático",
                    "warning"
                )

        except Exception as e:
            print(f"Error al crear scoring automático: {str(e)}")
            import traceback
            traceback.print_exc()
            flash(
                "Advertencia: La línea se creó pero hubo un error al configurar el scoring",
                "warning"
            )

        flash(
            f"Línea de crédito '{nombre_linea}' creada exitosamente con scoring configurado automáticamente",
            "success"
        )
        return redirect(url_for("admin") + "#TasasCredito")

    except Exception as e:
        print(f"Error al crear nueva línea de crédito: {str(e)}")
        flash(f"Error al crear la línea de crédito: {str(e)}")
        return redirect(url_for("admin") + "#TasasCredito")


@app.route("/admin/lineas/editar", methods=["POST"])
@no_cache_and_check_session
def editar_linea_credito():
    """Edita una línea de crédito existente"""
    if not tiene_permiso("cfg_tasas_editar"):
        flash("No tienes permiso para editar líneas de crédito", "warning")
        return redirect(url_for("admin"))

    try:
        nombre_original = request.form.get("nombre_original", "").strip()
        nombre_nuevo = request.form.get("nombre_linea", "").strip()
        descripcion = request.form.get("descripcion", "").strip()
        plazo_tipo = request.form.get("plazo_tipo", "meses")

        #  Logging para debug
        print(f"📝 Editando línea de crédito:")
        print(f"   - Nombre original: '{nombre_original}'")
        print(f"   - Nombre nuevo: '{nombre_nuevo}'")
        print(f"   - Descripción: '{descripcion}'")

        monto_min = float(
            request.form.get("monto_min", "0").replace(".", "").replace(",", "")
        )
        monto_max = float(
            request.form.get("monto_max", "0").replace(".", "").replace(",", "")
        )

        plazo_min = int(request.form.get("plazo_min", "1"))
        plazo_max = int(request.form.get("plazo_max", "12"))

        # CORRECCIÓN BUG #1: Leer tasa_anual del formulario
        tasa_anual_str = request.form.get("tasa_anual", "")
        if tasa_anual_str:
            tasa_anual = float(tasa_anual_str.replace(",", "."))
            # Conversión E.A. a mensual
            tasa_mensual_porcentaje = ((1 + (tasa_anual / 100)) ** (1 / 12) - 1) * 100
        else:
            tasa_anual = None
            tasa_mensual_porcentaje = None

        # CORRECCIÓN BUG #1: Leer aval_porcentaje del formulario
        aval_porcentaje_str = request.form.get("aval_porcentaje", "")
        if aval_porcentaje_str:
            aval_porcentaje = float(aval_porcentaje_str.replace(",", ".")) / 100
            print(f"✅ Aval porcentaje recibido: {aval_porcentaje * 100}%")
        else:
            aval_porcentaje = None  # Mantener valor existente

        # Leer configuración de desembolso
        permite_neto_str = request.form.get("permite_desembolso_neto", "false")
        permite_desembolso_neto = permite_neto_str.lower() == "true"
        desembolso_por_defecto = request.form.get("desembolso_por_defecto", "completo")

        print(
            f"✅ Permite desembolso neto: {permite_desembolso_neto} (raw: {permite_neto_str})"
        )
        print(f"✅ Modalidad por defecto: {desembolso_por_defecto}")

        config = cargar_configuracion()

        #  Validación mejorada
        if not nombre_original:
            print("❌ Error: nombre_original está vacío")
            flash("Error: No se recibió el nombre original de la línea")
            return redirect(url_for("admin") + "#TasasCredito")

        if nombre_original not in config["LINEAS_CREDITO"]:
            print(f"❌ Error: '{nombre_original}' no existe en config")
            print(f"   Líneas disponibles: {list(config['LINEAS_CREDITO'].keys())}")
            flash(f"Línea de crédito '{nombre_original}' no encontrada")
            return redirect(url_for("admin") + "#TasasCredito")

        if not nombre_nuevo or not descripcion:
            flash("El nombre y descripción son obligatorios")
            return redirect(url_for("admin") + "#TasasCredito")

        # Validar que no exista otra línea con el nuevo nombre (si cambió)
        if nombre_nuevo != nombre_original and nombre_nuevo in config["LINEAS_CREDITO"]:
            flash(f"Ya existe una línea de crédito con el nombre '{nombre_nuevo}'")
            return redirect(url_for("admin") + "#TasasCredito")

        # Validaciones de negocio
        if monto_min >= monto_max:
            flash("El monto mínimo debe ser menor que el monto máximo")
            return redirect(url_for("admin") + "#TasasCredito")

        if plazo_min >= plazo_max:
            flash("El plazo mínimo debe ser menor que el plazo máximo")
            return redirect(url_for("admin") + "#TasasCredito")

        # Obtener línea actual y actualizar datos
        linea_actual = config["LINEAS_CREDITO"][nombre_original].copy()

        print(f"📊 Datos anteriores: {linea_actual}")

        # CORRECCIÓN BUG #1: Construir diccionario de actualización con todos los campos
        datos_actualizacion = {
            "descripcion": descripcion,
            "monto_min": int(monto_min),
            "monto_max": int(monto_max),
            "plazo_min": plazo_min,
            "plazo_max": plazo_max,
            "plazo_tipo": plazo_tipo,
            "permite_desembolso_neto": permite_desembolso_neto,
            "desembolso_por_defecto": desembolso_por_defecto,
        }

        # Solo actualizar aval si se proporcionó (CORRECCIÓN BUG #1)
        if aval_porcentaje is not None:
            datos_actualizacion["aval_porcentaje"] = aval_porcentaje
            print(f"✅ Aval porcentaje actualizado: {aval_porcentaje * 100}%")

        # Solo actualizar tasas si se proporcionaron
        if tasa_anual is not None:
            datos_actualizacion["tasa_anual"] = tasa_anual
            datos_actualizacion["tasa_mensual"] = round(tasa_mensual_porcentaje, 4)
            print(
                f"✅ Tasas actualizadas: {tasa_anual}% E.A. → {round(tasa_mensual_porcentaje, 4)}% mensual"
            )

        linea_actual.update(datos_actualizacion)

        print(f"📊 Datos nuevos: {linea_actual}")

        # Si cambió el nombre, renombrar en todas las secciones
        if nombre_nuevo != nombre_original:
            print(f"🔄 Renombrando '{nombre_original}' → '{nombre_nuevo}'")

            # Crear nueva entrada con el nuevo nombre
            config["LINEAS_CREDITO"][nombre_nuevo] = linea_actual
            # Eliminar la entrada antigua
            del config["LINEAS_CREDITO"][nombre_original]

            # Renombrar en costos asociados
            if nombre_original in config["COSTOS_ASOCIADOS"]:
                config["COSTOS_ASOCIADOS"][nombre_nuevo] = config["COSTOS_ASOCIADOS"][
                    nombre_original
                ]
                del config["COSTOS_ASOCIADOS"][nombre_original]

            # Renombrar en scoring (tasas por producto)
            try:
                scoring_config = cargar_configuracion_scoring()

                for nivel in scoring_config.get("niveles_riesgo", []):
                    if (
                        "tasas_por_producto" in nivel
                        and nombre_original in nivel["tasas_por_producto"]
                    ):
                        nivel["tasas_por_producto"][nombre_nuevo] = nivel[
                            "tasas_por_producto"
                        ][nombre_original]
                        del nivel["tasas_por_producto"][nombre_original]

                    if (
                        "aval_por_producto" in nivel
                        and nombre_original in nivel["aval_por_producto"]
                    ):
                        nivel["aval_por_producto"][nombre_nuevo] = nivel[
                            "aval_por_producto"
                        ][nombre_original]
                        del nivel["aval_por_producto"][nombre_original]

                guardar_configuracion_scoring(scoring_config)
                print("✅ Scoring actualizado con nuevo nombre")
            except Exception as e:
                print(f"⚠️ Error al actualizar scoring: {str(e)}")

        else:
            # Solo actualizar datos sin renombrar
            config["LINEAS_CREDITO"][nombre_original] = linea_actual
            print(f"✅ Línea '{nombre_original}' actualizada sin cambiar nombre")

        # Guardar configuración
        if guardar_configuracion(config):
            print("✅ Configuración guardada exitosamente")

            # Invalidar caché para reflejar cambios inmediatamente
            global config_cache, last_config_load_time, LINEAS_CREDITO_CACHE
            config_cache = None
            last_config_load_time = 0
            LINEAS_CREDITO_CACHE = None
            print("✅ Caché invalidado - próximas cargas verán cambios")

            flash(f"Línea de crédito actualizada exitosamente")
        else:
            print("❌ Error al guardar la configuración")
            flash("Error al guardar la configuración")

        return redirect(url_for("admin") + "#TasasCredito")

    except Exception as e:
        print(f"❌ Error al editar línea de crédito: {str(e)}")
        import traceback

        traceback.print_exc()
        flash(f"Error al editar la línea de crédito: {str(e)}")
        return redirect(url_for("admin") + "#TasasCredito")


@app.route("/admin/lineas/eliminar", methods=["POST"])
@no_cache_and_check_session
def eliminar_linea_credito():
    """Elimina una línea de crédito (soft delete en DB) - CORREGIDO 2025-12-23"""
    # Requiere cfg_tasas_eliminar o cfg_tasas_editar (retrocompatibilidad)
    if not tiene_alguno_de(["cfg_tasas_eliminar", "cfg_tasas_editar"]):
        flash("No tienes permiso para eliminar líneas de crédito", "warning")
        return redirect(url_for("admin"))

    try:
        nombre_linea = request.form.get("nombre_linea", "").strip()

        if not nombre_linea:
            flash("Nombre de línea no proporcionado")
            return redirect(url_for("admin") + "#TasasCredito")

        config = cargar_configuracion()

        if nombre_linea not in config["LINEAS_CREDITO"]:
            flash("Línea de crédito no encontrada")
            return redirect(url_for("admin") + "#TasasCredito")

        if len(config["LINEAS_CREDITO"]) <= 1:
            flash("No se puede eliminar la única línea de crédito del sistema")
            return redirect(url_for("admin") + "#TasasCredito")

        # CORRECCIÓN BUG #2: Eliminar de la base de datos (soft delete)
        # Esto marca activo=0 en la DB para que no se cargue de nuevo
        if not eliminar_linea_credito_db(nombre_linea):
            flash("Error al eliminar la línea de la base de datos")
            return redirect(url_for("admin") + "#TasasCredito")

        # Actualizar scoring para remover referencias
        try:
            scoring_config = cargar_configuracion_scoring()

            for nivel in scoring_config.get("niveles_riesgo", []):
                if (
                    "tasas_por_producto" in nivel
                    and nombre_linea in nivel["tasas_por_producto"]
                ):
                    del nivel["tasas_por_producto"][nombre_linea]
                if (
                    "aval_por_producto" in nivel
                    and nombre_linea in nivel["aval_por_producto"]
                ):
                    del nivel["aval_por_producto"][nombre_linea]

            guardar_configuracion_scoring(scoring_config)
            print(f"✅ Scoring actualizado - línea '{nombre_linea}' removida")

        except Exception as e:
            print(f"⚠️ Error al actualizar scoring en eliminación: {str(e)}")

        # Invalidar cachés para forzar recarga desde DB (CRÍTICO)
        global LINEAS_CREDITO_CACHE, COSTOS_ASOCIADOS_CACHE, config_cache, last_config_load_time
        LINEAS_CREDITO_CACHE = None
        COSTOS_ASOCIADOS_CACHE = None
        config_cache = None
        last_config_load_time = 0
        print("✅ Cachés invalidados")

        flash(f"Línea de crédito '{nombre_linea}' eliminada exitosamente")
        return redirect(url_for("admin") + "#TasasCredito")

    except Exception as e:
        print(f"❌ Error al eliminar línea de crédito: {str(e)}")
        import traceback

        traceback.print_exc()
        flash(f"Error al eliminar la línea de crédito: {str(e)}")
        return redirect(url_for("admin") + "#TasasCredito")


# --------------------- RUTAS PARA SCORING ---------------------
@app.route("/scoring")
@no_cache_and_check_session
def scoring_page():
    # Verificar permiso
    if not tiene_permiso("sco_ejecutar"):
        flash("No tienes permiso para acceder al Scoring", "warning")
        return redirigir_a_pagina_permitida()

    global SCORING_CONFIG_CACHE, LINEAS_CREDITO_CACHE

    # Obtener línea de crédito seleccionada (si viene del formulario o URL)
    linea_seleccionada = request.args.get("linea_credito") or request.form.get(
        "linea_credito"
    )

    if not LINEAS_CREDITO_CACHE:
        config = cargar_configuracion()
        LINEAS_CREDITO_CACHE = config["LINEAS_CREDITO"]

    # Cargar configuración (global o por línea)
    SCORING_CONFIG_CACHE = cargar_configuracion_scoring(linea_seleccionada)

    # Limpiar scoring anterior al iniciar nueva evaluación
    if "ultimo_scoring" in session:
        del session["ultimo_scoring"]

    criterios = SCORING_CONFIG_CACHE.get("criterios", {})
    secciones = SCORING_CONFIG_CACHE.get("secciones", [])

    # Agrupar criterios por sección para el template
    criterios_agrupados = agrupar_criterios_por_seccion(criterios, secciones)

    # Determinar si la configuración es específica de línea
    config_es_por_linea = bool(
        linea_seleccionada and SCORING_CONFIG_CACHE.get("linea_credito_id")
    )

    return render_template(
        "scoring.html",
        scoring_criterios=criterios,
        scoring_secciones=secciones,
        scoring_criterios_agrupados=criterios_agrupados,
        scoring_json=SCORING_CONFIG_CACHE,
        lineas_credito=LINEAS_CREDITO_CACHE,
        linea_seleccionada=linea_seleccionada,
        config_es_por_linea=config_es_por_linea,
    )


# Ruta para calcular scoring con el procesamiento dinámico de criterios
@app.route("/scoring", methods=["POST"])
@no_cache_and_check_session
def calcular_scoring():
    #  Usar caché
    global LINEAS_CREDITO_CACHE, SCORING_CONFIG_CACHE

    puntaje_total = 0.0
    valores_criterios = {}
    form_values = {}
    resultados = {}
    rechazo_automatico = None
    es_aprobado = False
    nivel_riesgo = None
    tasas_diferenciadas = None

    if not session.get("autorizado"):
        return redirect(url_for("login"))

    if request.method != "POST" or not request.form:
        try:
            # Obtener línea de crédito seleccionada (si viene del formulario o URL)
            linea_seleccionada = request.args.get("linea_credito") or request.form.get(
                "linea_credito"
            )

            if not LINEAS_CREDITO_CACHE:
                config = cargar_configuracion()
                LINEAS_CREDITO_CACHE = config["LINEAS_CREDITO"]

            # Cargar configuración (global o por línea)
            SCORING_CONFIG_CACHE = cargar_configuracion_scoring(linea_seleccionada)

            criterios = SCORING_CONFIG_CACHE.get("criterios", {})
            secciones = SCORING_CONFIG_CACHE.get("secciones", [])  # 2025-12-26
            criterios_agrupados = agrupar_criterios_por_seccion(criterios, secciones)

            # Determinar si la configuración es específica de línea
            config_es_por_linea = bool(
                linea_seleccionada and SCORING_CONFIG_CACHE.get("linea_credito_id")
            )

            return render_template(
                "scoring.html",
                scoring_criterios=criterios,
                scoring_secciones=secciones,
                scoring_criterios_agrupados=criterios_agrupados,
                scoring_json=SCORING_CONFIG_CACHE,
                lineas_credito=LINEAS_CREDITO_CACHE,
                linea_seleccionada=linea_seleccionada,
                config_es_por_linea=config_es_por_linea,
            )
        except Exception as e:
            return render_template(
                "scoring.html",
                error="Error al cargar la página de scoring",
                scoring_criterios={},
                scoring_secciones=[],
                scoring_criterios_agrupados=[],
                scoring_json={},
                lineas_credito={},
            )

    try:
        # Obtener línea de crédito seleccionada (si viene del formulario)
        tipo_credito = request.form.get("tipo_credito", "LoansiFlex")

        # Cargar configuración (global o por línea)
        SCORING_CONFIG_CACHE = cargar_configuracion_scoring(tipo_credito)

        puntaje_minimo = SCORING_CONFIG_CACHE.get("puntaje_minimo_aprobacion", 20)

        if SCORING_CONFIG_CACHE.get("escala_max") != 100:
            SCORING_CONFIG_CACHE["escala_max"] = 100
            guardar_configuracion_scoring(SCORING_CONFIG_CACHE)

        criterios = SCORING_CONFIG_CACHE.get("criterios", {})

        if not criterios:
            return render_template(
                "scoring.html",
                error="No hay criterios de scoring configurados",
                scoring_criterios={},
                scoring_secciones=[],
                scoring_criterios_agrupados=[],
                scoring_json=SCORING_CONFIG_CACHE,
                lineas_credito=LINEAS_CREDITO_CACHE,
            )

        factores_rechazo = SCORING_CONFIG_CACHE.get("factores_rechazo_automatico", [])

        # ============================================================
        # FUNCIONES HELPER PARA CÁLCULO DE PUNTOS
        # (Movidas aquí para poder usarlas en pre-cálculo de score borderline)
        # ============================================================
        def obtener_puntos(criterio, valor):
            """
            Obtiene puntos de un criterio según su valor.
            Soporta criterios normales (min/max) y composite (condicion).
            """
            try:
                valor_numerico = float(valor)
                rangos = criterio.get("rangos", [])

                if not rangos:
                    return 0

                # Detectar si es criterio composite
                es_composite = criterio.get("tipo_campo") == "composite"

                if es_composite:
                    # Criterios composite: buscar por condición
                    # Por ahora, devolver puntos del primer rango
                    # (La lógica completa de composite se implementará en BLOQUE 21)
                    if rangos:
                        return rangos[0].get("puntos", 0)
                    return 0
                else:
                    # Criterios normales: buscar por min/max
                    for rango in rangos:
                        try:
                            rango_min = float(rango.get("min", 0))
                            rango_max = float(rango.get("max", 999999))
                            puntos = rango.get("puntos", 0)

                            if rango_min <= valor_numerico <= rango_max:
                                return puntos
                        except (ValueError, TypeError):
                            continue

                    return 0

            except (ValueError, TypeError):
                return 0

        def obtener_descripcion(criterio, valor):
            """
            Obtiene descripción de un criterio según su valor.
            Soporta criterios normales y composite.
            """
            try:
                valor_numerico = float(valor)
                es_composite = criterio.get("tipo_campo") == "composite"

                if es_composite:
                    # Composite: devolver primera descripción por ahora
                    rangos = criterio.get("rangos", [])
                    if rangos:
                        return rangos[0].get("descripcion", f"Valor: {valor_numerico}")
                    return f"Valor: {valor_numerico}"
                else:
                    # Normal: buscar por min/max
                    for rango in criterio.get("rangos", []):
                        rango_min = float(rango.get("min", 0))
                        rango_max = float(rango.get("max", 999999))

                        if rango_min <= valor_numerico <= rango_max:
                            return rango.get("descripcion", f"Valor: {valor_numerico}")

                    return f"Valor: {valor_numerico}"

            except (ValueError, TypeError):
                return f"Valor: {valor}"

        # tipo_credito ya se obtuvo arriba en la línea 4790
        #  VALIDACIÓN DE EDAD DEL CLIENTE - ROBUSTA
        edad_cliente = None
        edad_criterio_id = None

        # Buscar el criterio de edad por nombre (no por ID hardcoded)
        for criterio_id, criterio_config in criterios.items():
            if criterio_config.get("nombre", "").lower() in [
                "edad del cliente",
                "edad",
                "edad cliente",
            ]:
                edad_criterio_id = criterio_id
                break

        if edad_criterio_id:
            try:
                edad_cliente = int(request.form.get(edad_criterio_id, 0))
                if edad_cliente < 18 or edad_cliente > 100:
                    secciones = SCORING_CONFIG_CACHE.get("secciones", [])  # 2025-12-26
                    criterios_agrupados = agrupar_criterios_por_seccion(
                        criterios, secciones
                    )
                    return render_template(
                        "scoring.html",
                        error="Edad del cliente debe estar entre 18 y 100 años",
                        scoring_criterios=criterios,
                        scoring_secciones=secciones,
                        scoring_criterios_agrupados=criterios_agrupados,
                        scoring_json=SCORING_CONFIG_CACHE,
                        lineas_credito=LINEAS_CREDITO_CACHE,
                        form_values=form_values,
                        tipo_credito_selected=tipo_credito,
                    )
            except (ValueError, KeyError):
                pass  # Edad no es obligatoria si no existe el criterio

        nombre_cliente = (
            request.form.get("nombre_cliente", "").strip() or "Sin identificar"
        )
        # AUDITORÍA: Log de mapeo para debugging
        print("📋 AUDITORÍA DE MAPEO - Datos recibidos:")
        print(f"  - Cliente: {nombre_cliente}")
        print(f"  - Tipo crédito: {tipo_credito}")
        print(f"  - Criterios configurados: {list(criterios.keys())}")
        print(f"  - Form keys recibidas: {list(request.form.keys())}")
        print(f"🔧 DEBUG: formatear_monto disponible = {callable(formatear_monto)}")

        #  Validar que todos los criterios esperados están en el formulario
        criterios_faltantes = [
            cid for cid in criterios.keys() if cid not in request.form
        ]
        if criterios_faltantes:
            print(
                f"⚠️ ADVERTENCIA: Criterios faltantes en formulario: {criterios_faltantes}"
            )

        form_values["nombre_cliente"] = nombre_cliente

        # Preservar campos de identificación separados
        form_values["nombre_cliente_nombre"] = request.form.get(
            "nombre_cliente_nombre", ""
        ).strip()
        form_values["nombre_cliente_cedula"] = request.form.get(
            "nombre_cliente_cedula", ""
        ).strip()
        form_values["monto_solicitado"] = request.form.get(
            "monto_solicitado", ""
        ).strip()  # Preservar monto solicitado

        # Validar y parsear campos del formulario
        for criterio_id in criterios.keys():
            form_values[criterio_id] = request.form.get(criterio_id, "")

            try:
                criterio_config = criterios[criterio_id]
                tipo_campo = criterio_config.get("tipo_campo", "number")
                valor_str = request.form.get(criterio_id, "0")

                # Priorizar valor normalizado si existe
                valor_normalizado_str = request.form.get(
                    criterio_id + "_normalized", ""
                )
                if valor_normalizado_str and valor_normalizado_str.strip():
                    valor_str = valor_normalizado_str

                # PARSEO SEGÚN TIPO DE CAMPO
                if tipo_campo == "currency":
                    valor = parse_currency_value(valor_str)

                elif tipo_campo == "percentage":
                    try:
                        valor = float(valor_str.replace(",", ".")) if valor_str else 0
                        valor = max(0, valor)  # No negativos
                    except ValueError:
                        valor = 0

                elif tipo_campo == "select":
                    try:
                        valor = int(valor_str) if valor_str else 0
                        valor = max(0, valor)
                    except ValueError:
                        valor = 0

                else:  # number por defecto
                    try:
                        valor = float(valor_str.replace(",", ".")) if valor_str else 0
                        valor = max(0, valor)
                    except ValueError:
                        valor = 0

                #  VALIDACIONES ESPECÍFICAS POR CRITERIO
                if criterio_id == "puntaje_datacredito":
                    valor = max(0, min(valor, 999))

                elif criterio_id == "historial_pagos":
                    valor = max(0, min(valor, 12))

                elif criterio_id == "mora_reciente":
                    valor = max(0, valor)

            except Exception as e:
                print(f"⚠️ Error procesando criterio {criterio_id}: {str(e)}")
                valor = 0

            valores_criterios[criterio_id] = valor

        # ========================================================================
        # CAPTURAR CAMPOS CONDICIONALES (no están en criterios)
        # ========================================================================
        # Campo: Monto Mora Telcos (aparece solo si comportamiento_sectorial = 1)
        if "monto_mora_telcos" in request.form:
            form_values["monto_mora_telcos"] = request.form.get("monto_mora_telcos", "")

        # ========================================================================
        # CÁLCULOS AUTOMÁTICOS DE CRITERIOS DERIVADOS
        # ========================================================================

        # 1. % UTILIZACIÓN TARJETAS - DESHABILITADO (ahora es SELECT manual)
        pass

        # ========================================================================
        # AJUSTE AUTOMÁTICO DE MORA EN TELCOS + RECHAZO SI SUPERA UMBRAL
        # ========================================================================
        mora_dias_original = valores_criterios.get("mora_reciente", 0)
        sector_mora = valores_criterios.get("comportamiento_sectorial", 0)
        monto_mora_telcos = form_values.get("monto_mora_telcos", 0)

        # DEBUG: Imprimir valores recibidos
        print(f"🔍 MORA TELCOS - Valores recibidos:")
        print(f"   - Mora reciente: {mora_dias_original} días")
        print(f"   - Comportamiento sectorial: {sector_mora} (1=Solo Telcos)")
        print(f"   - Monto mora telcos: ${monto_mora_telcos}")

        # Convertir monto_mora_telcos a numérico
        try:
            # Formato colombiano: $210.000 (punto = miles, coma = decimal)
            # Convertir a formato Python: 210000.0
            valor_limpio = (
                str(monto_mora_telcos)
                .replace("$", "")
                .replace(".", "")
                .replace(",", ".")
                .strip()
            )
            monto_mora_telcos_num = float(valor_limpio) if valor_limpio else 0
        except (ValueError, TypeError):
            monto_mora_telcos_num = 0
            print(f"⚠️ Error convirtiendo monto_mora_telcos: {monto_mora_telcos}")

        # Guardar en valores_criterios para evaluación de rechazo automático
        valores_criterios["monto_mora_telcos"] = monto_mora_telcos_num

        # Obtener umbral de rechazo de scoring.json
        umbral_mora_telcos = SCORING_CONFIG_CACHE.get(
            "umbral_mora_telcos_rechazo", 200000
        )

        # Verificar si supera el umbral → RECHAZO AUTOMÁTICO
        rechazo_automatico = None
        if int(sector_mora) == 1 and monto_mora_telcos_num > umbral_mora_telcos:
            monto_formateado = f"${monto_mora_telcos_num:,.0f}".replace(",", ".")
            umbral_formateado = f"${umbral_mora_telcos:,.0f}".replace(",", ".")
            rechazo_automatico = f"Mora en Telcos superior al límite: {monto_formateado} (máximo permitido: {umbral_formateado})"
            print(f"🚫 RECHAZO AUTOMÁTICO: {rechazo_automatico}")

        # Si NO supera umbral: aplicar ajuste automático 50%
        elif int(sector_mora) == 1 and mora_dias_original > 0:
            mora_ajustada = mora_dias_original * 0.5
            valores_criterios["mora_reciente"] = mora_ajustada
            print(
                f"🔹 AJUSTE AUTOMÁTICO: Mora solo Telcos {mora_dias_original} días → {mora_ajustada} días (reducción 50%)"
            )
            print(
                f"   - Monto mora telcos: ${monto_mora_telcos_num:,.0f} (dentro del límite)"
            )
        elif int(sector_mora) == 1 and mora_dias_original == 0:
            print(
                f"ℹ️  Comportamiento sectorial = Telcos PERO mora = 0 días → No se aplica reducción"
            )
        elif mora_dias_original > 0:
            print(
                f"ℹ️  Mora = {mora_dias_original} días PERO comportamiento ≠ Solo Telcos (valor={sector_mora}) → No se aplica reducción"
            )

        print(
            f"🎯 DEBUG: Terminó sección mora telcos, empezando evaluación comité (DataCrédito bajo)"
        )

        # ============================================================
        # COMITÉ - CRITERIO 2: DataCrédito bajo + buen comportamiento
        # (Se evalúa ANTES de rechazos automáticos para evitar rechazo)
        # ============================================================
        config = cargar_configuracion()
        comite_config = config.get("COMITE_CREDITO", {})

        requiere_comite = False
        razon_comite = None

        # Solo evaluar para comité si NO hay rechazo automático previo (mora telcos crítico)
        if not rechazo_automatico:
            datacredito_max = float(comite_config.get("datacredito_maximo", 450))

            # Obtener valores de criterios
            puntaje_datacredito = valores_criterios.get("puntaje_datacredito", 0)

            # Criterio 2: DataCrédito bajo (<450) pero buen comportamiento interno
            # EVALUAR PRIMERO para evitar rechazo automático por DataCrédito < 450
            if (
                puntaje_datacredito > 0
                and puntaje_datacredito < datacredito_max
                and comite_config.get("evaluar_comportamiento_interno", True)
            ):
                criterios_comport = comite_config.get("criterios_comportamiento", {})

                cupo_total = float(valores_criterios.get("cupo_total_aprobado", 0))
                historial_pagos = float(valores_criterios.get("historial_pagos", 0))
                mora_reciente = float(valores_criterios.get("mora_reciente", 999))
                creditos_vigentes = float(
                    valores_criterios.get("creditos_vigentes_activos", 0)
                )

                print(
                    f"🔍 COMITÉ - Evaluando DataCrédito bajo ({int(puntaje_datacredito)}):"
                )
                print(
                    f"   - Cupo total: ${cupo_total:,.0f} (mínimo: ${criterios_comport.get('cupo_total_minimo', 5000000):,.0f})"
                )
                print(
                    f"   - Historial pagos: {historial_pagos} meses (mínimo: {criterios_comport.get('historial_pagos_minimo', 10)})"
                )
                print(
                    f"   - Mora reciente: {mora_reciente} días (máximo: {criterios_comport.get('mora_reciente_maxima', 0)})"
                )
                print(
                    f"   - Créditos vigentes: {int(creditos_vigentes)} (mínimo: {criterios_comport.get('creditos_vigentes_minimos', 2)})"
                )

                # Verificar si cumple criterios de comportamiento interno
                cumple_comportamiento = (
                    cupo_total >= criterios_comport.get("cupo_total_minimo", 5000000)
                    and historial_pagos
                    >= criterios_comport.get("historial_pagos_minimo", 10)
                    and mora_reciente
                    <= criterios_comport.get("mora_reciente_maxima", 0)
                    and creditos_vigentes
                    >= criterios_comport.get("creditos_vigentes_minimos", 2)
                )

                if cumple_comportamiento:
                    requiere_comite = True
                    razon_comite = f"DataCrédito bajo ({int(puntaje_datacredito)}) con excelente comportamiento interno"
                    print(f"🟡 CASO REQUIERE COMITÉ: {razon_comite}")
                else:
                    print(
                        f"❌ No cumple criterios de comportamiento interno → Se aplicará rechazo automático"
                    )

        # ============================================================
        # COMITÉ - CRITERIO 1: PRE-CÁLCULO Score Borderline
        # CRÍTICO: Calcular AQUÍ para saber si score estará en rango borderline
        # ANTES de ejecutar factores de rechazo automático
        # ============================================================
        if not requiere_comite and not rechazo_automatico:
            print(f"🎯 PRE-CÁLCULO BORDERLINE: Iniciando cálculo preliminar de score")

            try:
                # Calcular puntaje preliminar usando las funciones helper
                puntaje_preliminar = 0.0

                for criterio_id, valor in valores_criterios.items():
                    if criterio_id in criterios:
                        criterio = criterios[criterio_id]
                        puntos = obtener_puntos(criterio, valor)
                        peso_decimal = criterio["peso"] / 100
                        puntaje_preliminar += puntos * peso_decimal

                print(
                    f"🎯 PRE-CÁLCULO BORDERLINE: puntaje_preliminar = {round(puntaje_preliminar, 2)}"
                )

                # Verificar si está en rango borderline
                config = cargar_configuracion()
                comite_config = config.get("COMITE_CREDITO", {})
                score_min_comite = comite_config.get("score_minimo", 15)
                score_max_comite = comite_config.get("score_maximo", 17)

                print(
                    f"🎯 PRE-CÁLCULO BORDERLINE: Rango configurado = {score_min_comite} - {score_max_comite}"
                )

                if score_min_comite <= puntaje_preliminar <= score_max_comite:
                    requiere_comite = True
                    razon_comite = (
                        f"Score borderline ({round(puntaje_preliminar, 1)} puntos)"
                    )
                    print(
                        f"🟡 CASO REQUIERE COMITÉ (PRE-CÁLCULO BORDERLINE): {razon_comite}"
                    )
                else:
                    print(
                        f"🎯 PRE-CÁLCULO BORDERLINE: Score {round(puntaje_preliminar, 2)} fuera de rango [{score_min_comite}, {score_max_comite}]"
                    )
                    print(
                        f"🎯 PRE-CÁLCULO BORDERLINE: Continuar con factores de rechazo automático"
                    )

            except Exception as e:
                print(f"⚠️ ERROR en pre-cálculo borderline: {str(e)}")
                print(f"⚠️ Continuando con flujo normal (sin afectar evaluación)")
                # Si falla el pre-cálculo, continuar con flujo normal

        # ============================================================
        # FACTORES DE RECHAZO AUTOMÁTICO (solo si NO va a comité)
        # ============================================================
        print(
            f"🎯 DEBUG: Terminó evaluación DataCrédito comité, empezando factores rechazo"
        )

        if not requiere_comite and factores_rechazo:
            for factor in factores_rechazo:
                criterio_config = factor.get("criterio", "")

                # SALTAR evaluación de mora telcos (ya se maneja arriba con código personalizado)
                if criterio_config == "monto_mora_telcos":
                    continue

                operador = factor.get("operador", ">=")
                valor_limite = factor.get("valor_limite", factor.get("valor_minimo", 0))
                mensaje_template = factor.get(
                    "mensaje", f"Factor de rechazo: {criterio_config}"
                )

                if criterio_config in valores_criterios:
                    valor_actual = valores_criterios[criterio_config]
                    criterio_nombre = criterios.get(criterio_config, {}).get(
                        "nombre", criterio_config
                    )

                    try:
                        valor_actual_num = float(valor_actual)
                        valor_limite_num = float(valor_limite)

                        rechazar = False
                        if operador == "<":
                            rechazar = valor_actual_num < valor_limite_num
                        elif operador == "<=":
                            rechazar = valor_actual_num <= valor_limite_num
                        elif operador == ">":
                            rechazar = valor_actual_num > valor_limite_num
                        elif operador == ">=":
                            rechazar = valor_actual_num >= valor_limite_num

                        # Excepción para créditos cerrados = 0
                        if rechazar and criterio_config == "creditos_cerrados_exitosos":
                            # Obtener otros indicadores de comportamiento crediticio
                            cupo_total = float(
                                valores_criterios.get("cupo_total_aprobado", 0)
                            )
                            historial_pagos = float(
                                valores_criterios.get("historial_pagos", 0)
                            )
                            mora_reciente = float(
                                valores_criterios.get("mora_reciente", 0)
                            )

                            # CASO ESPECIAL: Sin créditos cerrados PERO buen comportamiento en vigentes
                            if (
                                valor_actual_num == 0
                                and cupo_total > 0
                                and historial_pagos >= 10
                                and mora_reciente == 0
                            ):
                                # NO rechazar automáticamente
                                rechazar = False
                                print(
                                    f"⚠️ EXCEPCIÓN APLICADA: Cliente sin créditos cerrados pero con buen comportamiento"
                                )
                                print(f"   - Créditos vigentes: ${cupo_total:,.0f}")
                                print(
                                    f"   - Historial pagos: {historial_pagos} meses normales"
                                )
                                print(f"   - Mora reciente: {mora_reciente} días")

                        if rechazar:
                            rechazo_automatico = mensaje_template.replace(
                                "{valor_actual}", str(valor_actual_num)
                            )
                            break

                    except (ValueError, TypeError) as e:
                        continue
                else:
                    continue

        # (Funciones obtener_puntos y obtener_descripcion ya definidas al principio)

        puntaje_total = 0.0

        for criterio_id, valor in valores_criterios.items():
            if criterio_id in criterios:
                criterio = criterios[criterio_id]

                puntos = obtener_puntos(criterio, valor)

                peso_decimal = criterio["peso"] / 100
                puntaje_ponderado = puntos * peso_decimal
                puntaje_total += puntaje_ponderado

                # FORMATEO AUTOMÁTICO POR tipo_campo DEL ADMIN
                tipo_campo = criterio.get("tipo_campo", "number")
                valor_mostrar = valor

                if tipo_campo == "currency":
                    # Campos monetarios
                    valor_mostrar = formatear_monto(valor)

                elif tipo_campo == "percentage":
                    # Porcentajes
                    valor_mostrar = f"{valor}%"

                elif tipo_campo == "select":
                    # Selects: buscar texto de la opción
                    opciones = criterio.get("opciones", [])
                    valor_int = int(valor) if valor else 0

                    # Buscar la opción comparando con INT y STRING (porque scoring.json tiene ambos)
                    for opcion in opciones:
                        opcion_valor = opcion.get("valor")
                        # Convertir a int si es string numérico
                        try:
                            opcion_valor_int = (
                                int(opcion_valor)
                                if isinstance(opcion_valor, str)
                                else opcion_valor
                            )
                        except (ValueError, TypeError):
                            opcion_valor_int = opcion_valor

                        # Comparar
                        if (
                            opcion_valor == valor_int
                            or opcion_valor_int == valor_int
                            or str(opcion_valor) == str(valor_int)
                        ):
                            valor_mostrar = opcion.get("texto", str(valor_int))
                            break
                    else:
                        valor_mostrar = str(valor_int)

                elif tipo_campo == "composite":
                    # Composite: mostrar "Evaluado automáticamente"
                    valor_mostrar = "Evaluado automáticamente"

                else:
                    # Number por defecto
                    # Formatear con separador de miles si es entero grande
                    try:
                        if valor >= 1000:
                            valor_mostrar = f"{int(valor):,}".replace(",", ".")
                        else:
                            valor_mostrar = (
                                str(int(valor))
                                if valor == int(valor)
                                else f"{valor:.1f}"
                            )
                    except:
                        valor_mostrar = str(valor)

                # Calcular puntos máximos y mínimos ponderados para este criterio
                rangos = criterio.get("rangos", [])
                if rangos:
                    max_puntos_for_criterion = max([r.get("puntos", 0) for r in rangos])
                    min_puntos_for_criterion = min([r.get("puntos", 0) for r in rangos])
                else:
                    max_puntos_for_criterion = 0
                    min_puntos_for_criterion = 0

                puntos_maximos_ponderados = (
                    criterio["peso"] / 100
                ) * max_puntos_for_criterion
                puntos_minimos_ponderados = (
                    criterio["peso"] / 100
                ) * min_puntos_for_criterion

                resultados[criterio_id] = {
                    "nombre": criterio.get("nombre", criterio_id),
                    "peso": criterio["peso"],
                    "valor": valor_mostrar,
                    "descripcion": obtener_descripcion(criterio, valor),
                    "puntos_originales": puntos,
                    "puntos_ponderados": round(puntaje_ponderado, 1),
                    "puntos_maximos": round(puntos_maximos_ponderados, 1),
                    "puntos_minimos": round(puntos_minimos_ponderados, 1),
                }

        max_puntuacion_posible = 0
        for criterio_id, criterio in criterios.items():
            max_puntos = 0
            for rango in criterio.get("rangos", []):
                if rango.get("puntos", 0) > max_puntos:
                    max_puntos = rango.get("puntos", 0)
            max_puntuacion_posible += max_puntos * (criterio["peso"] / 100)

        if max_puntuacion_posible > 0:
            puntaje_escala_100 = (puntaje_total / max_puntuacion_posible) * 100
        else:
            puntaje_escala_100 = (
                puntaje_total / SCORING_CONFIG_CACHE.get("escala_max", 100)
            ) * 100

        if puntaje_escala_100 > 100:
            puntaje_escala_100 = 100

        niveles_riesgo = SCORING_CONFIG_CACHE.get("niveles_riesgo", [])

        for nivel in niveles_riesgo:
            if nivel["min"] <= puntaje_escala_100 <= nivel["max"]:
                nivel_riesgo = nivel
                break

        if nivel_riesgo is None and niveles_riesgo:
            nivel_riesgo = niveles_riesgo[0]

        # LÓGICA DE DEGRADACIÓN: Mora en sector Telcos
        nivel_original = None
        nota_degradacion = None

        # Verificar si seleccionó "Moras solo en Telcos" en comportamiento sectorial
        comportamiento_sectorial = form_values.get("comportamiento_sectorial")

        if comportamiento_sectorial == "1":  # 1 = "Moras solo en Telcos"
            # Degradar CUALQUIER nivel a "Alto riesgo" si hay mora en telcos
            if nivel_riesgo and nivel_riesgo.get("nombre") != "Alto riesgo":
                nivel_original = nivel_riesgo["nombre"]  # Guardar nivel original

                # Buscar el nivel "Alto riesgo" para degradar
                for nivel in niveles_riesgo:
                    if nivel.get("nombre") == "Alto riesgo":
                        nivel_riesgo = nivel  # Degradar a alto riesgo
                        nota_degradacion = f"Nivel ajustado por mora en Telcos: Alto riesgo (originalmente {nivel_original})"
                        print(
                            f"🔻 DEGRADACIÓN APLICADA: {nivel_original} → Alto riesgo (mora en sector Telcos)"
                        )
                        break

        text_color = "#000000"
        if nivel_riesgo and nivel_riesgo["color"].lower() in [
            "#ff4136",
            "#ff0000",
            "#990000",
        ]:
            text_color = "#FFFFFF"

        # 🔍 LÓGICA COMITÉ DE CRÉDITO - CRITERIO 1: Score Borderline (15-17)
        # IMPORTANTE: Evaluar ANTES de verificar puntaje mínimo para evitar rechazo automático de casos borderline

        # Inicializar estado de comité (SIEMPRE, antes del if)
        origen_evaluacion = "Automático"
        estado_comite = None

        if not requiere_comite:
            config = cargar_configuracion()
            comite_config = config.get("COMITE_CREDITO", {})

            razon_comite = None

            # Solo evaluar para comité si NO hay rechazo automático previo (mora telcos, etc)
            if not rechazo_automatico:
                score_min_comite = comite_config.get("score_minimo", 15)
                score_max_comite = comite_config.get("score_maximo", 17)

                # Criterio 1: Score borderline (15-17)
                if score_min_comite <= puntaje_total <= score_max_comite:
                    requiere_comite = True
                    razon_comite = (
                        f"Score borderline ({round(puntaje_total, 1)} puntos)"
                    )
                    print(f"🟡 CASO REQUIERE COMITÉ: {razon_comite}")

        # Verificar puntaje mínimo SOLO si NO requiere comité
        if not requiere_comite:
            es_aprobado = float(puntaje_total) >= float(puntaje_minimo)

            if not es_aprobado and not rechazo_automatico:
                rechazo_automatico = f"Puntaje total insuficiente (obtenido: {round(puntaje_total, 1)}, requerido: {puntaje_minimo})"
        else:
            # Si requiere comité, NO aplica rechazo por puntaje
            es_aprobado = True  # Se mantiene como aprobado temporalmente para que llegue al comité
            print(f"ℹ️ Caso borderline: NO se aplica rechazo por puntaje insuficiente")

        if rechazo_automatico:
            es_aprobado = False

        # Establecer estado de comité si fue marcado
        if requiere_comite:
            origen_evaluacion = "Comité"
            estado_comite = "pending"

        tasas_diferenciadas = None
        aval_dinamico = None
        if (
            nivel_riesgo
            and "tasas_por_producto" in nivel_riesgo
            and tipo_credito in nivel_riesgo["tasas_por_producto"]
        ):
            tasas_diferenciadas = nivel_riesgo["tasas_por_producto"][tipo_credito]

            if (
                "aval_por_producto" in nivel_riesgo
                and tipo_credito in nivel_riesgo["aval_por_producto"]
            ):
                aval_dinamico = {
                    "porcentaje": nivel_riesgo["aval_por_producto"][tipo_credito],
                    "porcentaje_mostrar": nivel_riesgo["aval_por_producto"][
                        tipo_credito
                    ]
                    * 100,
                }

        scoring_result = {
            "score": round(puntaje_total, 1),
            "score_normalizado": round(puntaje_escala_100, 1),
            "level": nivel_riesgo["nombre"] if nivel_riesgo else "No definido",
            "nivel_original": nivel_original,  # ✅ Nivel antes de degradación (si aplica)
            "nota_degradacion": nota_degradacion,  # ✅ Nota de degradación (si aplica)
            "color": nivel_riesgo["color"] if nivel_riesgo else "#CCCCCC",
            "text_color": text_color,
            "aprobado": es_aprobado,
            "detalles": list(resultados.values()),
            "puntaje_minimo": puntaje_minimo,
            "rechazo_automatico": rechazo_automatico,
            "tasas_diferenciadas": tasas_diferenciadas,
            "aval_dinamico": aval_dinamico,
            "tipo_credito": tipo_credito,
            "requiere_comite": requiere_comite,
            "razon_comite": razon_comite,
            "origen": origen_evaluacion,
            "estado_comite": estado_comite,
            "timestamp": obtener_hora_colombia().isoformat(),
        }
        # Validaciones cruzadas automáticas
        alertas_sistema = []

        # Alerta 1: Score bajo pero aprobado por criterios mínimos
        if es_aprobado and puntaje_escala_100 < 40:
            alertas_sistema.append(
                {
                    "tipo": "warning",
                    "icono": "exclamation-triangle",
                    "mensaje": "Score bajo aprobado por criterios mínimos. Verificar capacidad de pago detalladamente.",
                }
            )

        # Alerta 2: Score alto pero con factores de riesgo detectados
        if es_aprobado and puntaje_escala_100 > 70:
            for criterio_id, resultado in resultados.items():
                if resultado["puntos_ponderados"] < 0:
                    alertas_sistema.append(
                        {
                            "tipo": "info",
                            "icono": "info-circle",
                            "mensaje": f'Aunque aprobado, se detectó riesgo en: {resultado["nombre"]}',
                        }
                    )
                    break

        # Alerta 3: Rechazo por margen estrecho
        if not es_aprobado and not rechazo_automatico:
            diferencia = puntaje_minimo - puntaje_total
            if diferencia < 5:
                alertas_sistema.append(
                    {
                        "tipo": "warning",
                        "icono": "graph-down",
                        "mensaje": f"Rechazado por {round(diferencia, 1)} puntos. Evaluar documentación adicional.",
                    }
                )

        scoring_result["alertas_sistema"] = alertas_sistema

        # 🔍 DEBUG: Verificar resultado antes de renderizar
        print(f"✅ Scoring calculado exitosamente:")
        print(f"   - Score: {scoring_result['score']}")
        print(f"   - Normalizado: {scoring_result['score_normalizado']}")
        print(f"   - Nivel: {scoring_result['level']}")
        print(f"   - Aprobado: {scoring_result['aprobado']}")

        # Guardar scoring en sesión para uso posterior
        session["ultimo_scoring"] = {
            "timestamp": scoring_result[
                "timestamp"
            ],  # ← Usar el timestamp real del resultado
            "monto_solicitado": request.form.get("monto_solicitado", "")
            .replace(".", "")
            .replace(",", ""),
            "nombre_cliente": request.form.get(
                "nombre_cliente", "Sin identificar"
            ).strip()
            or "Sin identificar",
            "tipo_credito": tipo_credito,
            "linea_credito": tipo_credito,
            "nivel_riesgo": scoring_result["level"],
            "score": scoring_result["score"],
            "score_normalizado": scoring_result["score_normalizado"],
            "aprobado": scoring_result["aprobado"],
            "aval_dinamico": scoring_result.get("aval_dinamico"),
            "origen": "Scoring automático",  # ← Identificador para distinguir de casos de comité
        }

        # Registrar evaluación para auditoría - Guardar datos completos
        registrar_evaluacion_scoring(
            username=session.get("username", "unknown"),
            cliente_info=request.form.get("nombre_cliente", "Sin identificar").strip()
            or "Sin identificar",
            scoring_result=scoring_result,
            valores_criterios=valores_criterios,  # Valores ingresados por el usuario
            resultados_detalle=resultados,  # Detalle de cada criterio evaluado
            form_values=form_values,  # Todos los valores del formulario
        )

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(scoring_result)
        else:
            secciones = SCORING_CONFIG_CACHE.get("secciones", [])  # 2025-12-26
            criterios_agrupados = agrupar_criterios_por_seccion(criterios, secciones)
            return render_template(
                "scoring.html",
                scoring_criterios=criterios,
                scoring_secciones=secciones,
                scoring_criterios_agrupados=criterios_agrupados,
                scoring_result=scoring_result,
                scoring_json=SCORING_CONFIG_CACHE,
                lineas_credito=LINEAS_CREDITO_CACHE,
                form_values=form_values,
                tipo_credito_selected=tipo_credito,
            )

    except Exception as e:
        form_values = {}
        for criterio_id in request.form:
            form_values[criterio_id] = request.form.get(criterio_id, "")

        try:
            if not LINEAS_CREDITO_CACHE:
                config = cargar_configuracion()
                LINEAS_CREDITO_CACHE = config["LINEAS_CREDITO"]
        except:
            LINEAS_CREDITO_CACHE = {"LoansiFlex": {}, "Microflex": {}}

        return render_template(
            "scoring.html",
            error=f"Error: {str(e)}",
            scoring_criterios={},
            scoring_secciones=[],
            scoring_criterios_agrupados=[],
            scoring_json={},
            lineas_credito=LINEAS_CREDITO_CACHE,
            form_values=form_values,
            tipo_credito_selected=request.form.get(
                "tipo_credito",
                (
                    list(LINEAS_CREDITO_CACHE.keys())[0]
                    if LINEAS_CREDITO_CACHE
                    else "LoansiFlex"
                ),
            ),
        )


@app.route("/asesor/mis-casos-comite")
@no_cache_and_check_session
def mis_casos_comite():
    # Verificar permiso
    if not tiene_alguno_de(["com_enviar", "com_ver_propios", "com_ver_todos"]):
        flash("No tienes permiso para ver casos de comité", "warning")
        return redirigir_a_pagina_permitida()
    """
    Vista para que el asesor vea sus casos enviados a comité
    Muestra: pendientes, aprobados, rechazados con sistema de notificaciones
    """
    if not session.get("autorizado"):
        return redirect(url_for("login"))

    username = session.get("username")

    try:
        # MIGRADO A SQLite - Ya no usa evaluaciones_log.json
        evaluaciones = leer_evaluaciones_db()

        # Filtrar solo casos del asesor actual que fueron a comité
        mis_casos = []
        for ev in evaluaciones:
            # Solo casos de este asesor que requieren/requirieron comité
            if ev.get("asesor") == username and ev.get("origen") == "Comité":
                mis_casos.append(ev)

        # Ordenar: Nuevos primero, luego pendientes, luego vistos (más recientes primero)
        def ordenar_casos(caso):
            # Prioridad 1: Casos decididos no vistos (nuevos)
            if caso.get("estado_comite") in ["approved", "rejected"] and not caso.get(
                "visto_por_asesor"
            ):
                return (0, caso.get("decision_admin", {}).get("timestamp", ""))
            # Prioridad 2: Casos pendientes
            elif caso.get("estado_comite") == "pending":
                return (1, caso.get("timestamp", ""))
            # Prioridad 3: Casos vistos (más recientes primero)
            else:
                return (2, caso.get("decision_admin", {}).get("timestamp", ""))

        mis_casos.sort(key=ordenar_casos, reverse=True)

        # Calcular estadísticas
        total_casos = len(mis_casos)
        pendientes = sum(1 for c in mis_casos if c.get("estado_comite") == "pending")
        aprobados = sum(1 for c in mis_casos if c.get("estado_comite") == "approved")
        rechazados = sum(1 for c in mis_casos if c.get("estado_comite") == "rejected")
        nuevos_sin_revisar = sum(
            1
            for c in mis_casos
            if c.get("estado_comite") in ["approved", "rejected"]
            and not c.get("visto_por_asesor")
        )

        # Tasa de aprobación
        casos_decididos = aprobados + rechazados
        tasa_aprobacion = (
            (aprobados / casos_decididos * 100) if casos_decididos > 0 else 0
        )

        # Tiempo promedio de decisión (días)
        tiempos = []
        for caso in mis_casos:
            if caso.get("decision_admin") and caso.get("timestamp"):
                try:
                    fecha_envio = datetime.fromisoformat(
                        caso["timestamp"].replace("Z", "+00:00")
                    )
                    fecha_decision = datetime.fromisoformat(
                        caso["decision_admin"]["timestamp"].replace("Z", "+00:00")
                    )
                    dias = (fecha_decision - fecha_envio).total_seconds() / 86400
                    tiempos.append(dias)
                except:
                    pass

        tiempo_promedio = sum(tiempos) / len(tiempos) if tiempos else 0

        stats = {
            "total_casos": total_casos,
            "pendientes": pendientes,
            "aprobados": aprobados,
            "rechazados": rechazados,
            "nuevos_sin_revisar": nuevos_sin_revisar,
            "tasa_aprobacion": round(tasa_aprobacion, 1),
            "tiempo_promedio": round(tiempo_promedio, 1),
        }

        return render_template(
            "asesor/mis_casos_comite.html", casos=mis_casos, stats=stats
        )

    except Exception as e:
        print(f"❌ Error en mis_casos_comite: {str(e)}")
        flash(f"Error al cargar casos: {str(e)}", "danger")
        return redirect(url_for("simulador_asesor"))


@app.route("/asesor/api/casos-comite/cambios")
@no_cache_and_check_session
def verificar_cambios_casos():
    """
    FASE 3C: Endpoint para polling - verifica si hay cambios en los casos del asesor
    Retorna { casos: [...], badge_count: N }

    CORREGIDO 2025-12-18: Ahora devuelve datos completos para crear filas nuevas
    cuando el polling detecta casos que no existen en la tabla.
    """
    if not session.get("autorizado"):
        return jsonify({"error": "No autorizado"}), 401

    username = session.get("username")

    try:
        # MIGRADO A SQLite - usa leer_evaluaciones_db()
        evaluaciones = leer_evaluaciones_db()

        # Retornar lista de casos con su estado actual Y datos completos
        casos_actualizados = []
        nuevos_sin_revisar = 0

        for ev in evaluaciones:
            if ev.get("asesor") == username and ev.get("origen") == "Comité":
                # Calcular estado
                estado_comite = ev.get("estado_comite", "pending")
                visto = ev.get("visto_por_asesor", False)

                # Contar nuevos sin revisar
                if estado_comite in ["approved", "rejected"] and not visto:
                    nuevos_sin_revisar += 1

                # Determinar estado visual
                if estado_comite in ["approved", "rejected"] and not visto:
                    estado_visual = "nuevos"
                elif estado_comite == "approved":
                    estado_visual = "aprobados"
                elif estado_comite == "rejected":
                    estado_visual = "rechazados"
                else:
                    estado_visual = "pendientes"

                # Obtener admin que tomó la decisión
                decision_admin = ev.get("decision_admin", {})
                admin_nombre = (
                    decision_admin.get("admin", "-") if decision_admin else "-"
                )

                # Obtener score
                resultado = ev.get("resultado", {})
                score = (
                    resultado.get("score", "N/A")
                    if isinstance(resultado, dict)
                    else "N/A"
                )

                # CORREGIDO: Incluir TODOS los datos necesarios para crear fila nueva
                casos_actualizados.append(
                    {
                        "timestamp": ev.get("timestamp"),
                        "estado_comite": estado_comite,
                        "estado_visual": estado_visual,
                        "visto": visto,
                        # Datos adicionales para crear fila nueva en polling
                        "cliente": ev.get("cliente")
                        or ev.get("nombre_cliente")
                        or "Sin nombre",
                        "cedula": ev.get("cedula", ""),
                        "monto": ev.get("monto_solicitado", 0),
                        "score": score,
                        "admin": admin_nombre,
                        "fecha_envio": ev.get("fecha_envio_comite")
                        or ev.get("timestamp"),
                        "fecha_decision": (
                            decision_admin.get("timestamp") if decision_admin else None
                        ),
                        "nivel_riesgo": ev.get("nivel_riesgo", "N/A"),
                    }
                )

        return jsonify({"casos": casos_actualizados, "badge_count": nuevos_sin_revisar})

    except Exception as e:
        print(f"❌ Error en verificar_cambios_casos: {str(e)}")
        import traceback

        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/asesor/marcar-caso-visto/<timestamp>", methods=["POST"])
@no_cache_and_check_session
def marcar_caso_visto(timestamp):
    """
    FASE 3C: Marca un caso como visto por el asesor (quita badge NUEVO)
    """
    if not session.get("autorizado"):
        return jsonify({"error": "No autorizado"}), 403

    username = session.get("username")

    try:
        # MIGRADO A SQLite - Ya no usa evaluaciones_log.json
        evaluaciones = leer_evaluaciones_db()

        # Buscar el caso y marcarlo como visto
        caso_encontrado = None
        for ev in evaluaciones:
            if ev.get("timestamp") == timestamp and ev.get("asesor") == username:
                ev["visto_por_asesor"] = True
                ev["fecha_visto_asesor"] = obtener_hora_colombia().isoformat()
                caso_encontrado = ev
                break

        if not caso_encontrado:
            return jsonify({"error": "Caso no encontrado"}), 404

        # MIGRADO A SQLite - Guardar solo el caso modificado
        actualizar_evaluacion_db(caso_encontrado)

        # Calcular nuevo badge count
        nuevos_sin_revisar = sum(
            1
            for c in evaluaciones
            if c.get("asesor") == username
            and c.get("estado_comite") in ["approved", "rejected"]
            and not c.get("visto_por_asesor")
        )

        return jsonify({"success": True, "nuevos_sin_revisar": nuevos_sin_revisar})

    except Exception as e:
        print(f"❌ Error al marcar caso como visto: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/badge-count")
@no_cache_and_check_session
def badge_count():
    """
    FASE 3C: Devuelve el número de casos nuevos sin revisar para el badge
    """
    if not session.get("autorizado"):
        return jsonify({"count": 0})

    username = session.get("username")

    try:
        # MIGRADO A SQLite - Ya no usa evaluaciones_log.json
        evaluaciones = leer_evaluaciones_db()

        # Contar casos nuevos sin revisar
        count = sum(
            1
            for c in evaluaciones
            if c.get("asesor") == username
            and c.get("estado_comite") in ["approved", "rejected"]
            and not c.get("visto_por_asesor")
        )

        return jsonify({"count": count})

    except:
        return jsonify({"count": 0})


# Ruta para guardar configuración de scoring
@app.route("/admin/scoring/guardar", methods=["POST"])
@no_cache_and_check_session
def guardar_scoring():
    if not tiene_permiso("cfg_sco_editar"):
        return jsonify(
            {"success": False, "error": "No tienes permiso para editar scoring"}
        )

    try:
        scoring_data = request.json

        if not scoring_data:
            return jsonify({"success": False, "error": "No se recibieron datos"})

        if "criterios" not in scoring_data or "niveles_riesgo" not in scoring_data:
            return jsonify(
                {
                    "success": False,
                    "error": "Estructura de datos incompleta. Se requieren criterios y niveles de riesgo.",
                }
            )

        total_peso = sum(
            float(criterio.get("peso", 0))
            for criterio in scoring_data["criterios"].values()
        )

        # Tolerancia de 0.01% para errores de redondeo de punto flotante
        if abs(total_peso - 100.0) > 0.01:
            return jsonify(
                {
                    "success": False,
                    "error": f"❌ La suma de pesos de los criterios debe ser exactamente 100%. Actual: {total_peso:.2f}%",
                }
            )

        guardar_configuracion_scoring(scoring_data)

        return jsonify({"success": True, "redirect_url": "/admin#Scoring"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# --------------------- THEME TOGGLE SERVER-SIDE SOLUTION ---------------------


@app.route("/toggle_theme", methods=["POST"])
def toggle_theme():
    """Server-side theme toggle - bulletproof solution bypassing deployment sync issues"""
    try:
        current_theme = request.cookies.get("theme", "light")

        new_theme = "dark" if current_theme == "light" else "light"

        referrer = request.referrer or url_for("home")

        response = make_response(redirect(referrer))

        response.set_cookie("theme", new_theme, max_age=365 * 24 * 60 * 60)

        return response

    except Exception as e:
        print(f"Error in toggle_theme: {str(e)}")
        return redirect(url_for("home"))


@app.route("/admin/historial-evaluaciones")
@no_cache_and_check_session
def historial_evaluaciones():
    """Muestra el historial de evaluaciones de scoring con paginación y filtros por equipo"""

    # Validar permisos
    if not tiene_alguno_de(["sco_hist_propio", "sco_hist_equipo", "sco_hist_todos"]):
        flash("No tienes permiso para ver el historial de evaluaciones", "warning")
        return redirect(url_for("dashboard"))

    # Parámetros de paginación
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)

    if per_page not in [10, 25, 50, 100]:
        per_page = 50

    try:
        logs = leer_evaluaciones_db()

        # RBAC: propio / equipo / todos + asignaciones
        from db_helpers import resolve_visible_usernames

        username_actual = session.get("username")
        permisos_actuales = obtener_permisos_usuario_actual()

        vis = resolve_visible_usernames(
            username_actual, permisos_actuales, "evaluaciones"
        )
        if vis.get("scope") == "ninguno":
            flash("No tienes permiso para ver historial de evaluaciones", "warning")
            return redirect(url_for("dashboard"))

        logs_scope = logs
        if vis.get("scope") != "todos":
            visibles = set(vis.get("usernames_visibles", []) or [])
            # Incluir también las propias evaluaciones del usuario
            visibles.add(username_actual)
            logs_scope = [log for log in logs if log.get("asesor") in visibles]

        # Filtros (GET): asesor + fechas
        filtro_asesor = (request.args.get("asesor") or "").strip()
        filtro_desde = (request.args.get("desde") or "").strip()
        filtro_hasta = (request.args.get("hasta") or "").strip()

        # Lista de asesores disponibles para el filtro (solo los que puede ver)
        asesores_disponibles = sorted(
            {log.get("asesor") for log in logs_scope if log.get("asesor")}
        )

        logs = logs_scope
        if filtro_asesor:
            logs = [log for log in logs if log.get("asesor") == filtro_asesor]
        if filtro_desde:
            logs = [
                log for log in logs if (log.get("timestamp", "")[:10] >= filtro_desde)
            ]
        if filtro_hasta:
            logs = [
                log for log in logs if (log.get("timestamp", "")[:10] <= filtro_hasta)
            ]

        filtros = {
            "asesor": filtro_asesor,
            "desde": filtro_desde,
            "hasta": filtro_hasta,
            "resultado": request.args.get("resultado", ""),
        }

        # Calcular paginación
        total_logs = len(logs)
        total_pages = (total_logs + per_page - 1) // per_page

        if page < 1:
            page = 1
        elif page > total_pages and total_pages > 0:
            page = total_pages

        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        logs_pagina = logs[start_idx:end_idx]

        # Estadísticas
        total = len(logs)
        aprobados = sum(1 for log in logs if log.get("resultado", {}).get("aprobado"))
        rechazados = total - aprobados
        tasa_aprobacion = (aprobados / total * 100) if total > 0 else 0

        por_asesor = {}
        for log in logs:
            asesor = log.get("asesor", "desconocido")
            por_asesor[asesor] = por_asesor.get(asesor, 0) + 1

        stats = {
            "total": total,
            "aprobados": aprobados,
            "rechazados": rechazados,
            "tasa_aprobacion": round(tasa_aprobacion, 1),
            "por_asesor": por_asesor,
        }

        pagination = {
            "page": page,
            "per_page": per_page,
            "total_logs": total_logs,
            "total_pages": total_pages,
            "start_idx": start_idx + 1,
            "end_idx": min(end_idx, total_logs),
            "has_prev": page > 1,
            "has_next": page < total_pages,
        }

        # Filtrar por resultado si se especifica
        filtro_resultado = filtros.get("resultado", "")
        if filtro_resultado == "aprobado":
            logs_pagina = [
                l for l in logs_pagina if l.get("resultado", {}).get("aprobado") == True
            ]
        elif filtro_resultado == "rechazado":
            logs_pagina = [
                l
                for l in logs_pagina
                if l.get("resultado", {}).get("aprobado") == False
            ]

        # Determinar URL de volver según rol
        rol_actual = session.get("rol", "asesor")
        if rol_actual in ["admin", "admin_tecnico"]:
            url_volver = url_for("admin")
        else:
            url_volver = url_for("dashboard")

        return render_template(
            "admin/historial_evaluaciones.html",
            logs=logs_pagina,
            stats=stats,
            filtros=filtros,
            pagination=pagination,
            asesores_disponibles=asesores_disponibles,
            scope=vis.get("scope"),
            url_volver=url_volver,
        )

    except Exception as e:
        flash(f"Error al cargar historial: {str(e)}", "danger")
        return redirect(url_for("dashboard"))


# ============================================================================
# RUTA: GESTIÓN DE ASIGNACIONES DE EQUIPO
# ============================================================================


@app.route("/admin/asignaciones-equipo", methods=["GET", "POST"])
@no_cache_and_check_session
def admin_asignaciones_equipo():
    """
    Gestión de asignaciones de usuarios a supervisores/auditores/gerentes.
    Acceso por permiso (usr_permisos o usr_asignaciones_equipo).
    """
    if not tiene_alguno_de(["usr_permisos", "usr_asignaciones_equipo"]):
        flash("No tienes permiso para gestionar asignaciones de equipo", "warning")
        return redirigir_a_pagina_permitida()

    from db_helpers import (
        get_all_assignments,
        get_managers_for_assignments,
        get_members_for_assignments,
        add_assignment,
        remove_assignment_by_id,
        ensure_user_assignments_table,
    )

    # Asegurar que la tabla existe
    ensure_user_assignments_table()

    mensaje = None
    tipo_mensaje = None

    if request.method == "POST":
        accion = request.form.get("accion")

        if accion == "agregar":
            manager = request.form.get("manager_username")
            member = request.form.get("member_username")

            if manager and member:
                if add_assignment(manager, member):
                    mensaje = f"✅ Asignación creada: {member} asignado a {manager}"
                    tipo_mensaje = "success"
                else:
                    mensaje = "❌ Error al crear asignación (posible duplicado o auto-asignación)"
                    tipo_mensaje = "danger"
            else:
                mensaje = "⚠️ Debe seleccionar manager y miembro"
                tipo_mensaje = "warning"

        elif accion == "eliminar":
            assignment_id = request.form.get("assignment_id")
            if assignment_id:
                if remove_assignment_by_id(int(assignment_id)):
                    mensaje = "✅ Asignación eliminada"
                    tipo_mensaje = "success"
                else:
                    mensaje = "❌ Error al eliminar asignación"
                    tipo_mensaje = "danger"

    # Obtener datos para la vista
    assignments = get_all_assignments()
    managers = get_managers_for_assignments()
    members = get_members_for_assignments()

    # Agrupar asignaciones por manager
    assignments_by_manager = {}
    for a in assignments:
        mgr = a["manager_username"]
        if mgr not in assignments_by_manager:
            assignments_by_manager[mgr] = {
                "manager_rol": a["manager_rol"],
                "members": [],
            }
        assignments_by_manager[mgr]["members"].append(a)

    return render_template(
        "admin/asignaciones_equipo.html",
        assignments=assignments,
        assignments_by_manager=assignments_by_manager,
        managers=managers,
        members=members,
        mensaje=mensaje,
        tipo_mensaje=tipo_mensaje,
    )


@app.route("/admin/limpiar-historial", methods=["POST"])
@no_cache_and_check_session
def limpiar_historial():
    """Elimina TODOS los registros del historial de evaluaciones"""
    if not tiene_permiso("cfg_params_editar"):
        return (
            jsonify({"success": False, "error": "No tienes permiso para esta acción"}),
            403,
        )

    try:
        # MIGRADO A SQLite - Ya no usa evaluaciones_log.json

        # Logging para debug
        print(f"🗑️ Intentando limpiar historial de SQLite")

        # Crear backup de la base de datos antes de eliminar
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "loansi.db")
        if os.path.exists(db_path):
            backup_result = crear_backup_con_rotacion(db_path, prefijo="db_backup")
            print(f"📦 Backup de DB creado: {backup_result}")

        # Eliminar todos los registros de evaluaciones
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM evaluaciones")
        registros_eliminados = cursor.rowcount
        conn.commit()
        conn.close()

        print(
            f"✅ Historial limpiado exitosamente ({registros_eliminados} registros eliminados)"
        )
        flash(
            f"Historial limpiado correctamente. Se eliminaron {registros_eliminados} registros. Se creó un backup de seguridad.",
            "success",
        )
        return jsonify({"success": True, "registros_eliminados": registros_eliminados})

    except Exception as e:
        print(f"❌ Error al limpiar historial: {str(e)}")
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# =====================================================
# RUTAS COMITÉ DE CRÉDITO
# =====================================================


@app.route("/admin/comite-credito")
@no_cache_and_check_session
def comite_credito():
    """Vista principal del comité de crédito - Con sistema de permisos mejorado"""

    # VALIDACIÓN DE ACCESO: Verificar que tiene AL MENOS UN permiso de comité
    permisos_comite = [
        "com_ver_pendientes",
        "com_aprobar",
        "com_rechazar",
        "com_ver_todos",
    ]

    if not tiene_alguno_de(permisos_comite):
        flash("No tienes permiso para acceder al Comité de Crédito.", "warning")
        return redirect(url_for("dashboard"))

    # Variables de permisos para el template
    puede_ver_pendientes = tiene_permiso("com_ver_pendientes")
    puede_aprobar = tiene_permiso("com_aprobar")
    puede_rechazar = tiene_permiso("com_rechazar")
    puede_marcar_desembolso = tiene_permiso("com_marcar_desembolso")
    puede_ver_config = tiene_alguno_de(["cfg_comite_ver", "cfg_params_editar"])
    puede_editar_config = tiene_permiso("cfg_comite_editar") or tiene_permiso(
        "cfg_params_editar"
    )

    try:
        config = cargar_configuracion()
        comite_config = config.get("COMITE_CREDITO", {})

        casos_pendientes = []
        decisiones_recientes = []

        # Leer desde SQLite
        logs = leer_evaluaciones_db()

        # Filtrar casos pendientes de comité
        for log in logs:
            if log.get("estado_comite") == "pending":
                timestamp = parsear_timestamp_naive(log["timestamp"])
                tiempo_espera_horas = (
                    obtener_hora_colombia_naive() - timestamp
                ).total_seconds() / 3600

                log["tiempo_espera_horas"] = int(tiempo_espera_horas)
                log["alerta_tiempo"] = tiempo_espera_horas > comite_config.get(
                    "alertar_sin_decision_horas", 24
                )
                casos_pendientes.append(log)

        # Filtrar decisiones recientes (últimas 20)
        for log in logs:
            if log.get("estado_comite") in ["approved", "rejected"]:
                decisiones_recientes.append(log)
                if len(decisiones_recientes) >= 20:
                    break

        stats = {
            "pendientes": len(casos_pendientes),
            "decisiones_hoy": len(
                [
                    d
                    for d in decisiones_recientes
                    if d["timestamp"][:10] == datetime.now().strftime("%Y-%m-%d")
                ]
            ),
            "con_alerta": len([c for c in casos_pendientes if c.get("alerta_tiempo")]),
        }

        return render_template(
            "admin/comite_credito.html",
            casos_pendientes=casos_pendientes,
            decisiones_recientes=decisiones_recientes,
            stats=stats,
            comite_config=comite_config,
            puede_aprobar=puede_aprobar,
            puede_rechazar=puede_rechazar,
            puede_marcar_desembolso=puede_marcar_desembolso,
            puede_ver_config=puede_ver_config,
            puede_editar_config=puede_editar_config,
        )

    except Exception as e:
        flash(f"Error al cargar comité de crédito: {str(e)}", "danger")
        return redirect(url_for("dashboard"))


@app.route("/admin/comite/configuracion", methods=["POST"])
@no_cache_and_check_session
def guardar_configuracion_comite():
    """
    Guardar configuración del comité de crédito.
    Requiere permiso cfg_params_editar (admin, admin_tecnico).
    """
    # Verificar por permiso en vez de rol fijo
    if not tiene_permiso("cfg_params_editar"):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "No tienes permiso para modificar configuración del comité",
                }
            ),
            403,
        )

    try:
        # Obtener datos del formulario
        data = request.get_json()

        if not data:
            return jsonify({"success": False, "error": "No se recibieron datos"}), 400

        # Cargar configuración actual
        config = cargar_configuracion()

        # Actualizar configuración del comité
        if "COMITE_CREDITO" not in config:
            config["COMITE_CREDITO"] = {}

        # Actualizar valores básicos
        config["COMITE_CREDITO"]["score_minimo"] = float(data.get("score_minimo", 14.0))
        config["COMITE_CREDITO"]["score_maximo"] = float(data.get("score_maximo", 16.0))
        config["COMITE_CREDITO"]["datacredito_maximo"] = int(
            data.get("datacredito_maximo", 400)
        )
        config["COMITE_CREDITO"]["evaluar_comportamiento_interno"] = data.get(
            "evaluar_comportamiento_interno", False
        )

        # Actualizar criterios de comportamiento interno
        if "criterios_comportamiento" not in config["COMITE_CREDITO"]:
            config["COMITE_CREDITO"]["criterios_comportamiento"] = {}

        # Convertir cupo_total_minimo (puede venir como string con formato)
        cupo_total = data.get("cupo_total_minimo", "7000000")
        if isinstance(cupo_total, str):
            cupo_total = (
                cupo_total.replace("$", "").replace(".", "").replace(",", "").strip()
            )
        config["COMITE_CREDITO"]["criterios_comportamiento"]["cupo_total_minimo"] = int(
            cupo_total
        )

        config["COMITE_CREDITO"]["criterios_comportamiento"][
            "historial_pagos_minimo"
        ] = int(data.get("historial_pagos_minimo", 11))
        config["COMITE_CREDITO"]["criterios_comportamiento"]["mora_reciente_maxima"] = (
            int(data.get("mora_reciente_maxima", 0))
        )
        config["COMITE_CREDITO"]["criterios_comportamiento"][
            "creditos_vigentes_minimos"
        ] = int(data.get("creditos_vigentes_minimos", 2))

        # Guardar configuración
        guardar_configuracion(config)

        print(f"✅ Configuración del comité guardada exitosamente")
        print(
            f"   - Score range: {config['COMITE_CREDITO']['score_minimo']}-{config['COMITE_CREDITO']['score_maximo']}"
        )
        print(
            f"   - DataCrédito máximo: {config['COMITE_CREDITO']['datacredito_maximo']}"
        )
        print(
            f"   - Evaluar comportamiento: {config['COMITE_CREDITO']['evaluar_comportamiento_interno']}"
        )

        return jsonify(
            {"success": True, "message": "Configuración guardada exitosamente"}
        )

    except Exception as e:
        print(f"❌ Error al guardar configuración del comité: {str(e)}")
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/comite/pendientes")
@no_cache_and_check_session
def api_comite_pendientes():
    """
    API endpoint para obtener contador de casos pendientes
    Usado por JavaScript para auto-actualización cada 10 segundos
    """
    try:
        # Permitir acceso a roles con permisos de comité
        if not tiene_alguno_de(
            ["com_ver_pendientes", "com_ver_todos", "com_aprobar", "com_rechazar"]
        ):
            return jsonify({"success": False, "error": "No autorizado"}), 403

        # MIGRADO A SQLite - Ya no usa evaluaciones_log.json
        evaluaciones = leer_evaluaciones_db()

        # Calcular estadísticas
        ahora = obtener_hora_colombia_naive()
        casos_pendientes = []
        con_alerta = 0

        for eval in evaluaciones:
            if eval.get("estado_comite") == "pending":
                casos_pendientes.append(eval)

                # Verificar si tiene más de 24 horas
                fecha_eval = parsear_timestamp_naive(eval["timestamp"])
                horas_espera = (ahora - fecha_eval).total_seconds() / 3600
                if horas_espera > 24:
                    con_alerta += 1

        # Detectar si hay nuevos casos comparando con sesión
        casos_pendientes_actuales = len(casos_pendientes)
        casos_pendientes_previos = session.get("casos_pendientes_count", 0)

        hay_nuevos = casos_pendientes_actuales > casos_pendientes_previos

        # Actualizar contador en sesión
        session["casos_pendientes_count"] = casos_pendientes_actuales

        return jsonify(
            {
                "success": True,
                "pendientes": casos_pendientes_actuales,
                "con_alerta": con_alerta,
                "hay_nuevos": hay_nuevos,
            }
        )

    except Exception as e:
        print(f"❌ Error en API pendientes: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================
# Ruta para ver detalle completo de evaluación
# ============================================
@app.route("/api/detalle_evaluacion/<timestamp>")
@no_cache_and_check_session
def detalle_evaluacion(timestamp):
    from urllib.parse import unquote

    timestamp = unquote(timestamp)

    # 🔒 VALIDACIÓN DE SESIÓN OBLIGATORIA
    username = session.get("username")
    rol = session.get("rol")

    # 🔍 LOGS DE DEBUGGING
    print(f"\n{'='*80}")
    print(f"🔍 DEBUG detalle_evaluacion():")
    print(f"   📋 Timestamp solicitado: {timestamp}")
    print(f"   👤 Username en sesión: '{username}' (tipo: {type(username).__name__})")
    print(f"   🎭 Rol en sesión: '{rol}'")
    print(f"   📦 Session ID: {session.get('_id', 'N/A')}")
    print(f"   🔑 Session keys: {list(session.keys())}")

    # Validar que la sesión esté activa
    if not username or not rol:
        print(f"❌ SESIÓN INVÁLIDA: username={username}, rol={rol}")
        print(f"{'='*80}\n")
        return (
            jsonify({"error": "Sesión no válida. Por favor inicia sesión nuevamente."}),
            401,
        )

    try:
        evaluaciones = leer_evaluaciones()
        evaluacion = None

        # Buscar el caso
        for ev in evaluaciones:
            if ev.get("timestamp") == timestamp:
                evaluacion = ev
                break

        if not evaluacion:
            print(f"❌ CASO NO ENCONTRADO: {timestamp}")
            print(f"{'='*80}\n")
            return jsonify({"error": "Caso no encontrado"}), 404

        # 🔍 LOGS DE DEBUGGING DEL CASO
        asesor_del_caso = evaluacion.get("asesor", "")
        print(f"   📄 Caso encontrado:")
        print(f"      - Cliente: {evaluacion.get('cliente')}")
        print(
            f"      - Asesor del caso: '{asesor_del_caso}' (tipo: {type(asesor_del_caso).__name__})"
        )
        print(f"      - Origen: {evaluacion.get('origen')}")
        print(f"      - Estado comité: {evaluacion.get('estado_comite')}")

        # 🔒 CONTROL DE ACCESO BASADO EN PERMISOS (RBAC + asignaciones)
        permisos_actuales = obtener_permisos_usuario_actual()
        visible = resolve_visible_usernames(username, permisos_actuales, "evaluaciones")

        if visible.get("scope") == "ninguno":
            print("   ⛔ No autorizado: sin visibilidad en evaluaciones.")
            return jsonify({"error": "No autorizado para ver este caso"}), 403

        # Siempre permitir ver lo propio. Si no es lo propio, aplicar scope.
        if asesor_del_caso != username and visible.get("scope") != "todos":
            if asesor_del_caso not in visible.get("usernames_visibles", []):
                print(
                    f"   ⛔ No autorizado: '{username}' no puede ver caso de '{asesor_del_caso}'."
                )
                return jsonify({"error": "No autorizado para ver este caso"}), 403

        print(f"   ✅ Acceso autorizado para '{username}' (rol: {rol})")
        print(f"{'='*80}\n")

        # Obtener tasas diferenciadas por nivel de riesgo
        tasas_nivel = None
        color_nivel = None

        try:
            # MIGRADO A SQLite - Ya no usa scoring.json
            scoring_data = cargar_scoring_db()
            if not scoring_data:
                scoring_data = {}

            niveles_riesgo = scoring_data.get("niveles_riesgo", [])

            # Determinar qué nivel usar (ajustado o calculado)
            # CORREGIDO 2025-12-18: Proteger contra decision_admin = None
            nivel_a_buscar = None
            decision_admin = evaluacion.get("decision_admin")
            if decision_admin and isinstance(decision_admin, dict):
                nivel_a_buscar = decision_admin.get("nivel_riesgo_ajustado")

            if not nivel_a_buscar:
                nivel_a_buscar = evaluacion.get("nivel_riesgo")

            # Buscar el nivel en la configuración
            if nivel_a_buscar:
                for nivel in niveles_riesgo:
                    # Normalizar nombres para comparación
                    nombre_nivel = nivel.get("nombre", "").lower()
                    nivel_buscar_norm = nivel_a_buscar.lower()

                    # Comparación flexible
                    if (
                        nombre_nivel == nivel_buscar_norm
                        or "alto" in nombre_nivel
                        and "alto" in nivel_buscar_norm
                        or "moderado" in nombre_nivel
                        and "moderado" in nivel_buscar_norm
                        or "bajo" in nombre_nivel
                        and "bajo" in nivel_buscar_norm
                    ):

                        # Obtener línea de crédito
                        linea_credito = evaluacion.get(
                            "linea_credito"
                        ) or evaluacion.get("tipo_credito")

                        if linea_credito:
                            tasas_por_producto = nivel.get("tasas_por_producto", {})
                            tasas_nivel = tasas_por_producto.get(linea_credito)
                            color_nivel = nivel.get("color", "#999999")

                        break
        except Exception as e:
            print(f"⚠️ Error al obtener tasas: {str(e)}")
            # No bloqueamos la respuesta si falla la obtención de tasas

        # Agregar tasas a la evaluación si se encontraron
        if tasas_nivel:
            evaluacion["tasas_nivel_riesgo"] = tasas_nivel
            evaluacion["color_nivel_riesgo"] = color_nivel

        return jsonify({"success": True, "evaluacion": evaluacion})

    except Exception as e:
        print(f"   ❌ ERROR INESPERADO: {str(e)}")
        print(f"   📍 Traceback completo:")
        import traceback

        traceback.print_exc()
        print(f"{'='*80}\n")
        return jsonify({"error": str(e)}), 500


# RUTA ALIAS PARA ASESORES - DETALLE EVALUACIÓN
# ============================================
@app.route("/asesor/detalle-evaluacion/<path:timestamp>")
@no_cache_and_check_session
def detalle_evaluacion_asesor(timestamp):
    """
    Alias de detalle_evaluacion para asesores.
    Redirige a la API principal.
    """
    from urllib.parse import unquote

    timestamp = unquote(timestamp)
    # Usar la misma lógica que detalle_evaluacion
    return detalle_evaluacion(timestamp)


@app.route("/admin/comite-credito/aprobar", methods=["POST"])
@no_cache_and_check_session
def aprobar_comite():
    """Aprobar caso del comité (con modificaciones opcionales - FASE 3B)"""
    # SISTEMA DE PERMISOS: Verificar permiso de aprobación
    if not tiene_permiso("com_aprobar"):
        print("❌ aprobar_comite(): Usuario sin permiso com_aprobar")
        return (
            jsonify(
                {"success": False, "error": "No tienes permiso para aprobar casos"}
            ),
            403,
        )

        # Compatibilidad: verificación anterior comentada
        # if session.get('rol') != 'admin':
        print("❌ aprobar_comite(): Usuario no autorizado")
        return jsonify({"success": False, "error": "No autorizado"}), 403

    try:
        data = request.get_json()
        timestamp = data.get("timestamp")

        # NUEVOS CAMPOS - FASE 3B
        monto_aprobado = data.get("monto_aprobado")  # Puede ser None
        nivel_riesgo_ajustado = data.get("nivel_riesgo_ajustado")  # Puede ser None
        justificacion_modificacion = data.get(
            "justificacion_modificacion", ""
        )  # Puede ser ''

        print(f"🔍 DEBUG aprobar_comite(): Datos recibidos:")
        print(f"   - Timestamp: {timestamp}")
        print(f"   - Monto aprobado: {monto_aprobado}")
        print(f"   - Nivel riesgo ajustado: {nivel_riesgo_ajustado}")
        print(
            f"   - Justificación: {justificacion_modificacion[:50] if justificacion_modificacion else 'N/A'}..."
        )

        if not timestamp:
            print("❌ aprobar_comite(): Timestamp no proporcionado")
            return (
                jsonify({"success": False, "error": "Timestamp no proporcionado"}),
                400,
            )

        # MIGRADO A SQLite - Ya no usa evaluaciones_log.json
        try:
            evaluaciones = leer_evaluaciones_db()
            if not evaluaciones:
                print("❌ aprobar_comite(): No se pudieron cargar evaluaciones")
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "No se pudieron cargar evaluaciones",
                        }
                    ),
                    500,
                )
        except Exception as e:
            print(f"❌ aprobar_comite(): Error al cargar desde SQLite: {e}")
            return (
                jsonify({"success": False, "error": "Error al leer evaluaciones"}),
                500,
            )

        # Buscar el caso por timestamp
        caso = None
        for eval_data in evaluaciones:
            if str(eval_data.get("timestamp")) == str(timestamp):
                caso = eval_data
                break

        if not caso:
            print(f"❌ aprobar_comite(): Caso con timestamp {timestamp} no encontrado")
            return jsonify({"success": False, "error": "Caso no encontrado"}), 404

        print(
            f"✅ aprobar_comite(): Caso encontrado - Cliente: {caso.get('cliente', 'N/A')}"
        )
        print(f"   - Monto solicitado original: {caso.get('monto_solicitado', 0)}")
        print(f"   - Nivel riesgo calculado: {caso.get('nivel_riesgo', 'N/A')}")

        # VALIDACIONES DE MODIFICACIONES (FASE 3B)
        monto_solicitado_original = float(caso.get("monto_solicitado", 0))

        # Validar monto aprobado
        if monto_aprobado:
            try:
                # Limpiar formato monetario (eliminar $, puntos, comas)
                monto_aprobado_limpio = (
                    str(monto_aprobado)
                    .replace("$", "")
                    .replace(".", "")
                    .replace(",", "")
                    .replace(" ", "")
                    .strip()
                )
                monto_aprobado_float = float(monto_aprobado_limpio)

                if monto_aprobado_float <= 0:
                    print(
                        f"❌ aprobar_comite(): Monto aprobado inválido (≤0): {monto_aprobado_float}"
                    )
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "El monto aprobado debe ser mayor a cero",
                            }
                        ),
                        400,
                    )

                if monto_aprobado_float > monto_solicitado_original:
                    print(
                        f"❌ aprobar_comite(): Monto aprobado ({monto_aprobado_float}) excede solicitado ({monto_solicitado_original})"
                    )
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "El monto aprobado no puede ser mayor al solicitado",
                            }
                        ),
                        400,
                    )

                monto_aprobado = monto_aprobado_float
                print(f"✅ aprobar_comite(): Monto aprobado válido: {monto_aprobado}")

            except (ValueError, TypeError) as e:
                print(f"❌ aprobar_comite(): Error al convertir monto aprobado: {e}")
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "El monto aprobado tiene formato inválido",
                        }
                    ),
                    400,
                )
        else:
            # Si no se proporciona monto, aprobar el monto completo
            monto_aprobado = monto_solicitado_original
            print(
                f"ℹ️ aprobar_comite(): Sin modificación de monto, aprobando monto completo: {monto_aprobado}"
            )

        # Validar degradación de nivel de riesgo
        if nivel_riesgo_ajustado and nivel_riesgo_ajustado != "sin_cambio":
            nivel_calculado = caso.get("nivel_riesgo", "")

            # Normalizar niveles (convertir variantes a formato estándar)
            def normalizar_nivel(nivel):
                """Convierte cualquier formato de nivel a formato estándar"""
                nivel_lower = str(nivel).lower().strip()
                if "bajo" in nivel_lower:
                    return "Bajo riesgo"
                elif "moderado" in nivel_lower or "medio" in nivel_lower:
                    return "Riesgo moderado"
                elif "alto" in nivel_lower:
                    return "Alto riesgo"
                return nivel

            # Normalizar ambos niveles antes de comparar
            nivel_calc_normalizado = normalizar_nivel(nivel_calculado)
            nivel_ajust_normalizado = normalizar_nivel(nivel_riesgo_ajustado)

            print(f"🔍 DEBUG: Nivel calculado original: '{nivel_calculado}'")
            print(f"🔍 DEBUG: Nivel calculado normalizado: '{nivel_calc_normalizado}'")
            print(f"🔍 DEBUG: Nivel ajustado original: '{nivel_riesgo_ajustado}'")
            print(f"🔍 DEBUG: Nivel ajustado normalizado: '{nivel_ajust_normalizado}'")

            # Mapeo de niveles a números para comparar
            niveles_map = {"Bajo riesgo": 1, "Riesgo moderado": 2, "Alto riesgo": 3}

            nivel_calc_num = niveles_map.get(nivel_calc_normalizado, 0)
            nivel_ajustado_num = niveles_map.get(nivel_ajust_normalizado, 0)

            print(f"🔍 DEBUG: Nivel calculado número: {nivel_calc_num}")
            print(f"🔍 DEBUG: Nivel ajustado número: {nivel_ajustado_num}")

            if nivel_ajustado_num < nivel_calc_num:
                print(
                    f"❌ aprobar_comite(): No se puede mejorar nivel de riesgo ({nivel_calc_normalizado} → {nivel_ajust_normalizado})"
                )
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"No se puede mejorar el nivel de riesgo. Solo se permite degradar de {nivel_calc_normalizado} a un nivel más conservador.",
                        }
                    ),
                    400,
                )

            print(
                f"✅ aprobar_comite(): Degradación de riesgo válida: {nivel_calc_normalizado} → {nivel_ajust_normalizado}"
            )
            # Guardar el nivel normalizado para consistencia
            nivel_riesgo_ajustado = nivel_ajust_normalizado
        else:
            nivel_riesgo_ajustado = None
            print(f"ℹ️ aprobar_comite(): Sin modificación de nivel de riesgo")

        # =====================================================================
        # CORRECCIÓN 2025-12-18: decision_admin ahora incluye TODOS los campos
        # =====================================================================
        # Obtener tasas del nivel aplicado
        tasas_aplicadas = None
        try:
            nivel_para_tasas = nivel_riesgo_ajustado or caso.get("nivel_riesgo")
            tipo_credito = caso.get("tipo_credito", caso.get("linea_credito", ""))

            if nivel_para_tasas and tipo_credito:
                config = cargar_config_db()
                # CORREGIDO 2025-12-18: Proteger contra config = None
                if config:
                    niveles_config = config.get("NIVELES_RIESGO", [])

                    for nivel_cfg in niveles_config:
                        if (
                            nivel_cfg.get("nombre", "").lower()
                            == nivel_para_tasas.lower()
                        ):
                            tasas = nivel_cfg.get("tasas_diferenciadas", {}).get(
                                tipo_credito, {}
                            )
                            if tasas:
                                tasas_aplicadas = {
                                    "tasa_anual": tasas.get("tasa_ea"),
                                    "tasa_mensual": tasas.get("tasa_mensual"),
                                }
                                print(
                                    f"✅ Tasas obtenidas para {nivel_para_tasas}/{tipo_credito}: {tasas_aplicadas}"
                                )
                            break
        except Exception as e:
            print(f"⚠️ Error al obtener tasas: {e}")

        # Actualizar caso
        caso["decision_comite"] = "aprobado"
        caso["estado_comite"] = "approved"
        caso["fecha_decision_comite"] = datetime.now().isoformat()
        caso["visto_por_asesor"] = False
        caso["fecha_visto_asesor"] = None

        # decision_admin CON TODOS LOS CAMPOS
        caso["decision_admin"] = {
            "accion": "aprobado",
            "admin": session.get("username"),
            "timestamp": obtener_hora_colombia().isoformat(),
            "monto_aprobado": monto_aprobado,
            "nivel_riesgo_ajustado": nivel_riesgo_ajustado,
            "nivel_riesgo_modificado": nivel_riesgo_ajustado,
            "justificacion": (
                justificacion_modificacion if justificacion_modificacion else None
            ),
            "justificacion_modificacion": (
                justificacion_modificacion if justificacion_modificacion else None
            ),
            "tasas_aplicadas": tasas_aplicadas,
        }

        # TAMBIÉN guardar en columnas directas (para queries SQL más fáciles)
        caso["monto_aprobado"] = monto_aprobado
        caso["nivel_riesgo_ajustado"] = nivel_riesgo_ajustado
        caso["justificacion_modificacion"] = (
            justificacion_modificacion if justificacion_modificacion else None
        )
        caso["tasas_nivel_riesgo"] = tasas_aplicadas

        print(f"📝 aprobar_comite(): Caso actualizado:")
        print(f"   - Decision: {caso['decision_comite']}")
        print(f"   - Monto aprobado: {caso.get('monto_aprobado')}")
        print(f"   - Nivel ajustado: {caso.get('nivel_riesgo_ajustado')}")
        print(
            f"   - Justificación: {'Sí' if caso.get('justificacion_modificacion') else 'No'}"
        )

        # MIGRADO A SQLite - Guardar decisión
        try:
            actualizar_evaluacion_db(caso)
            print(
                f"✅ aprobar_comite(): Caso aprobado y guardado exitosamente en SQLite"
            )
        except Exception as e:
            print(f"❌ aprobar_comite(): Error al guardar en SQLite: {e}")
            return jsonify({"success": False, "error": "Error al guardar cambios"}), 500

        return jsonify({"success": True, "message": "Caso aprobado exitosamente"}), 200

    except Exception as e:
        print(f"❌ aprobar_comite(): Error inesperado: {str(e)}")
        import traceback

        print(
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [ERROR] {traceback.format_exc()}"
        )
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/admin/comite-credito/rechazar", methods=["POST"])
@no_cache_and_check_session
def rechazar_caso_comite():
    """Rechazar un caso del comité de crédito"""
    if not tiene_permiso("com_rechazar"):
        return (
            jsonify(
                {"success": False, "error": "No tienes permiso para rechazar casos"}
            ),
            403,
        )

    try:
        data = request.json
        timestamp = data.get("timestamp")
        motivo = data.get("motivo", "")

        if not timestamp:
            return jsonify({"success": False, "error": "Timestamp requerido"}), 400

        if not motivo:
            return jsonify({"success": False, "error": "Motivo requerido"}), 400

        # MIGRADO A SQLite - Ya no usa evaluaciones_log.json
        logs = leer_evaluaciones_db()

        # Buscar y actualizar el caso
        caso_encontrado = None
        for log in logs:
            if log["timestamp"] == timestamp:
                log["estado_comite"] = "rejected"
                log["resultado"]["aprobado"] = False
                log["decision_admin"] = {
                    "accion": "rechazado",
                    "admin": session.get("username"),
                    "timestamp": obtener_hora_colombia().isoformat(),
                    "motivo": motivo,
                }
                caso_encontrado = log
                break

        if caso_encontrado:
            # MIGRADO A SQLite - Guardar cambios
            actualizar_evaluacion_db(caso_encontrado)

            print(f"❌ Caso rechazado por comité: {timestamp}")
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": "Caso no encontrado"}), 404

    except Exception as e:
        print(f"❌ Error al rechazar caso: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/admin/actualizar_config_comite", methods=["POST"])
@no_cache_and_check_session
def actualizar_config_comite():
    """Actualizar configuración del comité de crédito"""
    print(f"📥 COMITÉ CONFIG - Inicio de actualización")
    print(
        f"📥 COMITÉ CONFIG - Usuario: {session.get('username')}, Rol: {session.get('rol')}"
    )

    if not tiene_permiso("cfg_comite_editar"):
        print(f"❌ COMITÉ CONFIG - Usuario sin permiso cfg_comite_editar")
        return (
            jsonify(
                {"success": False, "error": "No tienes permiso para configurar comité"}
            ),
            403,
        )

    try:
        data = request.json
        print(f"📥 COMITÉ CONFIG - Datos recibidos: {data}")

        # Validar datos
        score_minimo = float(data.get("score_minimo", 15))
        score_maximo = float(data.get("score_maximo", 17))
        datacredito_maximo = int(data.get("datacredito_maximo", 450))
        evaluar_comportamiento = data.get("evaluar_comportamiento_interno", True)

        print(f"📊 COMITÉ CONFIG - Valores parseados:")
        print(f"   Score: {score_minimo} - {score_maximo}")
        print(f"   DataCrédito max: {datacredito_maximo}")
        print(f"   Evaluar comportamiento: {evaluar_comportamiento}")

        # Validar rangos
        if score_minimo >= score_maximo:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Score mínimo debe ser menor que score máximo",
                    }
                ),
                400,
            )

        if datacredito_maximo < 0 or datacredito_maximo > 999:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "DataCrédito máximo debe estar entre 0 y 999",
                    }
                ),
                400,
            )

        # Cargar config actual
        config = cargar_configuracion()

        # Actualizar configuración del comité
        if "COMITE_CREDITO" not in config:
            config["COMITE_CREDITO"] = {}

        config["COMITE_CREDITO"]["score_minimo"] = score_minimo
        config["COMITE_CREDITO"]["score_maximo"] = score_maximo
        config["COMITE_CREDITO"]["datacredito_maximo"] = datacredito_maximo
        config["COMITE_CREDITO"][
            "evaluar_comportamiento_interno"
        ] = evaluar_comportamiento

        # Actualizar criterios de comportamiento si se envían
        if "criterios_comportamiento" in data:
            criterios = data["criterios_comportamiento"]
            config["COMITE_CREDITO"]["criterios_comportamiento"] = {
                "cupo_total_minimo": int(criterios.get("cupo_total_minimo", 5000000)),
                "historial_pagos_minimo": int(
                    criterios.get("historial_pagos_minimo", 10)
                ),
                "mora_reciente_maxima": int(criterios.get("mora_reciente_maxima", 0)),
                "creditos_vigentes_minimos": int(
                    criterios.get("creditos_vigentes_minimos", 2)
                ),
            }

        # Guardar configuración
        print(f"💾 COMITÉ CONFIG - Intentando guardar...")
        print(f"💾 COMITÉ CONFIG - Config a guardar: {config.get('COMITE_CREDITO')}")

        resultado_guardado = guardar_configuracion(config)

        print(f"💾 COMITÉ CONFIG - Resultado guardado: {resultado_guardado}")

        if resultado_guardado:
            print(
                f"✅ COMITÉ CONFIG - Configuración del comité actualizada exitosamente"
            )
            return jsonify({"success": True})
        else:
            print(f"❌ COMITÉ CONFIG - Error: guardar_configuracion retornó False")
            return (
                jsonify({"success": False, "error": "Error al guardar configuración"}),
                500,
            )

    except Exception as e:
        print(f"❌ COMITÉ CONFIG - Excepción: {str(e)}")
        import traceback

        print(f"❌ COMITÉ CONFIG - Traceback: {traceback.format_exc()}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/admin/actualizar-estado-desembolso", methods=["POST"])
@no_cache_and_check_session
def actualizar_estado_desembolso():
    """Actualiza el estado de desembolso de una evaluación específica"""
    # SISTEMA DE PERMISOS: Verificar permiso de marcar desembolso
    if not tiene_alguno_de(["com_marcar_desembolso", "com_aprobar"]):
        return (
            jsonify({"success": False, "error": "No tienes permiso para esta acción"}),
            403,
        )

    # Verificar propiedad del caso si no es admin/comité
    if not tiene_alguno_de(["com_aprobar", "com_ver_todos"]):
        try:
            data = request.get_json()
            timestamp = data.get("timestamp")
            caso = obtener_caso_completo(timestamp) if timestamp else None
            if caso and caso.get("asesor") != session.get("username"):
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Solo puedes modificar tus propios casos",
                        }
                    ),
                    403,
                )
        except:
            pass

        # Compatibilidad: verificación anterior comentada
        # if session.get('rol') != 'admin':
        return jsonify({"success": False, "error": "No autorizado"}), 403

    try:
        data = request.get_json()
        timestamp = data.get("timestamp")
        nuevo_estado = data.get("nuevo_estado")

        if not timestamp or not nuevo_estado:
            return jsonify({"success": False, "error": "Datos incompletos"}), 400

        # Validar estado
        estados_validos = ["Pendiente", "Desembolsado", "Rechazado"]
        if nuevo_estado not in estados_validos:
            return jsonify({"success": False, "error": "Estado inválido"}), 400

        # MIGRADO A SQLite - Ya no usa evaluaciones_log.json
        logs = leer_evaluaciones_db()

        if not logs:
            return jsonify({"success": False, "error": "No existe historial"}), 404

        # Buscar y actualizar el registro
        registro_encontrado = None
        for log in logs:
            if log.get("timestamp") == timestamp:
                log["estado_desembolso"] = nuevo_estado
                registro_encontrado = log
                break

        if not registro_encontrado:
            return jsonify({"success": False, "error": "Registro no encontrado"}), 404

        # MIGRADO A SQLite - Guardar cambios
        actualizar_evaluacion_db(registro_encontrado)

        return jsonify({"success": True, "message": "Estado actualizado correctamente"})

    except Exception as e:
        print(f"Error al actualizar estado: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================
# RUTAS: CAPACIDAD DE PAGO - API
# ============================================


@app.route("/api/capacidad-config")
@no_cache_and_check_session
def api_capacidad_config():
    """
    Retorna la configuración de capacidad de pago para el frontend.
    Requiere permiso cfg_cap_ver o cfg_params_editar.
    """
    # Validación de permisos
    if not tiene_alguno_de(
        [
            "cfg_cap_ver",
            "cfg_cap_editar",
            "cfg_params_editar",
            "admin_panel_acceso",
            "cap_usar",
        ]
    ):
        return jsonify({"error": "No tienes permiso para ver esta configuración"}), 403

    try:
        config = cargar_configuracion()
        parametros = config.get(
            "PARAMETROS_CAPACIDAD_PAGO",
            {
                "limite_conservador": 30,
                "limite_maximo": 35,
                "limite_absoluto": 40,
                "descripcion_conservador": "Recomendado para créditos de libre inversión",
                "descripcion_maximo": "Límite máximo con scoring alto",
                "descripcion_absoluto": "Solo casos excepcionales",
            },
        )
        return jsonify(parametros)
    except Exception as e:
        print(f"❌ Error al cargar parámetros de capacidad: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/admin/actualizar_umbral_mora_telcos", methods=["POST"])
@no_cache_and_check_session
def actualizar_umbral_mora_telcos():
    """
    Actualiza el umbral de mora telcos.
    """
    # Requiere cfg_comite_editar o cfg_params_editar (retrocompatibilidad)
    if not tiene_alguno_de(["cfg_comite_editar", "cfg_params_editar"]):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "No tienes permiso para modificar configuración del comité",
                }
            ),
            403,
        )

    try:
        data = request.get_json()
        nuevo_umbral = float(data.get("umbral", 200000))

        # MIGRADO A SQLite - Cargar scoring desde DB
        scoring_data = cargar_scoring_db()
        if not scoring_data:
            scoring_data = {}

        # Actualizar umbral
        scoring_data["umbral_mora_telcos_rechazo"] = nuevo_umbral

        # Guardar en SQLite
        guardar_scoring_db(scoring_data)

        # CORRECCIÓN 2025-12-23: Limpiar TODOS los cachés de scoring
        global scoring_cache, last_scoring_load_time, SCORING_CONFIG_CACHE
        scoring_cache = None
        last_scoring_load_time = 0
        SCORING_CONFIG_CACHE = None  # ← LÍNEA CRÍTICA AGREGADA

        print(f"✅ Umbral mora telcos actualizado: {nuevo_umbral}")

        return jsonify({"success": True, "nuevo_umbral": nuevo_umbral})

    except Exception as e:
        print(f"❌ Error al actualizar umbral mora telcos: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================
# MANEJADORES DE ERRORES GLOBALES
# ============================================
def handle_csrf_error(error):
    """
    Maneja específicamente errores CSRF (token inválido/expirado).
    Distingue entre rutas públicas y privadas.

    IMPORTANTE: NO limpiar sesión aquí - puede causar ciclos de redirect
    donde el usuario nunca puede hacer login.
    """
    # Log del error
    print(f"⚠️ CSRF Error en {request.path}: {error}")

    # NO llamar session.clear() - causa ciclos problemáticos
    # La sesión se regenerará naturalmente al hacer login exitoso

    # Verificar si es ruta pública ANTES de redirigir
    if es_ruta_publica():
        # RUTA PÚBLICA: NO mostrar mensaje, NO redirigir a login
        # Simplemente recargar la página pública actual
        print(
            f"ℹ️ CSRF en ruta pública {request.path}, redirigiendo a simulador público"
        )
        return redirect(url_for("home"))

    # RUTA PRIVADA: Redirigir a login con mensaje
    # Si es AJAX, devolver JSON
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return (
            jsonify(
                {
                    "error": "Sesión expirada. Por favor, inicia sesión nuevamente.",
                    "redirect": url_for("login"),
                }
            ),
            401,
        )

    # Si es navegación normal, redirigir a login con mensaje
    flash("Tu sesión ha expirado. Por favor, inicia sesión nuevamente.", "warning")
    return redirect(url_for("login"))


@app.errorhandler(400)
def bad_request_error(error):
    """
    Maneja errores 400 (Bad Request).
    Redirige según contexto: rutas públicas vs privadas.

    IMPORTANTE: NO limpiar sesión aquí - puede causar problemas de CSRF.
    """
    # NO llamar session.clear() - la sesión se regenerará en login
    # Limpiar solo si es crítico para seguridad

    # Detectar si es error CSRF
    error_message = str(error)
    is_csrf = "csrf" in error_message.lower() or "token" in error_message.lower()

    # Determinar destino según tipo de ruta
    if es_ruta_publica():
        # RUTA PÚBLICA: Redirigir al simulador público sin mensaje
        destino = url_for("index")
        if is_csrf:
            # Solo agregar flash en rutas públicas si es crítico
            pass  # No mostrar mensaje en público
        else:
            flash("Solicitud inválida. Por favor, intenta nuevamente.", "warning")
    else:
        # RUTA PRIVADA: Redirigir al login con mensaje
        destino = url_for("login")
        if is_csrf:
            flash(
                "Tu sesión ha expirado por inactividad. Por favor, inicia sesión nuevamente.",
                "warning",
            )
        else:
            flash("Solicitud inválida. Por favor, inicia sesión nuevamente.", "warning")

    # Crear respuesta con headers anti-caché
    response = make_response(redirect(destino))
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "-1"

    return response


@app.errorhandler(403)
def forbidden_error(error):
    """
    Maneja errores 403 (Forbidden), común cuando CSRF falla en validación.
    Redirige según contexto: rutas públicas vs privadas.
    """
    session.clear()

    # Determinar destino según tipo de ruta
    if es_ruta_publica():
        # RUTA PÚBLICA: Redirigir al simulador público sin mensaje
        destino = url_for("index")
    else:
        # RUTA PRIVADA: Redirigir al login con mensaje
        flash("Acceso denegado. Tu sesión puede haber expirado.", "warning")
        destino = url_for("login")

    response = make_response(redirect(destino))
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "-1"

    return response


@app.errorhandler(500)
def internal_error(error):
    """
    Maneja errores 500 (Internal Server Error).
    """
    import traceback

    print("ERROR 500:", traceback.format_exc())

    # Si hay sesión activa, intentar mantenerla
    if session.get("autorizado"):
        flash("Ocurrió un error interno. Por favor, intenta nuevamente.")
        return redirect(request.referrer or url_for("simulador_asesor"))

    flash("Ocurrió un error en el sistema. Por favor, inicia sesión.")
    return redirect(url_for("login"))


# ============================================
# FILTRO JINJA PARA FORMATEAR FECHAS
# ============================================
@app.template_filter("formatear_fecha")
def filtro_formatear_fecha(fecha_iso):
    """
    Filtro Jinja para usar en templates:
    {{ caso.timestamp | formatear_fecha }}
    Muestra: 2025-11-27 5:30 PM (hora Colombia)
    """
    return formatear_fecha_colombia(fecha_iso)


# ============================================
# RUTAS API: ESTADOS DE CRÉDITO (Desembolso/Desistido)
# Sistema de permisos granulares - 2025-12-31
# ============================================


@app.route("/api/credito/marcar-desembolsado", methods=["POST"])
@no_cache_and_check_session
def api_marcar_desembolsado():
    """Marca un crédito aprobado como desembolsado (registrado en Finsoftek)"""
    # Verificar permisos: asesor que procesó el caso, comité o admin
    if not tiene_alguno_de(["com_marcar_desembolso", "com_aprobar"]):
        return jsonify({"success": False, "error": "Sin permiso para esta acción"}), 403

    try:
        data = request.get_json()
        timestamp = data.get("timestamp")
        comentario = data.get("comentario", "")

        if not timestamp:
            return jsonify({"success": False, "error": "Timestamp requerido"}), 400

        # Verificar que el asesor solo pueda marcar sus propios casos
        if not tiene_alguno_de(["com_aprobar", "com_ver_todos"]):
            caso = obtener_caso_completo(timestamp)
            if caso and caso.get("asesor") != session.get("username"):
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Solo puedes marcar tus propios casos",
                        }
                    ),
                    403,
                )

        resultado = marcar_desembolsado(
            timestamp=timestamp,
            usuario_registrador=session.get("username"),
            comentario=comentario,
        )

        status = 200 if resultado["success"] else 400
        return jsonify(resultado), status

    except Exception as e:
        print(f"❌ Error en api_marcar_desembolsado: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/credito/marcar-desistido", methods=["POST"])
@no_cache_and_check_session
def api_marcar_desistido():
    """Marca un crédito como desistido (cliente no quiere el crédito)"""
    if not tiene_alguno_de(["com_marcar_desistido", "com_aprobar"]):
        return jsonify({"success": False, "error": "Sin permiso para esta acción"}), 403

    try:
        data = request.get_json()
        timestamp = data.get("timestamp")
        motivo = data.get("motivo", "")

        if not timestamp:
            return jsonify({"success": False, "error": "Timestamp requerido"}), 400

        # Verificar propiedad del caso si no es comité/admin
        if not tiene_alguno_de(["com_aprobar", "com_ver_todos"]):
            caso = obtener_caso_completo(timestamp)
            if caso and caso.get("asesor") != session.get("username"):
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Solo puedes marcar tus propios casos",
                        }
                    ),
                    403,
                )

        resultado = marcar_desistido(
            timestamp=timestamp,
            usuario_registrador=session.get("username"),
            motivo=motivo,
        )

        status = 200 if resultado["success"] else 400
        return jsonify(resultado), status

    except Exception as e:
        print(f"❌ Error en api_marcar_desistido: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/credito/revertir-estado", methods=["POST"])
@no_cache_and_check_session
def api_revertir_estado():
    """Revierte el estado final de un crédito (solo admin)"""
    if not tiene_alguno_de(["com_aprobar"]):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Solo administradores pueden revertir estados",
                }
            ),
            403,
        )

    try:
        data = request.get_json()
        timestamp = data.get("timestamp")
        motivo = data.get("motivo", "")

        if not timestamp:
            return jsonify({"success": False, "error": "Timestamp requerido"}), 400

        resultado = revertir_estado_final(
            timestamp=timestamp,
            usuario_registrador=session.get("username"),
            motivo=motivo,
        )

        status = 200 if resultado["success"] else 400
        return jsonify(resultado), status

    except Exception as e:
        print(f"❌ Error en api_revertir_estado: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/credito/estadisticas-estados")
@no_cache_and_check_session
def api_estadisticas_estados():
    """Obtiene estadísticas de estados de créditos"""
    if not tiene_alguno_de(
        ["rep_metricas_propio", "rep_metricas_equipo", "rep_metricas_global"]
    ):
        return jsonify({"error": "Sin permiso para ver estadísticas"}), 403

    try:
        # Si tiene permisos globales, mostrar todo
        if tiene_permiso("rep_metricas_global"):
            estadisticas = obtener_estadisticas_estados()
            return jsonify(estadisticas)
        else:
            # Solo estadísticas propias
            resumen = obtener_resumen_asesor(session.get("username"))
            return jsonify(resumen)

    except Exception as e:
        print(f"❌ Error en api_estadisticas_estados: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/credito/casos-pendientes-desembolso")
@no_cache_and_check_session
def api_casos_pendientes_desembolso():
    """Obtiene casos aprobados pendientes de desembolso"""
    if not session.get("autorizado"):
        return jsonify({"error": "No autorizado"}), 401

    try:
        filtros = {}

        # Si no tiene permiso global, solo sus casos
        if not tiene_alguno_de(["com_ver_todos", "rep_metricas_global"]):
            filtros["asesor"] = session.get("username")

        casos = obtener_casos_por_estado_final("pendiente_desembolso", filtros)

        return jsonify({"success": True, "casos": casos, "total": len(casos)})

    except Exception as e:
        print(f"❌ Error en api_casos_pendientes_desembolso: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/credito/caso-completo/<path:timestamp>")
@no_cache_and_check_session
def api_caso_completo(timestamp):
    """Obtiene datos completos de un caso incluyendo estados finales"""
    if not session.get("autorizado"):
        return jsonify({"error": "No autorizado"}), 401

    try:
        caso = obtener_caso_completo(timestamp)

        if not caso:
            return jsonify({"error": "Caso no encontrado"}), 404

        # Verificar permisos de visualización
        if not tiene_alguno_de(["com_ver_todos", "sco_hist_todos"]):
            if caso.get("asesor") != session.get("username"):
                return jsonify({"error": "Sin permiso para ver este caso"}), 403

        return jsonify({"success": True, "caso": caso})

    except Exception as e:
        print(f"❌ Error en api_caso_completo: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================
# API: USUARIOS PARA GESTIÓN DE PERMISOS
# ============================================


@app.route("/api/usuarios/lista")
@no_cache_and_check_session
def api_usuarios_lista():
    """Obtiene lista de usuarios con IDs para gestión de permisos"""
    if not tiene_alguno_de(["usr_ver", "usr_permisos"]):
        return jsonify({"error": "Sin permiso"}), 403

    try:
        from database import conectar_db

        conn = conectar_db()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, username, rol, nombre_completo, activo
            FROM usuarios
            ORDER BY username
        """
        )

        usuarios = []
        for row in cursor.fetchall():
            usuarios.append(
                {
                    "id": row[0],
                    "username": row[1],
                    "rol": row[2],
                    "nombre_completo": row[3] or row[1],
                    "activo": bool(row[4]),
                }
            )

        conn.close()
        return jsonify({"success": True, "usuarios": usuarios})

    except Exception as e:
        print(f"❌ Error en api_usuarios_lista: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/usuarios/<username>/id")
@no_cache_and_check_session
def api_obtener_id_usuario(username):
    """Obtiene el ID de un usuario por su username"""
    if not tiene_alguno_de(["usr_ver", "usr_permisos"]):
        return jsonify({"error": "Sin permiso"}), 403

    try:
        from database import conectar_db

        conn = conectar_db()
        cursor = conn.cursor()

        cursor.execute("SELECT id, rol FROM usuarios WHERE username = ?", (username,))
        row = cursor.fetchone()

        conn.close()

        if not row:
            return jsonify({"error": "Usuario no encontrado"}), 404

        return jsonify(
            {"success": True, "id": row[0], "username": username, "rol": row[1]}
        )

    except Exception as e:
        print(f"❌ Error en api_obtener_id_usuario: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================
# RUTAS DE DEBUG
# ============================================


@app.route("/debug/session")
@no_cache_and_check_session
def debug_session():
    """Endpoint temporal para debugging de sesión"""
    if not tiene_permiso("aud_ver_todos"):
        return jsonify({"error": "No autorizado"}), 403

    return jsonify(
        {
            "session_keys": list(session.keys()),
            "username": session.get("username"),
            "rol": session.get("rol"),
            "session_id": session.get("_id", "N/A"),
            "permanent": session.permanent,
            "all_session": dict(session),
        }
    )


@app.route("/api/db_diagnostics", methods=["GET"])
@no_cache_and_check_session
def api_db_diagnostics():
    """
    Endpoint de diagnóstico para verificar estado de SQLite.
    Solo accesible por admin.

    ÚTIL PARA DEBUGGING EN PRODUCCIÓN
    """
    if not tiene_permiso("aud_ver_todos"):
        return jsonify({"error": "No autorizado"}), 403

    try:
        from database import (
            conectar_db,
            contar_registros_tabla,
            verificar_integridad_db,
            DB_PATH,
        )

        conn = conectar_db()

        diagnostico = {
            "timestamp": datetime.now().isoformat(),
            "db_file": str(DB_PATH),
            "integridad": "OK" if verificar_integridad_db() else "ERROR",
            "tablas": {
                "usuarios": contar_registros_tabla("usuarios"),
                "lineas_credito": contar_registros_tabla("lineas_credito"),
                "evaluaciones": contar_registros_tabla("evaluaciones"),
                "simulaciones": contar_registros_tabla("simulaciones"),
                "costos_asociados": contar_registros_tabla("costos_asociados"),
            },
            "cache_config": config_cache is not None,
            "cache_scoring": scoring_cache is not None,
            "sqlite_debug": SQLITE_DEBUG,
        }

        conn.close()

        return jsonify(diagnostico), 200

    except Exception as e:
        logger.error(f"Error en diagnóstico DB: {e}")
        return jsonify({"error": str(e), "timestamp": datetime.now().isoformat()}), 500


# -----------------------------------------------------------
# API: Obtener líneas de crédito con info de scoring
# -----------------------------------------------------------
@app.route("/api/scoring/lineas-credito", methods=["GET"])
@no_cache_and_check_session
@requiere_permiso("cfg_sco_ver")
def api_scoring_lineas_credito():
    """Obtiene todas las líneas de crédito con información de scoring."""
    try:
        lineas = obtener_lineas_credito_scoring()
        return jsonify({"success": True, "lineas": lineas})
    except Exception as e:
        logger.error(f"Error obteniendo líneas de crédito: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# -----------------------------------------------------------
# API: Obtener configuración de scoring para una línea
# -----------------------------------------------------------
@app.route("/api/scoring/linea/<int:linea_id>/config", methods=["GET"])
@no_cache_and_check_session
@requiere_permiso("cfg_sco_ver")
def api_scoring_get_config_linea(linea_id):
    """Obtiene la configuración completa de scoring para una línea."""
    try:
        config = obtener_config_scoring_linea(linea_id)

        if not config:
            return (
                jsonify({"success": False, "error": f"Línea {linea_id} no encontrada"}),
                404,
            )

        return jsonify({"success": True, "config": config})
    except Exception as e:
        logger.error(f"Error obteniendo config scoring línea {linea_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# -----------------------------------------------------------
# API: Guardar configuración general de scoring para una línea
# -----------------------------------------------------------
@app.route("/api/scoring/linea/<int:linea_id>/config", methods=["POST"])
@no_cache_and_check_session
@requiere_permiso("cfg_sco_editar")
def api_scoring_save_config_linea(linea_id):
    """Guarda la configuración de scoring para una línea."""
    try:
        # Validar CSRF
        csrf_token = request.headers.get("X-CSRFToken") or request.form.get(
            "csrf_token"
        )
        if not csrf_token:
            return jsonify({"success": False, "error": "Token CSRF requerido"}), 403

        data = request.get_json()

        if not data:
            return jsonify({"success": False, "error": "No se recibieron datos"}), 400

        resultado = guardar_config_scoring_linea(linea_id, data)

        if resultado:
            # Registrar en auditoría
            registrar_auditoria(
                session.get("username", "sistema"),
                "SCORING_CONFIG_LINEA_UPDATE",
                f"Configuración de scoring actualizada para línea {linea_id}",
                detalles=json.dumps({"linea_id": linea_id}),
            )

            return jsonify(
                {"success": True, "message": "Configuración guardada exitosamente"}
            )
        else:
            return (
                jsonify({"success": False, "error": "Error al guardar configuración"}),
                500,
            )

    except Exception as e:
        logger.error(f"Error guardando config scoring línea {linea_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# -----------------------------------------------------------
# API: Obtener niveles de riesgo de una línea
# -----------------------------------------------------------
@app.route("/api/scoring/linea/<int:linea_id>/niveles-riesgo", methods=["GET"])
@no_cache_and_check_session
@requiere_permiso("cfg_sco_ver")
def api_scoring_get_niveles_riesgo(linea_id):
    """Obtiene los niveles de riesgo para una línea."""
    try:
        niveles = obtener_niveles_riesgo_linea(linea_id)
        return jsonify({"success": True, "niveles": niveles})
    except Exception as e:
        logger.error(f"Error obteniendo niveles de riesgo: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# -----------------------------------------------------------
# API: Guardar niveles de riesgo de una línea
# -----------------------------------------------------------
@app.route("/api/scoring/linea/<int:linea_id>/niveles-riesgo", methods=["POST"])
@no_cache_and_check_session
@requiere_permiso("cfg_sco_editar")
def api_scoring_save_niveles_riesgo(linea_id):
    """Guarda los niveles de riesgo para una línea."""
    try:
        # Validar CSRF
        csrf_token = request.headers.get("X-CSRFToken") or request.form.get(
            "csrf_token"
        )
        if not csrf_token:
            return jsonify({"success": False, "error": "Token CSRF requerido"}), 403

        data = request.get_json()
        niveles = data.get("niveles", [])

        if not niveles:
            return (
                jsonify(
                    {"success": False, "error": "No se recibieron niveles de riesgo"}
                ),
                400,
            )

        resultado = guardar_niveles_riesgo_linea(linea_id, niveles)

        if resultado:
            registrar_auditoria(
                session.get("username", "sistema"),
                "SCORING_NIVELES_RIESGO_UPDATE",
                f"Niveles de riesgo actualizados para línea {linea_id}",
                detalles=json.dumps(
                    {"linea_id": linea_id, "num_niveles": len(niveles)}
                ),
            )

            return jsonify(
                {
                    "success": True,
                    "message": f"{len(niveles)} niveles de riesgo guardados",
                }
            )
        else:
            return (
                jsonify(
                    {"success": False, "error": "Error al guardar niveles de riesgo"}
                ),
                500,
            )

    except Exception as e:
        logger.error(f"Error guardando niveles de riesgo: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# -----------------------------------------------------------
# API: Obtener factores de rechazo de una línea
# -----------------------------------------------------------
@app.route("/api/scoring/linea/<int:linea_id>/factores-rechazo", methods=["GET"])
@no_cache_and_check_session
@requiere_permiso("cfg_sco_ver")
def api_scoring_get_factores_rechazo(linea_id):
    """Obtiene los factores de rechazo para una línea."""
    try:
        factores = obtener_factores_rechazo_linea(linea_id)
        return jsonify({"success": True, "factores": factores})
    except Exception as e:
        logger.error(f"Error obteniendo factores de rechazo: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# -----------------------------------------------------------
# API: Guardar factores de rechazo de una línea
# -----------------------------------------------------------
@app.route("/api/scoring/linea/<int:linea_id>/factores-rechazo", methods=["POST"])
@no_cache_and_check_session
@requiere_permiso("cfg_sco_editar")
def api_scoring_save_factores_rechazo(linea_id):
    """Guarda los factores de rechazo para una línea."""
    try:
        # Validar CSRF
        csrf_token = request.headers.get("X-CSRFToken") or request.form.get(
            "csrf_token"
        )
        if not csrf_token:
            return jsonify({"success": False, "error": "Token CSRF requerido"}), 403

        data = request.get_json()
        factores = data.get("factores", [])

        resultado = guardar_factores_rechazo_linea(linea_id, factores)

        if resultado:
            registrar_auditoria(
                session.get("username", "sistema"),
                "SCORING_FACTORES_RECHAZO_UPDATE",
                f"Factores de rechazo actualizados para línea {linea_id}",
                detalles=json.dumps(
                    {"linea_id": linea_id, "num_factores": len(factores)}
                ),
            )

            return jsonify(
                {
                    "success": True,
                    "message": f"{len(factores)} factores de rechazo guardados",
                }
            )
        else:
            return (
                jsonify(
                    {"success": False, "error": "Error al guardar factores de rechazo"}
                ),
                500,
            )

    except Exception as e:
        logger.error(f"Error guardando factores de rechazo: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# -----------------------------------------------------------
# API: Agregar un factor de rechazo
# -----------------------------------------------------------
@app.route(
    "/api/scoring/linea/<int:linea_id>/factores-rechazo/agregar", methods=["POST"]
)
@no_cache_and_check_session
@requiere_permiso("cfg_sco_editar")
def api_scoring_agregar_factor_rechazo(linea_id):
    """Agrega un nuevo factor de rechazo a una línea."""
    try:
        # Validar CSRF
        csrf_token = request.headers.get("X-CSRFToken") or request.form.get(
            "csrf_token"
        )
        if not csrf_token:
            return jsonify({"success": False, "error": "Token CSRF requerido"}), 403

        data = request.get_json()

        factor_id = agregar_factor_rechazo_linea(linea_id, data)

        if factor_id:
            return jsonify(
                {
                    "success": True,
                    "factor_id": factor_id,
                    "message": "Factor de rechazo agregado",
                }
            )
        else:
            return (
                jsonify(
                    {"success": False, "error": "Error al agregar factor de rechazo"}
                ),
                500,
            )

    except Exception as e:
        logger.error(f"Error agregando factor de rechazo: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# -----------------------------------------------------------
# API: Eliminar un factor de rechazo
# -----------------------------------------------------------
@app.route("/api/scoring/factores-rechazo/<int:factor_id>", methods=["DELETE"])
@no_cache_and_check_session
@requiere_permiso("cfg_sco_editar")
def api_scoring_eliminar_factor_rechazo(factor_id):
    """Elimina un factor de rechazo."""
    try:
        # Validar CSRF
        csrf_token = request.headers.get("X-CSRFToken") or request.form.get(
            "csrf_token"
        )
        if not csrf_token:
            return jsonify({"success": False, "error": "Token CSRF requerido"}), 403

        resultado = eliminar_factor_rechazo(factor_id)

        if resultado:
            return jsonify({"success": True, "message": "Factor de rechazo eliminado"})
        else:
            return jsonify({"success": False, "error": "Factor no encontrado"}), 404

    except Exception as e:
        logger.error(f"Error eliminando factor de rechazo: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# -----------------------------------------------------------
# API: Obtener criterios de una línea
# -----------------------------------------------------------
@app.route("/api/scoring/linea/<int:linea_id>/criterios", methods=["GET"])
@no_cache_and_check_session
@requiere_permiso("cfg_sco_ver")
def api_scoring_get_criterios_linea(linea_id):
    """Obtiene los criterios configurados para una línea."""
    try:
        criterios = obtener_criterios_linea(linea_id)
        return jsonify({"success": True, "criterios": criterios})
    except Exception as e:
        logger.error(f"Error obteniendo criterios: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# -----------------------------------------------------------
# API: Guardar un criterio de una línea
# -----------------------------------------------------------
@app.route(
    "/api/scoring/linea/<int:linea_id>/criterios/<string:criterio_codigo>",
    methods=["POST"],
)
@no_cache_and_check_session
@requiere_permiso("cfg_sco_editar")
def api_scoring_save_criterio_linea(linea_id, criterio_codigo):
    """Guarda la configuración de un criterio para una línea."""
    try:
        # Validar CSRF
        csrf_token = request.headers.get("X-CSRFToken") or request.form.get(
            "csrf_token"
        )
        if not csrf_token:
            return jsonify({"success": False, "error": "Token CSRF requerido"}), 403

        data = request.get_json()

        resultado = guardar_criterio_linea(linea_id, criterio_codigo, data)

        if resultado:
            return jsonify(
                {"success": True, "message": f"Criterio {criterio_codigo} guardado"}
            )
        else:
            return (
                jsonify({"success": False, "error": "Error al guardar criterio"}),
                500,
            )

    except Exception as e:
        logger.error(f"Error guardando criterio: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# -----------------------------------------------------------
# API: Copiar configuración entre líneas
# -----------------------------------------------------------
@app.route("/api/scoring/copiar-config", methods=["POST"])
@no_cache_and_check_session
@requiere_permiso("cfg_sco_editar")
def api_scoring_copiar_config():
    """Copia la configuración de scoring de una línea a otra."""
    try:
        # Validar CSRF
        csrf_token = request.headers.get("X-CSRFToken") or request.form.get(
            "csrf_token"
        )
        if not csrf_token:
            return jsonify({"success": False, "error": "Token CSRF requerido"}), 403

        data = request.get_json()
        linea_origen = data.get("linea_origen_id")
        linea_destino = data.get("linea_destino_id")
        incluir_criterios = data.get("incluir_criterios", True)

        if not linea_origen or not linea_destino:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Debe especificar línea origen y destino",
                    }
                ),
                400,
            )

        if linea_origen == linea_destino:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Origen y destino no pueden ser iguales",
                    }
                ),
                400,
            )

        resultado = copiar_config_scoring(
            linea_origen, linea_destino, incluir_criterios
        )

        if resultado:
            registrar_auditoria(
                session.get("username", "sistema"),
                "SCORING_CONFIG_COPIADA",
                f"Configuración copiada de línea {linea_origen} a {linea_destino}",
                detalles=json.dumps(
                    {
                        "origen": linea_origen,
                        "destino": linea_destino,
                        "incluir_criterios": incluir_criterios,
                    }
                ),
            )

            return jsonify(
                {"success": True, "message": "Configuración copiada exitosamente"}
            )
        else:
            return (
                jsonify({"success": False, "error": "Error al copiar configuración"}),
                500,
            )

    except Exception as e:
        logger.error(f"Error copiando configuración: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# -----------------------------------------------------------
# API: Invalidar cache de scoring (para admin técnico)
# -----------------------------------------------------------
@app.route("/api/scoring/invalidar-cache", methods=["POST"])
@no_cache_and_check_session
@requiere_permiso("cfg_sco_editar")
def api_scoring_invalidar_cache():
    """Invalida el cache de scoring."""
    try:
        linea_id = request.get_json().get("linea_id") if request.is_json else None

        invalidar_cache_scoring_linea(linea_id)

        return jsonify({"success": True, "message": "Cache de scoring invalidado"})
    except Exception as e:
        logger.error(f"Error invalidando cache: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# VERIFICACIÓN DE MIGRACIÓN
# ============================================================================


def verificar_migracion():
    """
    Función para verificar si la migración de scoring multi-línea está completa.
    Llamar desde la consola Flask o al iniciar la aplicación.
    """
    try:
        if verificar_tablas_scoring_linea():
            logger.info("✅ Tablas de scoring multi-línea: OK")
            return True
        else:
            logger.warning("⚠️ Tablas de scoring multi-línea no encontradas")
            logger.warning("   Ejecute: python migration_scoring_multilinea.py")
            return False
    except ImportError:
        logger.error("❌ Módulo db_helpers_scoring_linea no encontrado")
        return False
    except Exception as e:
        logger.error(f"❌ Error verificando migración: {e}")
        return False


# Para ejecutar la aplicación localmente
if __name__ == "__main__":
    # Verificar migración al iniciar (solo en modo desarrollo)
    try:
        verificar_migracion()
    except Exception as e:
        logger.warning(f"No se pudo verificar migración: {e}")

    app.run(debug=True)
