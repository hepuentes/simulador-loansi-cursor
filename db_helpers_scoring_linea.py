"""
DB_HELPERS_SCORING_LINEA.PY - Funciones para Scoring Multi-Línea
================================================================

Este módulo contiene todas las funciones CRUD para el sistema de
scoring por línea de crédito.

Author: Sistema Loansi
Date: 2026-01-13
Version: 1.0
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

# Importar conexión desde database.py
try:
    from database import conectar_db, DB_PATH
except ImportError:
    DB_PATH = Path(__file__).parent / 'loansi.db'
    
    def conectar_db():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


# ============================================================================
# CACHE PARA OPTIMIZACIÓN
# ============================================================================

_SCORING_LINEA_CACHE = {}
_CACHE_TTL = 300  # 5 minutos


def invalidar_cache_scoring_linea(linea_id=None):
    """
    Invalida el cache de scoring por línea.
    
    Args:
        linea_id: Si se especifica, solo invalida esa línea
    """
    global _SCORING_LINEA_CACHE
    
    if linea_id:
        keys_to_remove = [k for k in _SCORING_LINEA_CACHE if str(linea_id) in k]
        for key in keys_to_remove:
            del _SCORING_LINEA_CACHE[key]
        print(f"🔄 Cache de scoring invalidado para línea {linea_id}")
    else:
        _SCORING_LINEA_CACHE = {}
        print("🔄 Cache de scoring completamente invalidado")


# ============================================================================
# FUNCIONES PARA LÍNEAS DE CRÉDITO CON SCORING
# ============================================================================

def obtener_lineas_credito_scoring():
    """
    Obtiene todas las líneas de crédito con información de scoring.
    
    Returns:
        list: Lista de líneas con configuración de scoring
    """
    conn = conectar_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT 
                lc.id,
                lc.nombre,
                lc.descripcion,
                lc.monto_min,
                lc.monto_max,
                lc.plazo_min,
                lc.plazo_max,
                lc.activo,
                COALESCE(scl.puntaje_minimo_aprobacion, 17) as puntaje_minimo,
                COALESCE(scl.score_datacredito_minimo, 400) as score_min,
                (SELECT COUNT(*) FROM niveles_riesgo_linea WHERE linea_credito_id = lc.id) as num_niveles,
                (SELECT COUNT(*) FROM factores_rechazo_linea WHERE linea_credito_id = lc.id) as num_factores
            FROM lineas_credito lc
            LEFT JOIN scoring_config_linea scl ON lc.id = scl.linea_credito_id
            WHERE lc.activo = 1
            ORDER BY lc.nombre
        """)
        
        lineas = []
        for row in cursor.fetchall():
            lineas.append({
                "id": row[0],
                "nombre": row[1],
                "descripcion": row[2],
                "monto_min": row[3],
                "monto_max": row[4],
                "plazo_min": row[5],
                "plazo_max": row[6],
                "activo": bool(row[7]),
                "puntaje_minimo": row[8],
                "score_datacredito_minimo": row[9],
                "num_niveles_riesgo": row[10],
                "num_factores_rechazo": row[11],
                "tiene_config_scoring": row[10] > 0
            })
        
        return lineas
        
    except Exception as e:
        print(f"❌ Error obteniendo líneas de crédito: {e}")
        return []
    finally:
        conn.close()


def obtener_linea_credito_por_id(linea_id):
    """
    Obtiene una línea de crédito específica por ID.
    
    Args:
        linea_id: ID de la línea de crédito
        
    Returns:
        dict: Datos de la línea o None
    """
    conn = conectar_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, nombre, descripcion, monto_min, monto_max,
                   plazo_min, plazo_max, tasa_mensual, tasa_anual,
                   aval_porcentaje, activo
            FROM lineas_credito
            WHERE id = ?
        """, (linea_id,))
        
        row = cursor.fetchone()
        if row:
            return {
                "id": row[0],
                "nombre": row[1],
                "descripcion": row[2],
                "monto_min": row[3],
                "monto_max": row[4],
                "plazo_min": row[5],
                "plazo_max": row[6],
                "tasa_mensual": row[7],
                "tasa_anual": row[8],
                "aval_porcentaje": row[9],
                "activo": bool(row[10])
            }
        return None
        
    except Exception as e:
        print(f"❌ Error obteniendo línea {linea_id}: {e}")
        return None
    finally:
        conn.close()


def obtener_linea_credito_por_nombre(nombre):
    """
    Obtiene una línea de crédito por nombre.
    
    Args:
        nombre: Nombre de la línea
        
    Returns:
        dict: Datos de la línea o None
    """
    conn = conectar_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, nombre, descripcion, monto_min, monto_max,
                   plazo_min, plazo_max, tasa_mensual, tasa_anual,
                   aval_porcentaje, activo
            FROM lineas_credito
            WHERE nombre = ? AND activo = 1
        """, (nombre,))
        
        row = cursor.fetchone()
        if row:
            return {
                "id": row[0],
                "nombre": row[1],
                "descripcion": row[2],
                "monto_min": row[3],
                "monto_max": row[4],
                "plazo_min": row[5],
                "plazo_max": row[6],
                "tasa_mensual": row[7],
                "tasa_anual": row[8],
                "aval_porcentaje": row[9],
                "activo": bool(row[10])
            }
        return None
        
    except Exception as e:
        print(f"❌ Error obteniendo línea {nombre}: {e}")
        return None
    finally:
        conn.close()


