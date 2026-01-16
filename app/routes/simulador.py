"""
SIMULADOR.PY - Rutas del simulador de crédito
==============================================
"""

from flask import render_template, request, redirect, url_for, session, jsonify, flash
from functools import wraps
import json

from . import simulador_bp


def login_required(f):
    """Decorador que requiere autenticación"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("autorizado"):
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated_function


def requiere_permiso(permiso):
    """Decorador que requiere un permiso específico"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get("autorizado"):
                return redirect(url_for("auth.login"))
            
            # Importar función de permisos
            import sys
            from pathlib import Path
            BASE_DIR = Path(__file__).parent.parent.parent.resolve()
            if str(BASE_DIR) not in sys.path:
                sys.path.insert(0, str(BASE_DIR))
            
            from permisos import tiene_permiso
            
            if not tiene_permiso(permiso):
                flash("No tienes permiso para acceder a esta función", "error")
                return redirect(url_for("main.dashboard"))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


@simulador_bp.route("/simulador")
@login_required
@requiere_permiso("sim_usar")
def simulador_asesor():
    """Página del simulador de crédito para asesores"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import cargar_configuracion, cargar_scoring
    
    config = cargar_configuracion()
    scoring = cargar_scoring()
    
    lineas_credito = config.get("LINEAS_CREDITO", {})
    costos_asociados = config.get("COSTOS_ASOCIADOS", {})
    niveles_riesgo = scoring.get("niveles_riesgo", [])
    
    return render_template(
        "asesor/simulador.html",
        lineas_credito=lineas_credito,
        costos_asociados=costos_asociados,
        niveles_riesgo=niveles_riesgo,
        config_json=json.dumps({
            "lineas_credito": lineas_credito,
            "costos_asociados": costos_asociados,
            "niveles_riesgo": niveles_riesgo
        })
    )


@simulador_bp.route("/capacidad_pago")
@login_required
@requiere_permiso("cap_usar")
def capacidad_pago():
    """Página de cálculo de capacidad de pago"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import cargar_configuracion
    
    config = cargar_configuracion()
    parametros = config.get("PARAMETROS_CAPACIDAD_PAGO", {})
    
    return render_template(
        "asesor/capacidad_pago.html",
        parametros=parametros
    )


@simulador_bp.route("/historial_simulaciones")
@login_required
def historial_simulaciones():
    """Historial de simulaciones del asesor"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import cargar_simulaciones, resolve_visible_usernames
    from permisos import obtener_permisos_usuario_actual
    
    username = session.get("username")
    permisos = obtener_permisos_usuario_actual()
    
    # Determinar qué simulaciones puede ver
    visibilidad = resolve_visible_usernames(username, permisos, contexto="simulaciones")
    
    # Cargar simulaciones según visibilidad
    todas_simulaciones = cargar_simulaciones()
    
    if visibilidad['scope'] == 'todos':
        simulaciones = todas_simulaciones
    elif visibilidad['scope'] == 'equipo':
        usernames_visibles = visibilidad['usernames_visibles'] or []
        simulaciones = [s for s in todas_simulaciones if s.get('asesor') in usernames_visibles]
    else:
        # Solo propias
        simulaciones = [s for s in todas_simulaciones if s.get('asesor') == username]
    
    return render_template(
        "asesor/historial_simulaciones.html",
        simulaciones=simulaciones,
        scope=visibilidad['scope']
    )


@simulador_bp.route("/guardar_simulacion", methods=["POST"])
@login_required
@requiere_permiso("sim_usar")
def guardar_simulacion_endpoint():
    """Guardar una nueva simulación"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import guardar_simulacion
    from ..utils.timezone import obtener_hora_colombia
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No se recibieron datos"}), 400
        
        # Agregar metadata
        data["timestamp"] = obtener_hora_colombia().isoformat()
        data["asesor"] = session.get("username")
        
        # Guardar simulación
        guardar_simulacion(data)
        
        return jsonify({
            "success": True,
            "message": "Simulación guardada correctamente",
            "timestamp": data["timestamp"]
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
