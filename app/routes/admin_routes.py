"""
ADMIN_ROUTES.PY - Rutas de administración
==========================================
"""

from flask import render_template, request, redirect, url_for, session, jsonify, flash
from functools import wraps
import json
import traceback

from . import admin_bp


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


def requiere_rol(*roles_permitidos):
    """Decorador que requiere uno de los roles especificados"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get("autorizado"):
                return redirect(url_for("auth.login"))
            
            rol_actual = session.get("rol", "asesor")
            if rol_actual not in roles_permitidos:
                flash("No tienes permiso para acceder a esta sección", "error")
                return redirect(url_for("main.dashboard"))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


@admin_bp.route("")
@login_required
@requiere_permiso("admin_panel_acceso")
def admin_panel():
    """Panel principal de administración"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import cargar_configuracion, cargar_scoring, obtener_usuarios_completos
    from db_helpers_scoring_linea import obtener_lineas_credito_scoring
    
    config = cargar_configuracion()
    scoring = cargar_scoring()
    usuarios = obtener_usuarios_completos()
    
    lineas_credito = config.get("LINEAS_CREDITO", {})
    costos_asociados = config.get("COSTOS_ASOCIADOS", {})
    parametros_capacidad = config.get("PARAMETROS_CAPACIDAD_PAGO", {})
    config_comite = config.get("COMITE_CREDITO", {})
    
    # Obtener líneas con info de scoring
    lineas_scoring = obtener_lineas_credito_scoring()
    
    return render_template(
        "admin/admin.html",
        lineas_credito=lineas_credito,
        lineas_scoring=lineas_scoring,
        costos_asociados=costos_asociados,
        usuarios=usuarios,
        parametros_capacidad=parametros_capacidad,
        config_comite=config_comite,
        scoring=scoring
    )


@admin_bp.route("/historial-evaluaciones")
@login_required
@requiere_permiso("sco_hist_todos")
def historial_evaluaciones():
    """Historial de todas las evaluaciones"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import cargar_evaluaciones
    
    evaluaciones = cargar_evaluaciones()
    
    return render_template(
        "admin/historial_evaluaciones.html",
        evaluaciones=evaluaciones
    )


@admin_bp.route("/asignaciones-equipo", methods=["GET", "POST"])
@login_required
@requiere_permiso("usr_asignaciones_equipo")
def asignaciones_equipo():
    """Gestión de asignaciones de equipo"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import (
        get_all_assignments, 
        add_assignment, 
        remove_assignment_by_id,
        get_managers_for_assignments,
        get_members_for_assignments
    )
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "add":
            manager = request.form.get("manager")
            member = request.form.get("member")
            
            if manager and member:
                if add_assignment(manager, member):
                    flash(f"Asignación creada: {member} → {manager}", "success")
                else:
                    flash("Error al crear asignación", "error")
        
        elif action == "remove":
            assignment_id = request.form.get("assignment_id")
            if assignment_id:
                if remove_assignment_by_id(int(assignment_id)):
                    flash("Asignación eliminada", "success")
                else:
                    flash("Error al eliminar asignación", "error")
        
        return redirect(url_for("admin.asignaciones_equipo"))
    
    # GET: mostrar página
    asignaciones = get_all_assignments()
    managers = get_managers_for_assignments()
    members = get_members_for_assignments()
    
    return render_template(
        "admin/asignaciones_equipo.html",
        asignaciones=asignaciones,
        managers=managers,
        members=members
    )


@admin_bp.route("/usuario/nuevo", methods=["POST"])
@login_required
@requiere_permiso("usr_crear")
def crear_usuario():
    """Crear nuevo usuario"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import crear_usuario as db_crear_usuario
    from werkzeug.security import generate_password_hash
    
    try:
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        rol = request.form.get("rol", "asesor")
        nombre_completo = request.form.get("nombre_completo", "").strip()
        
        if not username or not password:
            flash("Usuario y contraseña son requeridos", "error")
            return redirect(url_for("admin.admin_panel"))
        
        password_hash = generate_password_hash(password)
        
        if db_crear_usuario(username, password_hash, rol, nombre_completo):
            flash(f"Usuario '{username}' creado exitosamente", "success")
        else:
            flash(f"El usuario '{username}' ya existe", "error")
        
    except Exception as e:
        flash(f"Error al crear usuario: {str(e)}", "error")
    
    return redirect(url_for("admin.admin_panel"))


@admin_bp.route("/usuario/cambiar-password", methods=["POST"])
@login_required
@requiere_permiso("usr_password")
def cambiar_password():
    """Cambiar contraseña de usuario"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import cargar_configuracion, guardar_configuracion
    from werkzeug.security import generate_password_hash
    
    try:
        username = request.form.get("username")
        new_password = request.form.get("new_password")
        
        if not username or not new_password:
            flash("Usuario y nueva contraseña son requeridos", "error")
            return redirect(url_for("admin.admin_panel"))
        
        config = cargar_configuracion()
        usuarios = config.get("USUARIOS", {})
        
        if username not in usuarios:
            flash(f"Usuario '{username}' no existe", "error")
            return redirect(url_for("admin.admin_panel"))
        
        usuarios[username]["password_hash"] = generate_password_hash(new_password)
        config["USUARIOS"] = usuarios
        guardar_configuracion(config)
        
        flash(f"Contraseña de '{username}' actualizada", "success")
        
    except Exception as e:
        flash(f"Error al cambiar contraseña: {str(e)}", "error")
    
    return redirect(url_for("admin.admin_panel"))