# ============================================================================
# FUNCIONES PARA CONFIGURACIÓN DE SCORING POR LÍNEA
# ============================================================================

def obtener_config_scoring_linea(linea_id):
    """
    Obtiene la configuración de scoring para una línea específica.
    
    Args:
        linea_id: ID de la línea de crédito
        
    Returns:
        dict: Configuración completa de scoring para la línea
    """
    import time
    cache_key = f"config_{linea_id}"
    now = time.time()
    
    # Verificar cache
    if cache_key in _SCORING_LINEA_CACHE:
        cached_data, timestamp = _SCORING_LINEA_CACHE[cache_key]
        if now - timestamp < _CACHE_TTL:
            return cached_data
    
    conn = conectar_db()
    cursor = conn.cursor()
    
    config = {
        "linea_id": linea_id,
        "config_general": {},
        "niveles_riesgo": [],
        "factores_rechazo": [],
        "criterios": {}
    }
    
    try:
        # 1. Configuración general
        cursor.execute("""
            SELECT 
                scl.*,
                lc.nombre as linea_nombre
            FROM scoring_config_linea scl
            JOIN lineas_credito lc ON scl.linea_credito_id = lc.id
            WHERE scl.linea_credito_id = ?
        """, (linea_id,))
        
        row = cursor.fetchone()
        if row:
            config["config_general"] = {
                "linea_nombre": row["linea_nombre"],
                "puntaje_minimo_aprobacion": row["puntaje_minimo_aprobacion"],
                "puntaje_revision_manual": row["puntaje_revision_manual"],
                "umbral_mora_telcos": row["umbral_mora_telcos"],
                "edad_minima": row["edad_minima"],
                "edad_maxima": row["edad_maxima"],
                "dti_maximo": row["dti_maximo"],
                "score_datacredito_minimo": row["score_datacredito_minimo"],
                "consultas_max_3meses": row["consultas_max_3meses"],
                "escala_max": row["escala_max"]
            }
        else:
            # Valores por defecto si no existe configuración
            cursor.execute("SELECT nombre FROM lineas_credito WHERE id = ?", (linea_id,))
            nombre_row = cursor.fetchone()
            config["config_general"] = {
                "linea_nombre": nombre_row[0] if nombre_row else "Sin nombre",
                "puntaje_minimo_aprobacion": 17,
                "puntaje_revision_manual": 10,
                "umbral_mora_telcos": 200000,
                "edad_minima": 18,
                "edad_maxima": 84,
                "dti_maximo": 50,
                "score_datacredito_minimo": 400,
                "consultas_max_3meses": 8,
                "escala_max": 100
            }
        
        # 2. Niveles de riesgo
        cursor.execute("""
            SELECT id, nombre, codigo, score_min, score_max,
                   tasa_ea, tasa_nominal_mensual, aval_porcentaje,
                   color, orden, activo
            FROM niveles_riesgo_linea
            WHERE linea_credito_id = ? AND activo = 1
            ORDER BY orden, score_min DESC
        """, (linea_id,))
        
        for row in cursor.fetchall():
            config["niveles_riesgo"].append({
                "id": row[0],
                "nombre": row[1],
                "codigo": row[2],
                "min": row[3],
                "max": row[4],
                "tasa_ea": row[5],
                "tasa_nominal_mensual": row[6],
                "aval_porcentaje": row[7],
                "color": row[8],
                "orden": row[9]
            })
        
        # 3. Factores de rechazo
        cursor.execute("""
            SELECT id, criterio_codigo, criterio_nombre, operador,
                   valor_umbral, mensaje_rechazo, activo, orden
            FROM factores_rechazo_linea
            WHERE linea_credito_id = ? AND activo = 1
            ORDER BY orden
        """, (linea_id,))
        
        for row in cursor.fetchall():
            config["factores_rechazo"].append({
                "id": row[0],
                "criterio": row[1],
                "criterio_nombre": row[2],
                "operador": row[3],
                "valor": row[4],
                "mensaje": row[5],
                "activo": bool(row[6])
            })
        
        # 4. Criterios con configuración por línea
        cursor.execute("""
            SELECT 
                csm.codigo,
                csm.nombre,
                csm.descripcion,
                csm.tipo_campo,
                csm.seccion_id,
                clc.peso,
                clc.activo,
                clc.orden,
                clc.rangos_json
            FROM criterios_scoring_master csm
            LEFT JOIN criterios_linea_credito clc 
                ON csm.id = clc.criterio_master_id AND clc.linea_credito_id = ?
            WHERE csm.activo = 1
            ORDER BY COALESCE(clc.orden, csm.id)
        """, (linea_id,))
        
        for row in cursor.fetchall():
            rangos = []
            if row[8]:
                try:
                    rangos = json.loads(row[8])
                except:
                    pass
            
            config["criterios"][row[0]] = {
                "nombre": row[1],
                "descripcion": row[2],
                "tipo_campo": row[3],
                "seccion_id": row[4],
                "peso": row[5] or 5,
                "activo": bool(row[6]) if row[6] is not None else True,
                "orden": row[7] or 0,
                "rangos": rangos
            }
        
        # Guardar en cache
        _SCORING_LINEA_CACHE[cache_key] = (config, now)
        
        return config
        
    except Exception as e:
        print(f"❌ Error obteniendo config scoring línea {linea_id}: {e}")
        import traceback
        traceback.print_exc()
        return config
    finally:
        conn.close()


