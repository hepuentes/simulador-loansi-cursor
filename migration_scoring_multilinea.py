#!/usr/bin/env python3
"""
MIGRATION_SCORING_MULTILINEA.PY
===============================

Script de migración para crear las tablas del sistema de scoring multi-línea.
Ejecutar UNA VEZ para crear las tablas necesarias.

Uso:
    python3 migration_scoring_multilinea.py

Author: Sistema Loansi
Date: 2026-01-15
"""

import sqlite3
import os
from datetime import datetime

# Ruta a la base de datos
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'loansi.db')


def conectar_db():
    """Conecta a la base de datos SQLite."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def crear_tablas():
    """Crea las tablas necesarias para scoring multi-línea."""
    conn = conectar_db()
    cursor = conn.cursor()
    
    print("=" * 60)
    print("MIGRACIÓN: Scoring Multi-Línea")
    print("=" * 60)
    print(f"Base de datos: {DB_PATH}")
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    try:
        # =====================================================================
        # TABLA 1: scoring_config_linea
        # Configuración general de scoring por línea de crédito
        # =====================================================================
        print("\n1. Creando tabla scoring_config_linea...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scoring_config_linea (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                linea_credito_id INTEGER NOT NULL,
                puntaje_minimo_aprobacion REAL DEFAULT 17,
                puntaje_revision_manual REAL DEFAULT 10,
                umbral_mora_telcos REAL DEFAULT 200000,
                edad_minima INTEGER DEFAULT 18,
                edad_maxima INTEGER DEFAULT 84,
                dti_maximo REAL DEFAULT 50,
                score_datacredito_minimo INTEGER DEFAULT 400,
                consultas_max_3meses INTEGER DEFAULT 8,
                escala_max INTEGER DEFAULT 100,
                activo INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (linea_credito_id) REFERENCES lineas_credito(id) ON DELETE CASCADE,
                UNIQUE(linea_credito_id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scoring_config_linea ON scoring_config_linea(linea_credito_id)")
        print("   ✅ Tabla scoring_config_linea creada")
        
        # =====================================================================
        # TABLA 2: niveles_riesgo_linea
        # Niveles de riesgo con tasas diferenciadas por línea
        # =====================================================================
        print("\n2. Creando tabla niveles_riesgo_linea...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS niveles_riesgo_linea (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                linea_credito_id INTEGER NOT NULL,
                nombre TEXT NOT NULL,
                codigo TEXT NOT NULL,
                score_min REAL NOT NULL,
                score_max REAL NOT NULL,
                tasa_ea REAL NOT NULL,
                tasa_nominal_mensual REAL NOT NULL,
                aval_porcentaje REAL DEFAULT 0,
                color TEXT DEFAULT '#dc3545',
                orden INTEGER DEFAULT 0,
                activo INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (linea_credito_id) REFERENCES lineas_credito(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_niveles_riesgo_linea ON niveles_riesgo_linea(linea_credito_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_niveles_riesgo_activo ON niveles_riesgo_linea(activo)")
        print("   ✅ Tabla niveles_riesgo_linea creada")
        
        # =====================================================================
        # TABLA 3: factores_rechazo_linea
        # Factores de rechazo automático por línea
        # =====================================================================
        print("\n3. Creando tabla factores_rechazo_linea...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS factores_rechazo_linea (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                linea_credito_id INTEGER NOT NULL,
                criterio_codigo TEXT NOT NULL,
                criterio_nombre TEXT NOT NULL,
                operador TEXT NOT NULL,
                valor_umbral REAL NOT NULL,
                mensaje_rechazo TEXT,
                activo INTEGER DEFAULT 1,
                orden INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (linea_credito_id) REFERENCES lineas_credito(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_factores_rechazo_linea ON factores_rechazo_linea(linea_credito_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_factores_rechazo_activo ON factores_rechazo_linea(activo)")
        print("   ✅ Tabla factores_rechazo_linea creada")
        
        # =====================================================================
        # TABLA 4: criterios_scoring_master
        # Catálogo maestro de criterios de scoring
        # =====================================================================
        print("\n4. Creando tabla criterios_scoring_master...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS criterios_scoring_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT UNIQUE NOT NULL,
                nombre TEXT NOT NULL,
                descripcion TEXT,
                tipo_campo TEXT DEFAULT 'number',
                seccion_id INTEGER DEFAULT 1,
                activo INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_criterios_master_codigo ON criterios_scoring_master(codigo)")
        print("   ✅ Tabla criterios_scoring_master creada")
        
        # =====================================================================
        # TABLA 5: criterios_linea_credito
        # Criterios configurados por línea de crédito
        # =====================================================================
        print("\n5. Creando tabla criterios_linea_credito...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS criterios_linea_credito (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                criterio_master_id INTEGER NOT NULL,
                linea_credito_id INTEGER NOT NULL,
                peso REAL DEFAULT 5,
                activo INTEGER DEFAULT 1,
                orden INTEGER DEFAULT 0,
                rangos_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (criterio_master_id) REFERENCES criterios_scoring_master(id) ON DELETE CASCADE,
                FOREIGN KEY (linea_credito_id) REFERENCES lineas_credito(id) ON DELETE CASCADE,
                UNIQUE(criterio_master_id, linea_credito_id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_criterios_linea_credito ON criterios_linea_credito(linea_credito_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_criterios_linea_master ON criterios_linea_credito(criterio_master_id)")
        print("   ✅ Tabla criterios_linea_credito creada")
        
        # =====================================================================
        # TABLA 6: secciones_scoring
        # Secciones para agrupar criterios
        # =====================================================================
        print("\n6. Creando tabla secciones_scoring...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS secciones_scoring (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                icono TEXT DEFAULT 'bi-gear',
                descripcion TEXT,
                orden INTEGER DEFAULT 0,
                activo INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("   ✅ Tabla secciones_scoring creada")
        
        conn.commit()
        
        print("\n" + "=" * 60)
        print("✅ MIGRACIÓN COMPLETADA EXITOSAMENTE")
        print("=" * 60)
        
        # Verificar tablas creadas
        print("\nTablas de scoring multi-línea:")
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' 
            AND (name LIKE '%scoring%' OR name LIKE '%linea%' OR name LIKE '%criterio%')
            ORDER BY name
        """)
        for row in cursor.fetchall():
            print(f"   ✅ {row[0]}")
        
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ ERROR EN MIGRACIÓN: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        conn.close()


