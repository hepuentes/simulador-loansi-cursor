-- =============================================================================
-- UPDATE_SCORING_CONFIG.SQL
-- Actualiza configuración de scoring multi-línea según especificaciones
-- =============================================================================

-- Primero eliminamos duplicados de niveles de riesgo
DELETE FROM niveles_riesgo_linea WHERE id NOT IN (
    SELECT MIN(id) FROM niveles_riesgo_linea 
    GROUP BY linea_credito_id, codigo
);

-- Eliminar duplicados de factores de rechazo
DELETE FROM factores_rechazo_linea WHERE id NOT IN (
    SELECT MIN(id) FROM factores_rechazo_linea 
    GROUP BY linea_credito_id, criterio_codigo, operador, valor_umbral
);

-- =============================================================================
-- ACTUALIZAR CONFIGURACIÓN GENERAL - LoansiMoto (id=7)
-- =============================================================================
UPDATE scoring_config_linea SET
    score_datacredito_minimo = 400,
    dti_maximo = 55.0,
    puntaje_minimo_aprobacion = 70,
    puntaje_revision_manual = 50,
    edad_minima = 21,
    edad_maxima = 65,
    consultas_max_3meses = 8,
    umbral_mora_telcos = 400000,
    updated_at = CURRENT_TIMESTAMP
WHERE linea_credito_id = 7;

-- =============================================================================
-- ACTUALIZAR CONFIGURACIÓN GENERAL - LoansiFlex (id=5)
-- =============================================================================
UPDATE scoring_config_linea SET
    score_datacredito_minimo = 450,
    dti_maximo = 50.0,
    puntaje_minimo_aprobacion = 75,
    puntaje_revision_manual = 55,
    edad_minima = 22,
    edad_maxima = 60,
    consultas_max_3meses = 6,
    umbral_mora_telcos = 300000,
    updated_at = CURRENT_TIMESTAMP
WHERE linea_credito_id = 5;

-- =============================================================================
-- ACTUALIZAR CONFIGURACIÓN GENERAL - Microflex (id=6)
-- =============================================================================
UPDATE scoring_config_linea SET
    score_datacredito_minimo = 350,
    dti_maximo = 60.0,
    puntaje_minimo_aprobacion = 65,
    puntaje_revision_manual = 45,
    edad_minima = 18,
    edad_maxima = 70,
    consultas_max_3meses = 10,
    umbral_mora_telcos = 200000,
    updated_at = CURRENT_TIMESTAMP
WHERE linea_credito_id = 6;

-- =============================================================================
-- ACTUALIZAR NIVELES DE RIESGO - LoansiMoto (id=7)
-- Eliminar existentes y recrear con valores correctos
-- =============================================================================
DELETE FROM niveles_riesgo_linea WHERE linea_credito_id = 7;

INSERT INTO niveles_riesgo_linea (linea_credito_id, nombre, codigo, score_min, score_max, tasa_ea, tasa_nominal_mensual, aval_porcentaje, color, orden, activo) VALUES
(7, 'Premium', 'PREMIUM', 70.1, 100.0, 22.0, 1.67, 0.05, '#2ECC40', 1, 1),
(7, 'Estándar', 'ESTANDAR', 55.1, 70.0, 26.0, 1.94, 0.08, '#3D9970', 2, 1),
(7, 'Alto riesgo', 'ALTO', 45.1, 55.0, 40.0, 2.84, 0.12, '#FFDC00', 3, 1),
(7, 'Rescate', 'RESCATE', 0.0, 45.0, 57.5, 3.84, 0.135, '#FF4136', 4, 1);

-- =============================================================================
-- ACTUALIZAR NIVELES DE RIESGO - LoansiFlex (id=5)
-- =============================================================================
DELETE FROM niveles_riesgo_linea WHERE linea_credito_id = 5;