def guardar_config_scoring_linea(linea_id, config):
    """
    Guarda la configuración de scoring para una línea.
    
    Args:
        linea_id: ID de la línea de crédito
        config: dict con la configuración
        
    Returns:
        bool: True si se guardó exitosamente
    """
    conn = conectar_db()
    cursor = conn.cursor()
    
    try:
        # 1. Guardar/actualizar configuración general
        if "config_general" in config:
            cg = config["config_general"]
            cursor.execute("""
                INSERT OR REPLACE INTO scoring_config_linea
                (linea_credito_id, puntaje_minimo_aprobacion, puntaje_revision_manual,
                 umbral_mora_telcos, edad_minima, edad_maxima, dti_maximo,
                 score_datacredito_minimo, consultas_max_3meses, escala_max,
                 activo, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            """, (
                linea_id,
                cg.get("puntaje_minimo_aprobacion", 17),
                cg.get("puntaje_revision_manual", 10),
                cg.get("umbral_mora_telcos", 200000),
                cg.get("edad_minima", 18),
                cg.get("edad_maxima", 84),
                cg.get("dti_maximo", 50),
                cg.get("score_datacredito_minimo", 400),
                cg.get("consultas_max_3meses", 8),
                cg.get("escala_max", 100)
            ))
            print(f"✅ Configuración general guardada para línea {linea_id}")
        
        conn.commit()
        
        # Invalidar cache
        invalidar_cache_scoring_linea(linea_id)
        
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error guardando config scoring: {e}")
        return False
    finally:
        conn.close()


# ============================================================================
# CREAR CONFIGURACIÓN DE SCORING POR DEFECTO PARA NUEVA LÍNEA
# ============================================================================

