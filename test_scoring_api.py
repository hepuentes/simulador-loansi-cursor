#!/usr/bin/env python3
"""
Test script para verificar las funciones de scoring multi-línea.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db_helpers_scoring_linea import (
    obtener_lineas_credito_scoring,
    obtener_config_scoring_linea,
    obtener_niveles_riesgo_linea,
    obtener_factores_rechazo_linea,
    verificar_tablas_scoring_linea,
    cargar_scoring_por_linea
)

def test_all():
    print("=" * 60)
    print("TEST: Verificando funciones de scoring multi-línea")
    print("=" * 60)
    
    # Test 1: Verificar tablas
    print("\n1. Verificando tablas...")
    if verificar_tablas_scoring_linea():
        print("   ✅ Todas las tablas existen")
    else:
        print("   ❌ Faltan tablas")
        return False
    
    # Test 2: Obtener líneas de crédito
    print("\n2. Obteniendo líneas de crédito con scoring...")
    lineas = obtener_lineas_credito_scoring()
    if lineas:
        print(f"   ✅ {len(lineas)} líneas encontradas:")
        for linea in lineas:
            print(f"      - {linea['nombre']} (ID: {linea['id']}, Score min: {linea.get('score_datacredito_minimo', 'N/A')})")
    else:
        print("   ❌ No se encontraron líneas")
        return False
    
    # Test 3: Obtener configuración de LoansiMoto (id=7)
    print("\n3. Obteniendo configuración de LoansiMoto (id=7)...")
    config = obtener_config_scoring_linea(7)
    if config and config.get('config_general'):
        cg = config['config_general']
        print(f"   ✅ Configuración encontrada:")
        print(f"      - Línea: {cg.get('linea_nombre')}")
        print(f"      - Score DataCrédito mínimo: {cg.get('score_datacredito_minimo')}")
        print(f"      - DTI máximo: {cg.get('dti_maximo')}%")
        print(f"      - Puntaje mínimo aprobación: {cg.get('puntaje_minimo_aprobacion')}")
    else:
        print("   ⚠️ Configuración vacía o con valores por defecto")
    
    # Test 4: Obtener niveles de riesgo
    print("\n4. Obteniendo niveles de riesgo de LoansiMoto...")
    niveles = obtener_niveles_riesgo_linea(7)
    if niveles:
        print(f"   ✅ {len(niveles)} niveles encontrados:")
        for nivel in niveles:
            print(f"      - {nivel.get('nombre')}: Score {nivel.get('min')}-{nivel.get('max')}, Tasa {nivel.get('tasa_ea')}%")
    else:
        print("   ⚠️ No se encontraron niveles de riesgo")
    
    # Test 5: Obtener factores de rechazo
    print("\n5. Obteniendo factores de rechazo de LoansiMoto...")
    factores = obtener_factores_rechazo_linea(7)
    if factores:
        print(f"   ✅ {len(factores)} factores encontrados:")
        for f in factores[:5]:  # Mostrar solo los primeros 5
            print(f"      - {f.get('criterio_nombre')}: {f.get('operador')} {f.get('valor')}")
        if len(factores) > 5:
            print(f"      ... y {len(factores) - 5} más")
    else:
        print("   ⚠️ No se encontraron factores de rechazo")
    
    # Test 6: Cargar scoring por nombre de línea
    print("\n6. Cargando scoring por nombre 'LoansiMoto'...")
    scoring = cargar_scoring_por_linea('LoansiMoto')
    if scoring:
        print(f"   ✅ Scoring cargado:")
        print(f"      - Línea ID: {scoring.get('linea_credito_id')}")
        print(f"      - Puntaje mínimo: {scoring.get('puntaje_minimo_aprobacion')}")
        print(f"      - Niveles de riesgo: {len(scoring.get('niveles_riesgo', []))}")
        print(f"      - Factores de rechazo: {len(scoring.get('factores_rechazo_automatico', []))}")
    else:
        print("   ⚠️ No se pudo cargar scoring por nombre")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETADO")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = test_all()
    sys.exit(0 if success else 1)
