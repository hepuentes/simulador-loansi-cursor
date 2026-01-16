"""
COMITE_ROUTES.PY - Rutas del comité de crédito
===============================================
"""

from flask import render_template, request, redirect, url_for, session, jsonify, flash
from functools import wraps
import json
import traceback

from . import comite_bp


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
            
            import sys
            from pathlib import Path
            BASE_DIR = Path(__file__).parent.parent.parent.resolve()
            if str(BASE_DIR) not in sys.path:
                sys.path.insert(0, str(BASE_DIR))
            
            from permisos import tiene_permiso
            
            if not tiene_permiso(permiso):
                if request.is_json or request.path.startswith('/api/'):
                    return jsonify({
                        'error': 'Permiso denegado',
                        'code': 'PERMISSION_DENIED'
                    }), 403
                flash("No tienes permiso para acceder a esta función", "error")
                return redirect(url_for("main.dashboard"))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


@comite_bp.route("/admin/comite-credito")
@login_required
@requiere_permiso("com_ver_casos")
def comite_credito():
    """Panel del comité de crédito"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import obtener_casos_comite, cargar_configuracion, cargar_scoring
    
    # Obtener casos pendientes
    casos_pendientes = obtener_casos_comite({"estado_comite": "pending"})
    casos_aprobados = obtener_casos_comite({"estado_comite": "approved", "limite": 50})
    casos_rechazados = obtener_casos_comite({"estado_comite": "rejected", "limite": 50})
    
    # Configuración
    config = cargar_configuracion()
    scoring = cargar_scoring()
    
    config_comite = config.get("COMITE_CREDITO", {})
    niveles_riesgo = scoring.get("niveles_riesgo", [])
    
    return render_template(
        "admin/comite_credito.html",
        casos_pendientes=casos_pendientes,
        casos_aprobados=casos_aprobados,
        casos_rechazados=casos_rechazados,
        config_comite=config_comite,
        niveles_riesgo=niveles_riesgo
    )


@comite_bp.route("/admin/comite-credito/aprobar", methods=["POST"])
@login_required
@requiere_permiso("com_aprobar")
def aprobar_caso():
    """Aprobar un caso del comité"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import obtener_evaluacion_por_timestamp, actualizar_evaluacion
    from ..utils.timezone import obtener_hora_colombia
    from ..utils.formatting import parse_currency_value
    
    try:
        timestamp = request.form.get("timestamp")
        monto_aprobado = parse_currency_value(request.form.get("monto_aprobado"))
        nivel_riesgo_ajustado = request.form.get("nivel_riesgo_ajustado")
        comentario = request.form.get("comentario", "").strip()
        
        if not timestamp:
            flash("Timestamp no especificado", "error")
            return redirect(url_for("comite.comite_credito"))
        
        # Obtener evaluación
        evaluacion = obtener_evaluacion_por_timestamp(timestamp)
        
        if not evaluacion:
            flash("Evaluación no encontrada", "error")
            return redirect(url_for("comite.comite_credito"))
        
        if evaluacion.get("estado_comite") != "pending":
            flash("Este caso ya fue procesado", "error")
            return redirect(url_for("comite.comite_credito"))
        
        # Actualizar evaluación
        decision_admin = {
            "accion": "aprobar",
            "admin": session.get("username"),
            "timestamp": obtener_hora_colombia().isoformat(),
            "comentario": comentario,
            "monto_aprobado": monto_aprobado or evaluacion.get("monto_solicitado"),
            "nivel_riesgo_ajustado": nivel_riesgo_ajustado
        }
        
        actualizar_evaluacion(timestamp, {
            "estado_comite": "approved",
            "decision_admin": decision_admin,
            "monto_aprobado": monto_aprobado or evaluacion.get("monto_solicitado"),
            "nivel_riesgo_ajustado": nivel_riesgo_ajustado
        })
        
        flash(f"Caso aprobado para {evaluacion.get('nombre_cliente')}", "success")
        
    except Exception as e:
        traceback.print_exc()
        flash(f"Error al aprobar caso: {str(e)}", "error")
    
    return redirect(url_for("comite.comite_credito"))


@comite_bp.route("/admin/comite-credito/rechazar", methods=["POST"])
@login_required
@requiere_permiso("com_rechazar")
def rechazar_caso():
    """Rechazar un caso del comité"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import obtener_evaluacion_por_timestamp, actualizar_evaluacion
    from ..utils.timezone import obtener_hora_colombia
    
    try:
        timestamp = request.form.get("timestamp")
        motivo = request.form.get("motivo", "").strip()
        
        if not timestamp:
            flash("Timestamp no especificado", "error")
            return redirect(url_for("comite.comite_credito"))
        
        if not motivo:
            flash("El motivo de rechazo es requerido", "error")
            return redirect(url_for("comite.comite_credito"))
        
        # Obtener evaluación
        evaluacion = obtener_evaluacion_por_timestamp(timestamp)
        
        if not evaluacion:
            flash("Evaluación no encontrada", "error")
            return redirect(url_for("comite.comite_credito"))
        
        if evaluacion.get("estado_comite") != "pending":
            flash("Este caso ya fue procesado", "error")
            return redirect(url_for("comite.comite_credito"))
        
        # Actualizar evaluación
        decision_admin = {
            "accion": "rechazar",
            "admin": session.get("username"),
            "timestamp": obtener_hora_colombia().isoformat(),
            "motivo": motivo
        }
        
        actualizar_evaluacion(timestamp, {
            "estado_comite": "rejected",
            "decision_admin": decision_admin
        })
        
        flash(f"Caso rechazado para {evaluacion.get('nombre_cliente')}", "success")
        
    except Exception as e:
        traceback.print_exc()
        flash(f"Error al rechazar caso: {str(e)}", "error")
    
    return redirect(url_for("comite.comite_credito"))
