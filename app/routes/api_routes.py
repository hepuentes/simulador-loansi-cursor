"""
API_ROUTES.PY - Rutas de la API REST
=====================================
"""

from flask import request, jsonify, session
from functools import wraps
import json
import traceback

from . import api_bp


def api_login_required(f):
    """Decorador que requiere autenticación para API"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("autorizado"):
            return jsonify({
                'error': 'No autorizado',
                'code': 'AUTH_REQUIRED'
            }), 401
        return f(*args, **kwargs)
    return decorated_function


def api_requiere_permiso(permiso):
    """Decorador que requiere un permiso específico para API"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get("autorizado"):
                return jsonify({
                    'error': 'No autorizado',
                    'code': 'AUTH_REQUIRED'
                }), 401
            
            import sys
            from pathlib import Path
            BASE_DIR = Path(__file__).parent.parent.parent.resolve()
            if str(BASE_DIR) not in sys.path:
                sys.path.insert(0, str(BASE_DIR))
            
            from permisos import tiene_permiso
            
            if not tiene_permiso(permiso):
                return jsonify({
                    'error': 'Permiso denegado',
                    'code': 'PERMISSION_DENIED',
                    'required': permiso
                }), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ============================================================================
# API DE SESIÓN Y CSRF
# ============================================================================

@api_bp.route("/csrf-token", methods=["GET"])
def api_csrf_token():
    """Obtener token CSRF"""
    from flask_wtf.csrf import generate_csrf
    
    return jsonify({
        "csrf_token": generate_csrf()
    })


@api_bp.route("/session-status", methods=["GET"])
def api_session_status():
    """Verificar estado de sesión"""
    if session.get("autorizado"):
        return jsonify({
            "authenticated": True,
            "username": session.get("username"),
            "rol": session.get("rol"),
            "nombre_completo": session.get("nombre_completo")
        })
    return jsonify({"authenticated": False})


# ============================================================================
# API DE CONFIGURACIÓN
# ============================================================================

@api_bp.route("/lineas-config", methods=["GET"])
@api_login_required
def api_lineas_config():
    """Obtener configuración de líneas de crédito"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import cargar_configuracion
    
    config = cargar_configuracion()
    
    return jsonify({
        "lineas_credito": config.get("LINEAS_CREDITO", {}),
        "costos_asociados": config.get("COSTOS_ASOCIADOS", {})
    })


@api_bp.route("/capacidad-config", methods=["GET"])
@api_login_required
def api_capacidad_config():
    """Obtener configuración de capacidad de pago"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import cargar_configuracion
    
    config = cargar_configuracion()
    
    return jsonify(config.get("PARAMETROS_CAPACIDAD_PAGO", {}))


# ============================================================================
# API DE COMITÉ
# ============================================================================

@api_bp.route("/comite/pendientes", methods=["GET"])
@api_login_required
@api_requiere_permiso("com_ver_casos")
def api_comite_pendientes():
    """Obtener casos pendientes del comité"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import obtener_casos_comite
    
    casos = obtener_casos_comite({"estado_comite": "pending"})
    
    return jsonify({
        "casos": casos,
        "total": len(casos)
    })


@api_bp.route("/detalle_evaluacion/<timestamp>", methods=["GET"])
@api_login_required
def api_detalle_evaluacion(timestamp):
    """Obtener detalle de una evaluación"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import obtener_evaluacion_por_timestamp
    
    evaluacion = obtener_evaluacion_por_timestamp(timestamp)
    
    if not evaluacion:
        return jsonify({"error": "Evaluación no encontrada"}), 404
    
    return jsonify(evaluacion)


@api_bp.route("/badge-count", methods=["GET"])
@api_login_required
def api_badge_count():
    """Obtener contadores para badges del navbar"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import contar_casos_nuevos_asesor, obtener_casos_comite
    
    username = session.get("username")
    rol = session.get("rol")
    
    response = {
        "casos_nuevos": 0,
        "pendientes_comite": 0
    }
    
    # Casos nuevos para el asesor
    if username:
        response["casos_nuevos"] = contar_casos_nuevos_asesor(username)
    
    # Pendientes de comité (para admin y comité)
    if rol in ["admin", "admin_tecnico", "comite_credito"]:
        casos_pendientes = obtener_casos_comite({"estado_comite": "pending"})
        response["pendientes_comite"] = len(casos_pendientes)
    
    return jsonify(response)


# ============================================================================
# API DE USUARIOS
# ============================================================================

@api_bp.route("/usuarios/lista", methods=["GET"])
@api_login_required
@api_requiere_permiso("usr_ver")
def api_usuarios_lista():
    """Obtener lista de usuarios"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import obtener_usuarios_completos
    
    usuarios = obtener_usuarios_completos()
    
    return jsonify({
        "usuarios": usuarios,
        "total": len(usuarios)
    })


