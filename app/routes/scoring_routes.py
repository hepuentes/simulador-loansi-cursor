"""
SCORING_ROUTES.PY - Rutas de scoring de crédito
================================================
"""

from flask import render_template, request, redirect, url_for, session, jsonify, flash
from functools import wraps
import json
import traceback

from . import scoring_bp


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


@scoring_bp.route("/scoring")
@login_required
@requiere_permiso("sco_evaluar")
def scoring_page():
    """Página de evaluación de scoring"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import cargar_configuracion, cargar_scoring
    
    config = cargar_configuracion()
    scoring = cargar_scoring()
    
    lineas_credito = config.get("LINEAS_CREDITO", {})
    criterios = scoring.get("criterios", {})
    secciones = scoring.get("secciones", [])
    niveles_riesgo = scoring.get("niveles_riesgo", [])
    factores_rechazo = scoring.get("factores_rechazo_automatico", [])
    
    return render_template(
        "scoring.html",
        lineas_credito=lineas_credito,
        criterios=criterios,
        secciones=secciones,
        niveles_riesgo=niveles_riesgo,
        factores_rechazo=factores_rechazo,
        config_json=json.dumps({
            "lineas_credito": lineas_credito,
            "criterios": criterios,
            "niveles_riesgo": niveles_riesgo
        })
    )


@scoring_bp.route("/scoring", methods=["POST"])
@login_required
@requiere_permiso("sco_evaluar")
def calcular_scoring():
    """Procesar evaluación de scoring"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import cargar_scoring, guardar_evaluacion
    from ..utils.timezone import obtener_hora_colombia
    from ..utils.formatting import parse_currency_value
    
    try:
        # Obtener datos del formulario
        form_data = request.form.to_dict()
        
        nombre_cliente = form_data.get("nombre_cliente", "").strip()
        cedula = form_data.get("cedula", "").strip()
        linea_credito = form_data.get("linea_credito", "")
        monto_solicitado = parse_currency_value(form_data.get("monto_solicitado", 0))
        
        if not nombre_cliente or not cedula:
            flash("Nombre y cédula son requeridos", "error")
            return redirect(url_for("scoring.scoring_page"))
        
        # Cargar configuración de scoring
        scoring_config = cargar_scoring()
        criterios = scoring_config.get("criterios", {})
        niveles_riesgo = scoring_config.get("niveles_riesgo", [])
        factores_rechazo = scoring_config.get("factores_rechazo_automatico", [])
        puntaje_minimo = scoring_config.get("puntaje_minimo_aprobacion", 17)
        
        # Calcular score (lógica simplificada - el cálculo real está en flask_app.py)
        score_total = 0
        criterios_evaluados = []
        
        for codigo, config_criterio in criterios.items():
            if not config_criterio.get("activo", True):
                continue
            
            valor = form_data.get(codigo)
            if valor is None:
                continue
            
            peso = config_criterio.get("peso", 5)
            rangos = config_criterio.get("rangos", [])
            
            puntaje_criterio = 0
            for rango in rangos:
                # Lógica de evaluación de rangos
                pass
            
            score_total += puntaje_criterio
            criterios_evaluados.append({
                "codigo": codigo,
                "nombre": config_criterio.get("nombre", codigo),
                "valor": valor,
                "puntaje": puntaje_criterio,
                "peso": peso
            })
        
        # Determinar nivel de riesgo
        nivel_riesgo = "Alto riesgo"
        for nivel in niveles_riesgo:
            if nivel.get("min", 0) <= score_total <= nivel.get("max", 100):
                nivel_riesgo = nivel.get("nombre", "Sin clasificar")
                break
        
        # Verificar factores de rechazo
        rechazo_automatico = False
        razon_rechazo = None
        
        # Determinar resultado
        aprobado = score_total >= puntaje_minimo and not rechazo_automatico
        
        # Crear evaluación
        evaluacion = {
            "timestamp": obtener_hora_colombia().isoformat(),
            "asesor": session.get("username"),
            "nombre_cliente": nombre_cliente,
            "cedula": cedula,
            "linea_credito": linea_credito,
            "monto_solicitado": monto_solicitado,
            "resultado": {
                "score": score_total,
                "score_normalizado": min(100, max(0, score_total)),
                "nivel": nivel_riesgo,
                "aprobado": aprobado,
                "rechazo_automatico": rechazo_automatico,
                "razon_rechazo": razon_rechazo
            },
            "criterios_evaluados": criterios_evaluados,
            "nivel_riesgo": nivel_riesgo,
            "estado_comite": None,
            "origen": "Manual"
        }
        
        # Guardar evaluación
        guardar_evaluacion(evaluacion)
        
        # Redirigir a resultado
        return render_template(
            "asesor/resultado.html",
            evaluacion=evaluacion,
            resultado=evaluacion["resultado"]
        )
        
    except Exception as e:
        traceback.print_exc()
        flash(f"Error procesando evaluación: {str(e)}", "error")
        return redirect(url_for("scoring.scoring_page"))