def crear_config_scoring_linea_defecto(linea_id, tasa_anual=25.0, copiar_de_linea_id=None):
    """
    Crea la configuración de scoring por defecto para una nueva línea de crédito.
    
    Esta función se llama automáticamente cuando se crea una nueva línea de crédito.
    Crea:
    - Configuración general con valores por defecto
    - 3 niveles de riesgo (Bajo Riesgo, Moderado, Alto Riesgo)
    - Factores de rechazo básicos
    
    Args:
        linea_id: ID de la línea de crédito recién creada
        tasa_anual: Tasa anual base para calcular las tasas de niveles
        copiar_de_linea_id: Si se especifica, copia la configuración de otra línea
        
    Returns:
        bool: True si se creó exitosamente
    """
    conn = conectar_db()
    cursor = conn.cursor()
    
    try:
        # Si se especifica copiar de otra línea, usar esa función
        if copiar_de_linea_id:
            conn.close()
            return copiar_config_scoring(copiar_de_linea_id, linea_id)
        
        # Verificar que la línea existe
        cursor.execute("SELECT nombre FROM lineas_credito WHERE id = ?", (linea_id,))
        linea = cursor.fetchone()
        if not linea:
            print(f"❌ Línea {linea_id} no existe")
            return False
        
        nombre_linea = linea[0]
        print(f"🔧 Creando configuración de scoring para nueva línea: {nombre_linea} (ID: {linea_id})")
        
        # 1. Crear configuración general
        cursor.execute("""
            INSERT OR REPLACE INTO scoring_config_linea
            (linea_credito_id, puntaje_minimo_aprobacion, puntaje_revision_manual,
             umbral_mora_telcos, edad_minima, edad_maxima, dti_maximo,
             score_datacredito_minimo, consultas_max_3meses, escala_max,
             activo, updated_at)
            VALUES (?, 17, 10, 200000, 18, 65, 50, 400, 8, 100, 1, CURRENT_TIMESTAMP)
        """, (linea_id,))
        print(f"  ✅ Configuración general creada")
        
        # 2. Crear niveles de riesgo por defecto
        # Calcular tasas basadas en la tasa anual de la línea
        niveles_defecto = [
            {
                "nombre": "Bajo Riesgo",
                "codigo": "bajo_riesgo",
                "score_min": 70.1,
                "score_max": 100.0,
                "tasa_ea": tasa_anual,  # Tasa base
                "aval_porcentaje": 0.065,
                "color": "#28a745",
                "orden": 1
            },
            {
                "nombre": "Moderado",
                "codigo": "moderado",
                "score_min": 55.1,
                "score_max": 70.0,
                "tasa_ea": tasa_anual + 3,  # Tasa base + 3%
                "aval_porcentaje": 0.10,
                "color": "#ffc107",
                "orden": 2
            },
            {
                "nombre": "Alto Riesgo",
                "codigo": "alto_riesgo",
                "score_min": 0.0,
                "score_max": 55.0,
                "tasa_ea": tasa_anual + 8,  # Tasa base + 8%
                "aval_porcentaje": 0.15,
                "color": "#dc3545",
                "orden": 3
            }
        ]
        
        for nivel in niveles_defecto:
            # Calcular tasa nominal mensual: ((1 + tasa_ea/100)^(1/12) - 1) * 100
            tasa_ea = nivel["tasa_ea"]
            tasa_nominal = (pow(1 + tasa_ea/100, 1/12) - 1) * 100
            
            cursor.execute("""
                INSERT INTO niveles_riesgo_linea
                (linea_credito_id, nombre, codigo, score_min, score_max,
                 tasa_ea, tasa_nominal_mensual, aval_porcentaje, color, orden, activo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                linea_id,
                nivel["nombre"],
                nivel["codigo"],
                nivel["score_min"],
                nivel["score_max"],
                nivel["tasa_ea"],
                round(tasa_nominal, 4),
                nivel["aval_porcentaje"],
                nivel["color"],
                nivel["orden"]
            ))
        print(f"  ✅ {len(niveles_defecto)} niveles de riesgo creados")
        
        # 3. Crear factores de rechazo básicos
        factores_defecto = [
            ("score_datacredito", "Score DataCrédito", "<", 400, "Score DataCrédito inferior al mínimo requerido"),
            ("mora_sector_financiero", "Mora activa sector financiero", ">", 30, "Presenta mora activa en el sector financiero"),
            ("mora_telcos", "Mora en telecomunicaciones", ">", 200000, "Mora en telecomunicaciones superior al umbral"),
            ("mora_telcos_dias", "Mora telcos (días)", ">", 90, "Mora en telecomunicaciones mayor a 90 días"),
            ("dti", "Relación deuda/ingreso (DTI)", ">", 50, "Nivel de endeudamiento superior al 50%"),
            ("consultas_3meses", "Consultas últimos 3 meses", ">", 8, "Exceso de consultas crediticias"),
            ("edad", "Edad del solicitante", "<", 18, f"Edad mínima 18 años para {nombre_linea}"),
            ("edad", "Edad del solicitante", ">", 65, f"Edad máxima 65 años para {nombre_linea}"),
        ]
        
        for i, (criterio, nombre, operador, valor, mensaje) in enumerate(factores_defecto):
            cursor.execute("""
                INSERT INTO factores_rechazo_linea
                (linea_credito_id, criterio_codigo, criterio_nombre, operador,
                 valor_umbral, mensaje_rechazo, activo, orden)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """, (linea_id, criterio, nombre, operador, valor, mensaje, i + 1))
        print(f"  ✅ {len(factores_defecto)} factores de rechazo creados")
        
        conn.commit()
        
        # Invalidar cache
        invalidar_cache_scoring_linea(linea_id)
        
        print(f"✅ Configuración de scoring completa creada para {nombre_linea}")
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error creando config scoring por defecto: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        conn.close()


# ============================================================================
# FUNCIONES PARA NIVELES DE RIESGO POR LÍNEA
# ============================================================================

def obtener_niveles_riesgo_linea(linea_id):
    """
    Obtiene los niveles de riesgo para una línea.
    
    Args:
        linea_id: ID de la línea de crédito
        
    Returns:
        list: Lista de niveles de riesgo
    """
    conn = conectar_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, nombre, codigo, score_min, score_max,
                   tasa_ea, tasa_nominal_mensual, aval_porcentaje,
                   color, orden, activo
            FROM niveles_riesgo_linea
            WHERE linea_credito_id = ?
            ORDER BY orden, score_min DESC
        """, (linea_id,))
        
        niveles = []
        for row in cursor.fetchall():
            niveles.append({
                "id": row[0],
                "nombre": row[1],
                "codigo": row[2],
                "min": row[3],
                "max": row[4],
                "tasa_ea": row[5],
                "tasa_nominal_mensual": row[6],
                "aval_porcentaje": row[7],
                "color": row[8],
                "orden": row[9],
                "activo": bool(row[10])
            })
        
        return niveles
        
    except Exception as e:
        print(f"❌ Error obteniendo niveles de riesgo: {e}")
        return []
    finally:
        conn.close()