@api_bp.route("/usuarios/<username>/id", methods=["GET"])
@api_login_required
def api_usuario_id(username):
    """Obtener ID de un usuario por username"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from database import conectar_db
    
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM usuarios WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return jsonify({"id": row[0], "username": username})
    
    return jsonify({"error": "Usuario no encontrado"}), 404


# ============================================================================
# API DE SCORING POR LÍNEA
# ============================================================================

@api_bp.route("/scoring/lineas-credito", methods=["GET"])
@api_login_required
def api_scoring_lineas():
    """Obtener líneas de crédito con info de scoring"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers_scoring_linea import obtener_lineas_credito_scoring
    
    lineas = obtener_lineas_credito_scoring()
    
    return jsonify({
        "lineas": lineas,
        "total": len(lineas)
    })


@api_bp.route("/scoring/linea/<int:linea_id>/config", methods=["GET"])
@api_login_required
def api_scoring_linea_config(linea_id):
    """Obtener configuración de scoring para una línea"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers_scoring_linea import obtener_config_scoring_linea
    
    config = obtener_config_scoring_linea(linea_id)
    
    return jsonify(config)


@api_bp.route("/scoring/linea/<int:linea_id>/config", methods=["POST"])
@api_login_required
@api_requiere_permiso("cfg_sco_editar")
def api_scoring_linea_guardar(linea_id):
    """Guardar configuración de scoring para una línea"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers_scoring_linea import guardar_config_scoring_linea
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No se recibieron datos"}), 400
        
        if guardar_config_scoring_linea(linea_id, data):
            return jsonify({
                "success": True,
                "message": "Configuración guardada"
            })
        else:
            return jsonify({"error": "Error al guardar configuración"}), 500
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/scoring/linea/<int:linea_id>/niveles-riesgo", methods=["GET"])
@api_login_required
def api_scoring_niveles_riesgo(linea_id):
    """Obtener niveles de riesgo para una línea"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers_scoring_linea import obtener_niveles_riesgo_linea
    
    niveles = obtener_niveles_riesgo_linea(linea_id)
    
    return jsonify({
        "niveles": niveles,
        "total": len(niveles)
    })


@api_bp.route("/scoring/linea/<int:linea_id>/niveles-riesgo", methods=["POST"])
@api_login_required
@api_requiere_permiso("cfg_sco_editar")
def api_scoring_niveles_guardar(linea_id):
    """Guardar niveles de riesgo para una línea"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers_scoring_linea import guardar_niveles_riesgo_linea
    
    try:
        data = request.get_json()
        
        if not data or 'niveles' not in data:
            return jsonify({"error": "Datos de niveles no especificados"}), 400
        
        if guardar_niveles_riesgo_linea(linea_id, data['niveles']):
            return jsonify({
                "success": True,
                "message": "Niveles de riesgo guardados"
            })
        else:
            return jsonify({"error": "Error al guardar niveles"}), 500
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ============================================================================
# API DE ESTADOS DE CRÉDITO
# ============================================================================

@api_bp.route("/credito/marcar-desembolsado", methods=["POST"])
@api_login_required
@api_requiere_permiso("est_marcar_desembolsado")
def api_marcar_desembolsado():
    """Marcar un crédito como desembolsado"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers_estados import marcar_desembolsado
    
    try:
        data = request.get_json()
        
        timestamp = data.get("timestamp")
        comentario = data.get("comentario")
        
        if not timestamp:
            return jsonify({"error": "Timestamp no especificado"}), 400
        
        resultado = marcar_desembolsado(
            timestamp, 
            session.get("username"),
            comentario
        )
        
        if resultado['success']:
            return jsonify(resultado)
        else:
            return jsonify(resultado), 400
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/credito/marcar-desistido", methods=["POST"])
@api_login_required
@api_requiere_permiso("est_marcar_desistido")
def api_marcar_desistido():
    """Marcar un crédito como desistido"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers_estados import marcar_desistido
    
    try:
        data = request.get_json()
        
        timestamp = data.get("timestamp")
        motivo = data.get("motivo")
        
        if not timestamp:
            return jsonify({"error": "Timestamp no especificado"}), 400
        
        resultado = marcar_desistido(
            timestamp,
            session.get("username"),
            motivo
        )
        
        if resultado['success']:
            return jsonify(resultado)
        else:
            return jsonify(resultado), 400
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/credito/estadisticas-estados", methods=["GET"])
@api_login_required
def api_estadisticas_estados():
    """Obtener estadísticas de estados de crédito"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers_estados import obtener_estadisticas_estados
    
    estadisticas = obtener_estadisticas_estados()
    
    return jsonify(estadisticas)