@admin_bp.route("/usuario/eliminar", methods=["POST"])
@login_required
@requiere_permiso("usr_eliminar")
def eliminar_usuario():
    """Eliminar usuario (soft delete)"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import eliminar_usuario_db
    
    try:
        username = request.form.get("username")
        
        if not username:
            flash("Usuario no especificado", "error")
            return redirect(url_for("admin.admin_panel"))
        
        if username == "admin":
            flash("No se puede eliminar el usuario admin", "error")
            return redirect(url_for("admin.admin_panel"))
        
        if username == session.get("username"):
            flash("No puedes eliminarte a ti mismo", "error")
            return redirect(url_for("admin.admin_panel"))
        
        if eliminar_usuario_db(username):
            flash(f"Usuario '{username}' eliminado", "success")
        else:
            flash(f"Error al eliminar usuario '{username}'", "error")
        
    except Exception as e:
        flash(f"Error al eliminar usuario: {str(e)}", "error")
    
    return redirect(url_for("admin.admin_panel"))


@admin_bp.route("/lineas/nueva", methods=["POST"])
@login_required
@requiere_permiso("cfg_lin_editar")
def crear_linea_credito():
    """Crear nueva línea de crédito"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import cargar_configuracion, guardar_configuracion
    from db_helpers_scoring_linea import crear_config_scoring_linea_defecto
    from ..utils.formatting import parse_currency_value
    
    try:
        nombre = request.form.get("nombre", "").strip()
        
        if not nombre:
            flash("El nombre de la línea es requerido", "error")
            return redirect(url_for("admin.admin_panel"))
        
        config = cargar_configuracion()
        lineas = config.get("LINEAS_CREDITO", {})
        
        if nombre in lineas:
            flash(f"La línea '{nombre}' ya existe", "error")
            return redirect(url_for("admin.admin_panel"))
        
        # Crear nueva línea
        tasa_anual = float(request.form.get("tasa_anual", 25))
        
        lineas[nombre] = {
            "descripcion": request.form.get("descripcion", ""),
            "monto_min": parse_currency_value(request.form.get("monto_min", 500000)),
            "monto_max": parse_currency_value(request.form.get("monto_max", 10000000)),
            "plazo_min": int(request.form.get("plazo_min", 1)),
            "plazo_max": int(request.form.get("plazo_max", 36)),
            "tasa_mensual": float(request.form.get("tasa_mensual", 2.0)),
            "tasa_anual": tasa_anual,
            "aval_porcentaje": float(request.form.get("aval_porcentaje", 0.10)),
            "plazo_tipo": request.form.get("plazo_tipo", "meses"),
            "permite_desembolso_neto": request.form.get("permite_desembolso_neto") == "on",
            "desembolso_por_defecto": request.form.get("desembolso_por_defecto", "completo")
        }
        
        config["LINEAS_CREDITO"] = lineas
        guardar_configuracion(config)
        
        # Crear configuración de scoring por defecto para la nueva línea
        # Primero necesitamos obtener el ID de la línea recién creada
        from database import conectar_db
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM lineas_credito WHERE nombre = ?", (nombre,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            linea_id = row[0]
            crear_config_scoring_linea_defecto(linea_id, tasa_anual)
        
        flash(f"Línea '{nombre}' creada exitosamente", "success")
        
    except Exception as e:
        traceback.print_exc()
        flash(f"Error al crear línea: {str(e)}", "error")
    
    return redirect(url_for("admin.admin_panel"))


@admin_bp.route("/lineas/eliminar", methods=["POST"])
@login_required
@requiere_permiso("cfg_lin_editar")
def eliminar_linea_credito():
    """Eliminar línea de crédito (soft delete)"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import eliminar_linea_credito_db
    
    try:
        nombre = request.form.get("nombre")
        
        if not nombre:
            flash("Nombre de línea no especificado", "error")
            return redirect(url_for("admin.admin_panel"))
        
        if eliminar_linea_credito_db(nombre):
            flash(f"Línea '{nombre}' eliminada", "success")
        else:
            flash(f"Error al eliminar línea '{nombre}'", "error")
        
    except Exception as e:
        flash(f"Error al eliminar línea: {str(e)}", "error")
    
    return redirect(url_for("admin.admin_panel"))


@admin_bp.route("/scoring/guardar", methods=["POST"])
@login_required
@requiere_permiso("cfg_sco_editar")
def guardar_scoring():
    """Guardar configuración de scoring"""
    import sys
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    
    from db_helpers import guardar_scoring as db_guardar_scoring
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No se recibieron datos"}), 400
        
        db_guardar_scoring(data)
        
        return jsonify({
            "success": True,
            "message": "Configuración de scoring guardada"
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