def guardar_niveles_riesgo_linea(linea_id, niveles):
    """
    Guarda los niveles de riesgo para una línea.
    
    Args:
        linea_id: ID de la línea de crédito
        niveles: Lista de niveles de riesgo
        
    Returns:
        bool: True si se guardó exitosamente
    """
    conn = conectar_db()
    cursor = conn.cursor()
    
    try:
        # Eliminar niveles existentes
        cursor.execute("""
            DELETE FROM niveles_riesgo_linea WHERE linea_credito_id = ?
        """, (linea_id,))
        
        # Insertar nuevos niveles
        for i, nivel in enumerate(niveles):
            cursor.execute("""
                INSERT INTO niveles_riesgo_linea
                (linea_credito_id, nombre, codigo, score_min, score_max,
                 tasa_ea, tasa_nominal_mensual, aval_porcentaje,
                 color, orden, activo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                linea_id,
                nivel.get("nombre", f"Nivel {i+1}"),
                nivel.get("codigo", f"N{i+1}"),
                nivel.get("min", 0),
                nivel.get("max", 100),
                nivel.get("tasa_ea", 24.0),
                nivel.get("tasa_nominal_mensual", 1.81),
                nivel.get("aval_porcentaje", 0.10),
                nivel.get("color", "#FF4136"),
                nivel.get("orden", i)
            ))
        
        conn.commit()
        invalidar_cache_scoring_linea(linea_id)
        
        print(f"✅ {len(niveles)} niveles de riesgo guardados para línea {linea_id}")
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error guardando niveles de riesgo: {e}")
        return False
    finally:
        conn.close()


# ============================================================================
# FUNCIONES PARA FACTORES DE RECHAZO POR LÍNEA
# ============================================================================

def obtener_factores_rechazo_linea(linea_id):
    """
    Obtiene los factores de rechazo para una línea.
    
    Args:
        linea_id: ID de la línea de crédito
        
    Returns:
        list: Lista de factores de rechazo
    """
    conn = conectar_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, criterio_codigo, criterio_nombre, operador,
                   valor_umbral, mensaje_rechazo, activo, orden
            FROM factores_rechazo_linea
            WHERE linea_credito_id = ?
            ORDER BY orden
        """, (linea_id,))
        
        factores = []
        for row in cursor.fetchall():
            factores.append({
                "id": row[0],
                "criterio": row[1],
                "criterio_nombre": row[2],
                "operador": row[3],
                "valor": row[4],
                "mensaje": row[5],
                "activo": bool(row[6]),
                "orden": row[7]
            })
        
        return factores
        
    except Exception as e:
        print(f"❌ Error obteniendo factores de rechazo: {e}")
        return []
    finally:
        conn.close()