INSERT INTO niveles_riesgo_linea (linea_credito_id, nombre, codigo, score_min, score_max, tasa_ea, tasa_nominal_mensual, aval_porcentaje, color, orden, activo) VALUES
(5, 'Premium', 'PREMIUM', 70.1, 100.0, 23.0, 1.73, 0.065, '#2ECC40', 1, 1),
(5, 'Estándar', 'ESTANDAR', 55.1, 70.0, 25.0, 1.88, 0.10, '#3D9970', 2, 1),
(5, 'Alto riesgo', 'ALTO', 45.1, 55.0, 50.0, 3.44, 0.15, '#FF851B', 3, 1);

-- =============================================================================
-- ACTUALIZAR NIVELES DE RIESGO - Microflex (id=6)
-- =============================================================================
DELETE FROM niveles_riesgo_linea WHERE linea_credito_id = 6;

INSERT INTO niveles_riesgo_linea (linea_credito_id, nombre, codigo, score_min, score_max, tasa_ea, tasa_nominal_mensual, aval_porcentaje, color, orden, activo) VALUES
(6, 'Bajo riesgo', 'BAJO', 65.1, 100.0, 45.0, 3.13, 0.05, '#2ECC40', 1, 1),
(6, 'Riesgo moderado', 'MODERADO', 45.1, 65.0, 55.0, 3.71, 0.08, '#FFDC00', 2, 1),
(6, 'Alto riesgo', 'ALTO', 0.0, 45.0, 65.0, 4.26, 0.10, '#FF4136', 3, 1);

-- =============================================================================
-- ACTUALIZAR FACTORES DE RECHAZO - LoansiMoto (id=7)
-- Eliminar existentes y recrear
-- =============================================================================
DELETE FROM factores_rechazo_linea WHERE linea_credito_id = 7;

INSERT INTO factores_rechazo_linea (linea_credito_id, criterio_codigo, criterio_nombre, operador, valor_umbral, mensaje_rechazo, activo, orden) VALUES
(7, 'score_datacredito', 'Score DataCrédito', '<', 400, 'Score DataCrédito inferior a 400 puntos', 1, 1),
(7, 'mora_activa_financiero', 'Mora activa sector financiero', '>', 45, 'Mora activa financiera superior a 45 días', 1, 2),
(7, 'mora_telcos', 'Mora en telecomunicaciones', '>', 400000, 'Mora en telcos superior a $400,000', 1, 3),
(7, 'mora_telcos_dias', 'Mora telcos (días)', '>', 90, 'Mora en telcos superior a 90 días', 1, 4),
(7, 'dti', 'Relación deuda/ingreso (DTI)', '>', 55, 'DTI superior al 55%', 1, 5),
(7, 'obligaciones_castigo', 'Obligaciones en castigo', '>', 1, 'Más de 1 obligación en castigo', 1, 6),
(7, 'consultas_3meses', 'Consultas últimos 3 meses', '>', 8, 'Más de 8 consultas en últimos 3 meses', 1, 7),
(7, 'edad_minima', 'Edad mínima', '<', 21, 'Edad mínima requerida: 21 años', 1, 8),
(7, 'edad_maxima', 'Edad máxima', '>', 65, 'Edad máxima permitida: 65 años', 1, 9),
(7, 'verificacion_sarlaft', 'Verificación SARLAFT', '=', 1, 'Coincidencia en listas SARLAFT', 1, 10),
(7, 'validacion_identidad', 'Validación de identidad', '=', 0, 'Validación de identidad fallida', 1, 11);

-- =============================================================================
-- ACTUALIZAR FACTORES DE RECHAZO - LoansiFlex (id=5)
-- =============================================================================
DELETE FROM factores_rechazo_linea WHERE linea_credito_id = 5;