def insertar_datos_iniciales():
    """Inserta datos iniciales si las tablas están vacías."""
    conn = conectar_db()
    cursor = conn.cursor()
    
    try:
        # Verificar si ya hay datos
        cursor.execute("SELECT COUNT(*) FROM scoring_config_linea")
        if cursor.fetchone()[0] > 0:
            print("\n⚠️  Las tablas ya tienen datos. No se insertarán datos iniciales.")
            return True
        
        print("\n📝 Insertando datos iniciales...")
        
        # Obtener IDs de líneas de crédito activas
        cursor.execute("SELECT id, nombre FROM lineas_credito WHERE activo = 1")
        lineas = cursor.fetchall()
        
        if not lineas:
            print("⚠️  No hay líneas de crédito activas.")
            return False
        
        for linea_id, linea_nombre in lineas:
            # Insertar configuración por defecto
            cursor.execute("""
                INSERT OR IGNORE INTO scoring_config_linea 
                (linea_credito_id, puntaje_minimo_aprobacion, score_datacredito_minimo, dti_maximo)
                VALUES (?, 17, 400, 50)
            """, (linea_id,))
            
            # Insertar niveles de riesgo por defecto
            niveles = [
                ('Bajo riesgo', 'BAJO', 70.1, 100, 22.0, 1.67, 0.05, '#2ECC40', 1),
                ('Riesgo moderado', 'MODERADO', 40.1, 70, 28.0, 2.07, 0.10, '#FFDC00', 2),
                ('Alto riesgo', 'ALTO', 0, 40, 45.0, 3.13, 0.15, '#FF4136', 3),
            ]
            
            for nivel in niveles:
                cursor.execute("""
                    INSERT OR IGNORE INTO niveles_riesgo_linea
                    (linea_credito_id, nombre, codigo, score_min, score_max, 
                     tasa_ea, tasa_nominal_mensual, aval_porcentaje, color, orden)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (linea_id,) + nivel)
            
            print(f"   ✅ Datos iniciales para {linea_nombre}")
        
        conn.commit()
        print("\n✅ Datos iniciales insertados")
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error insertando datos iniciales: {e}")
        return False
    finally:
        conn.close()


def verificar_migracion():
    """Verifica que la migración se completó correctamente."""
    conn = conectar_db()
    cursor = conn.cursor()
    
    print("\n" + "=" * 60)
    print("VERIFICACIÓN DE MIGRACIÓN")
    print("=" * 60)
    
    tablas_requeridas = [
        'scoring_config_linea',
        'niveles_riesgo_linea',
        'factores_rechazo_linea',
        'criterios_scoring_master',
        'criterios_linea_credito',
        'secciones_scoring'
    ]
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tablas_existentes = [row[0] for row in cursor.fetchall()]
    
    todas_existen = True
    for tabla in tablas_requeridas:
        if tabla in tablas_existentes:
            cursor.execute(f"SELECT COUNT(*) FROM {tabla}")
            count = cursor.fetchone()[0]
            print(f"   ✅ {tabla}: {count} registros")
        else:
            print(f"   ❌ {tabla}: NO EXISTE")
            todas_existen = False
    
    conn.close()
    
    if todas_existen:
        print("\n✅ Verificación completada: Todas las tablas existen")
    else:
        print("\n❌ Verificación fallida: Faltan tablas")
    
    return todas_existen


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("SCRIPT DE MIGRACIÓN - SCORING MULTI-LÍNEA")
    print("=" * 60)
    
    # Paso 1: Crear tablas
    if crear_tablas():
        # Paso 2: Insertar datos iniciales (opcional)
        insertar_datos_iniciales()
        
        # Paso 3: Verificar
        verificar_migracion()
    else:
        print("\n❌ La migración falló. Revise los errores anteriores.")