def guardar_factores_rechazo_linea(linea_id, factores):
    """
    Guarda los factores de rechazo para una línea.
    
    Args:
        linea_id: ID de la línea de crédito
        factores: Lista de factores de rechazo
        
    Returns:
        bool: True si se guardó exitosamente
    """
    conn = conectar_db()
    cursor = conn.cursor()
    
    try:
        # Eliminar factores existentes
        cursor.execute("""
            DELETE FROM factores_rechazo_linea WHERE linea_credito_id = ?
        """, (linea_id,))
        
        # Insertar nuevos factores
        for i, factor in enumerate(factores):
            cursor.execute("""
                INSERT INTO factores_rechazo_linea
                (linea_credito_id, criterio_codigo, criterio_nombre, operador,
                 valor_umbral, mensaje_rechazo, activo, orden)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                linea_id,
                factor.get("criterio", ""),
                factor.get("criterio_nombre", ""),
                factor.get("operador", "<"),
                factor.get("valor", 0),
                factor.get("mensaje", ""),
                1 if factor.get("activo", True) else 0,
                factor.get("orden", i)
            ))
        
        conn.commit()
        invalidar_cache_scoring_linea(linea_id)
        
        print(f"✅ {len(factores)} factores de rechazo guardados para línea {linea_id}")
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error guardando factores de rechazo: {e}")
        return False
    finally:
        conn.close()


def agregar_factor_rechazo_linea(linea_id, factor):
    """
    Agrega un nuevo factor de rechazo a una línea.
    
    Args:
        linea_id: ID de la línea de crédito
        factor: dict con datos del factor
        
    Returns:
        int: ID del factor creado o None
    """
    conn = conectar_db()
    cursor = conn.cursor()
    
    try:
        # Obtener siguiente orden
        cursor.execute("""
            SELECT COALESCE(MAX(orden), -1) + 1 FROM factores_rechazo_linea
            WHERE linea_credito_id = ?
        """, (linea_id,))
        nuevo_orden = cursor.fetchone()[0]
        
        cursor.execute("""
            INSERT INTO factores_rechazo_linea
            (linea_credito_id, criterio_codigo, criterio_nombre, operador,
             valor_umbral, mensaje_rechazo, activo, orden)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
        """, (
            linea_id,
            factor.get("criterio", ""),
            factor.get("criterio_nombre", ""),
            factor.get("operador", "<"),
            factor.get("valor", 0),
            factor.get("mensaje", ""),
            nuevo_orden
        ))
        
        factor_id = cursor.lastrowid
        conn.commit()
        invalidar_cache_scoring_linea(linea_id)
        
        return factor_id
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error agregando factor de rechazo: {e}")
        return None
    finally:
        conn.close()


def eliminar_factor_rechazo(factor_id):
    """
    Elimina un factor de rechazo.
    
    Args:
        factor_id: ID del factor a eliminar
        
    Returns:
        bool: True si se eliminó exitosamente
    """
    conn = conectar_db()
    cursor = conn.cursor()
    
    try:
        # Obtener linea_id antes de eliminar (para invalidar cache)
        cursor.execute("""
            SELECT linea_credito_id FROM factores_rechazo_linea WHERE id = ?
        """, (factor_id,))
        row = cursor.fetchone()
        linea_id = row[0] if row else None
        
        cursor.execute("""
            DELETE FROM factores_rechazo_linea WHERE id = ?
        """, (factor_id,))
        
        conn.commit()
        
        if linea_id:
            invalidar_cache_scoring_linea(linea_id)
        
        return cursor.rowcount > 0
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error eliminando factor de rechazo: {e}")
        return False
    finally:
        conn.close()


# ============================================================================
# FUNCIONES PARA CRITERIOS POR LÍNEA
# ============================================================================

def obtener_criterios_linea(linea_id):
    """
    Obtiene los criterios configurados para una línea.
    
    Args:
        linea_id: ID de la línea de crédito
        
    Returns:
        dict: Diccionario de criterios con sus configuraciones
    """
    conn = conectar_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT 
                csm.codigo,
                csm.nombre,
                csm.descripcion,
                csm.tipo_campo,
                csm.seccion_id,
                COALESCE(clc.peso, 5) as peso,
                COALESCE(clc.activo, 1) as activo,
                COALESCE(clc.orden, csm.id) as orden,
                clc.rangos_json
            FROM criterios_scoring_master csm
            LEFT JOIN criterios_linea_credito clc 
                ON csm.id = clc.criterio_master_id AND clc.linea_credito_id = ?
            WHERE csm.activo = 1
            ORDER BY orden
        """, (linea_id,))
        
        criterios = {}
        for row in cursor.fetchall():
            rangos = []
            if row[8]:
                try:
                    rangos = json.loads(row[8])
                except:
                    pass
            
            criterios[row[0]] = {
                "nombre": row[1],
                "descripcion": row[2],
                "tipo_campo": row[3],
                "seccion_id": row[4],
                "peso": row[5],
                "activo": bool(row[6]),
                "orden": row[7],
                "rangos": rangos
            }
        
        return criterios
        
    except Exception as e:
        print(f"❌ Error obteniendo criterios: {e}")
        return {}
    finally:
        conn.close()