INSERT INTO factores_rechazo_linea (linea_credito_id, criterio_codigo, criterio_nombre, operador, valor_umbral, mensaje_rechazo, activo, orden) VALUES
(5, 'score_datacredito', 'Score DataCrédito', '<', 450, 'Score DataCrédito inferior a 450 puntos', 1, 1),
(5, 'mora_activa_financiero', 'Mora activa sector financiero', '>', 30, 'Mora activa financiera superior a 30 días', 1, 2),
(5, 'mora_telcos', 'Mora en telecomunicaciones', '>', 300000, 'Mora en telcos superior a $300,000', 1, 3),
(5, 'mora_telcos_dias', 'Mora telcos (días)', '>', 60, 'Mora en telcos superior a 60 días', 1, 4),
(5, 'dti', 'Relación deuda/ingreso (DTI)', '>', 50, 'DTI superior al 50%', 1, 5),
(5, 'obligaciones_castigo', 'Obligaciones en castigo', '>', 0, 'No se permiten obligaciones en castigo', 1, 6),
(5, 'consultas_3meses', 'Consultas últimos 3 meses', '>', 6, 'Más de 6 consultas en últimos 3 meses', 1, 7),
(5, 'edad_minima', 'Edad mínima', '<', 22, 'Edad mínima requerida: 22 años', 1, 8),
(5, 'edad_maxima', 'Edad máxima', '>', 60, 'Edad máxima permitida: 60 años', 1, 9),
(5, 'verificacion_sarlaft', 'Verificación SARLAFT', '=', 1, 'Coincidencia en listas SARLAFT', 1, 10),
(5, 'validacion_identidad', 'Validación de identidad', '=', 0, 'Validación de identidad fallida', 1, 11);

-- =============================================================================
-- ACTUALIZAR FACTORES DE RECHAZO - Microflex (id=6)
-- =============================================================================
DELETE FROM factores_rechazo_linea WHERE linea_credito_id = 6;

INSERT INTO factores_rechazo_linea (linea_credito_id, criterio_codigo, criterio_nombre, operador, valor_umbral, mensaje_rechazo, activo, orden) VALUES
(6, 'score_datacredito', 'Score DataCrédito', '<', 350, 'Score DataCrédito inferior a 350 puntos', 1, 1),
(6, 'mora_activa_financiero', 'Mora activa sector financiero', '>', 60, 'Mora activa financiera superior a 60 días', 1, 2),
(6, 'mora_telcos', 'Mora en telecomunicaciones', '>', 200000, 'Mora en telcos superior a $200,000', 1, 3),
(6, 'mora_telcos_dias', 'Mora telcos (días)', '>', 90, 'Mora en telcos superior a 90 días', 1, 4),
(6, 'dti', 'Relación deuda/ingreso (DTI)', '>', 60, 'DTI superior al 60%', 1, 5),
(6, 'edad_minima', 'Edad mínima', '<', 18, 'Edad mínima requerida: 18 años', 1, 6),
(6, 'edad_maxima', 'Edad máxima', '>', 70, 'Edad máxima permitida: 70 años', 1, 7);

-- Verificar resultados
SELECT '=== CONFIG SCORING ACTUALIZADA ===' as info;
SELECT lc.nombre, sc.score_datacredito_minimo as score_min, sc.dti_maximo as dti_max, 
       sc.puntaje_minimo_aprobacion as puntaje_aprob, sc.puntaje_revision_manual as puntaje_rev
FROM scoring_config_linea sc
JOIN lineas_credito lc ON sc.linea_credito_id = lc.id
WHERE lc.activo = 1;

SELECT '=== NIVELES RIESGO ===' as info;
SELECT lc.nombre, nr.nombre as nivel, nr.score_min, nr.score_max, nr.tasa_ea
FROM niveles_riesgo_linea nr
JOIN lineas_credito lc ON nr.linea_credito_id = lc.id
WHERE lc.activo = 1 AND nr.activo = 1
ORDER BY lc.nombre, nr.orden;

SELECT '=== FACTORES RECHAZO (conteo) ===' as info;
SELECT lc.nombre, COUNT(*) as num_factores
FROM factores_rechazo_linea fr
JOIN lineas_credito lc ON fr.linea_credito_id = lc.id
WHERE lc.activo = 1 AND fr.activo = 1
GROUP BY lc.nombre;