def guardar_criterio_linea(linea_id, criterio_codigo, config):
    """
    Guarda la configuración de un criterio para una línea.
    
    Args:
        linea_id: ID de la línea de crédito
        criterio_codigo: Código del criterio
        config: dict con la configuración del criterio
        
    Returns:
        bool: True si se guardó exitosamente
    """
    conn = conectar_db()
    cursor = conn.cursor()
    
    try:
        # Obtener ID del criterio master
        cursor.execute("""
            SELECT id FROM criterios_scoring_master WHERE codigo = ?
        """, (criterio_codigo,))
        row = cursor.fetchone()
        
        if not row:
            print(f"❌ Criterio {criterio_codigo} no encontrado en catálogo master")
            return False
        
        criterio_master_id = row[0]
        
        # Serializar rangos
        rangos_json = json.dumps(config.get("rangos", []), ensure_ascii=False)
        
        # Insertar o actualizar
        cursor.execute("""
            INSERT OR REPLACE INTO criterios_linea_credito
            (criterio_master_id, linea_credito_id, peso, activo, orden, rangos_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            criterio_master_id,
            linea_id,
            config.get("peso", 5),
            1 if config.get("activo", True) else 0,
            config.get("orden", 0),
            rangos_json
        ))
        
        conn.commit()
        invalidar_cache_scoring_linea(linea_id)
        
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error guardando criterio: {e}")
        return False
    finally:
        conn.close()


# ============================================================================
# FUNCIONES PARA COPIAR CONFIGURACIÓN ENTRE LÍNEAS
# ============================================================================

def copiar_config_scoring(linea_origen_id, linea_destino_id, incluir_criterios=True):
    """
    Copia la configuración de scoring de una línea a otra.
    
    Args:
        linea_origen_id: ID de la línea origen
        linea_destino_id: ID de la línea destino
        incluir_criterios: Si True, también copia los criterios
        
    Returns:
        bool: True si se copió exitosamente
    """
    conn = conectar_db()
    cursor = conn.cursor()
    
    try:
        # 1. Copiar configuración general
        cursor.execute("""
            INSERT OR REPLACE INTO scoring_config_linea
            (linea_credito_id, puntaje_minimo_aprobacion, puntaje_revision_manual,
             umbral_mora_telcos, edad_minima, edad_maxima, dti_maximo,
             score_datacredito_minimo, consultas_max_3meses, escala_max, activo)
            SELECT 
                ?, puntaje_minimo_aprobacion, puntaje_revision_manual,
                umbral_mora_telcos, edad_minima, edad_maxima, dti_maximo,
                score_datacredito_minimo, consultas_max_3meses, escala_max, activo
            FROM scoring_config_linea
            WHERE linea_credito_id = ?
        """, (linea_destino_id, linea_origen_id))
        
        # 2. Eliminar y copiar niveles de riesgo
        cursor.execute("DELETE FROM niveles_riesgo_linea WHERE linea_credito_id = ?", 
                      (linea_destino_id,))
        
        cursor.execute("""
            INSERT INTO niveles_riesgo_linea
            (linea_credito_id, nombre, codigo, score_min, score_max,
             tasa_ea, tasa_nominal_mensual, aval_porcentaje, color, orden, activo)
            SELECT 
                ?, nombre, codigo, score_min, score_max,
                tasa_ea, tasa_nominal_mensual, aval_porcentaje, color, orden, activo
            FROM niveles_riesgo_linea
            WHERE linea_credito_id = ?
        """, (linea_destino_id, linea_origen_id))
        
        # 3. Eliminar y copiar factores de rechazo
        cursor.execute("DELETE FROM factores_rechazo_linea WHERE linea_credito_id = ?",
                      (linea_destino_id,))
        
        cursor.execute("""
            INSERT INTO factores_rechazo_linea
            (linea_credito_id, criterio_codigo, criterio_nombre, operador,
             valor_umbral, mensaje_rechazo, activo, orden)
            SELECT 
                ?, criterio_codigo, criterio_nombre, operador,
                valor_umbral, mensaje_rechazo, activo, orden
            FROM factores_rechazo_linea
            WHERE linea_credito_id = ?
        """, (linea_destino_id, linea_origen_id))
        
        # 4. Copiar criterios si se indica
        if incluir_criterios:
            cursor.execute("DELETE FROM criterios_linea_credito WHERE linea_credito_id = ?",
                          (linea_destino_id,))
            
            cursor.execute("""
                INSERT INTO criterios_linea_credito
                (criterio_master_id, linea_credito_id, peso, activo, orden, rangos_json)
                SELECT 
                    criterio_master_id, ?, peso, activo, orden, rangos_json
                FROM criterios_linea_credito
                WHERE linea_credito_id = ?
            """, (linea_destino_id, linea_origen_id))
        
        conn.commit()
        
        # Invalidar cache de ambas líneas
        invalidar_cache_scoring_linea(linea_origen_id)
        invalidar_cache_scoring_linea(linea_destino_id)
        
        print(f"✅ Configuración copiada de línea {linea_origen_id} a {linea_destino_id}")
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error copiando configuración: {e}")
        return False
    finally:
        conn.close()


# ============================================================================
# FUNCIÓN PARA OBTENER SCORING COMPLETO (compatible con sistema actual)
# ============================================================================

def cargar_scoring_por_linea(linea_nombre):
    """
    Carga la configuración de scoring para una línea específica.
    Compatible con el formato usado por el sistema actual.
    
    Args:
        linea_nombre: Nombre de la línea de crédito
        
    Returns:
        dict: Configuración de scoring en formato compatible
    """
    # Obtener ID de la línea
    linea = obtener_linea_credito_por_nombre(linea_nombre)
    
    if not linea:
        print(f"⚠️ Línea {linea_nombre} no encontrada, usando configuración global")
        return None
    
    # Obtener configuración de la línea
    config = obtener_config_scoring_linea(linea["id"])
    
    if not config or not config.get("niveles_riesgo"):
        print(f"⚠️ Línea {linea_nombre} sin configuración, usando global")
        return None
    
    # Convertir al formato esperado por el sistema actual
    scoring = {
        "criterios": config.get("criterios", {}),
        "niveles_riesgo": config.get("niveles_riesgo", []),
        "factores_rechazo_automatico": config.get("factores_rechazo", []),
        "puntaje_minimo_aprobacion": config["config_general"].get("puntaje_minimo_aprobacion", 17),
        "umbral_mora_telcos_rechazo": config["config_general"].get("umbral_mora_telcos", 200000),
        "escala_max": config["config_general"].get("escala_max", 100),
        "linea_credito_id": linea["id"],
        "linea_credito_nombre": linea_nombre
    }
    
    return scoring


# ============================================================================
# FUNCIONES DE UTILIDAD
# ============================================================================

def verificar_tablas_scoring_linea():
    """
    Verifica que existan las tablas necesarias para scoring multi-línea.
    
    Returns:
        bool: True si todas las tablas existen
    """
    conn = conectar_db()
    cursor = conn.cursor()
    
    tablas_requeridas = [
        "scoring_config_linea",
        "niveles_riesgo_linea",
        "criterios_scoring_master",
        "criterios_linea_credito",
        "factores_rechazo_linea",
        "secciones_scoring"
    ]
    
    try:
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table'
        """)
        
        tablas_existentes = [row[0] for row in cursor.fetchall()]
        
        faltantes = [t for t in tablas_requeridas if t not in tablas_existentes]
        
        if faltantes:
            print(f"⚠️ Tablas faltantes: {faltantes}")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ Error verificando tablas: {e}")
        return False
    finally:
        conn.close()


def obtener_secciones_scoring():
    """
    Obtiene las secciones de scoring.
    
    Returns:
        list: Lista de secciones
    """
    conn = conectar_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, nombre, icono, descripcion, orden
            FROM secciones_scoring
            WHERE activo = 1
            ORDER BY orden
        """)
        
        secciones = []
        for row in cursor.fetchall():
            secciones.append({
                "id": row[0],
                "nombre": row[1],
                "icono": row[2],
                "descripcion": row[3],
                "orden": row[4]
            })
        
        return secciones
        
    except Exception as e:
        print(f"❌ Error obteniendo secciones: {e}")
        return []
    finally:
        conn.close()
