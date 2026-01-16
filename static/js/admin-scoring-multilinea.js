/**
 * ADMIN-SCORING-MULTILINEA.JS
 * ===========================
 *
 * JavaScript para gestionar el scoring por línea de crédito
 * en el panel de administración.
 *
 * Author: Sistema Loansi
 * Date: 2026-01-13
 */

// ============================================================================
// VARIABLES GLOBALES
// ============================================================================

let lineaSeleccionadaId = null;
let lineaSeleccionadaNombre = "";
let configScoringLinea = null;
let lineasCreditoDisponibles = [];

// ============================================================================
// INICIALIZACIÓN
// ============================================================================

document.addEventListener("DOMContentLoaded", function () {
  // Verificar si estamos en la pestaña de Scoring
  const scoringTab = document.getElementById("Scoring");
  if (scoringTab) {
    console.log("🔄 Inicializando scoring multi-línea...");
    // Inicializar selector de línea
    initSelectorLineaCredito();
  }
});

/**
 * Inicializa el selector de línea de crédito
 */
async function initSelectorLineaCredito() {
  console.log("🔄 Cargando líneas de crédito para scoring...");
  
  try {
    const response = await fetch("/api/scoring/lineas-credito", {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCSRFToken(),
      },
    });

    const data = await response.json();

    if (data.success) {
      console.log("✅ Líneas de crédito cargadas:", data.lineas.length);
      lineasCreditoDisponibles = data.lineas;
      renderSelectorLinea(data.lineas);

      // Seleccionar primera línea por defecto
      if (data.lineas.length > 0) {
        await seleccionarLineaCredito(data.lineas[0].id, data.lineas[0].nombre);
      }
    } else {
      console.error("❌ Error cargando líneas:", data.error);
      mostrarAlertaScoring("Error al cargar líneas de crédito", "danger");
    }
  } catch (error) {
    console.error("❌ Error en initSelectorLineaCredito:", error);
    mostrarAlertaScoring("Error de conexión", "danger");
  }
}

/**
 * Renderiza el selector de línea de crédito
 */
function renderSelectorLinea(lineas) {
  const container = document.getElementById("selectorLineaCreditoContainer");
  if (!container) {
    console.warn("Contenedor de selector no encontrado");
    return;
  }

  let html = `
        <div class="card mb-4 border-primary">
            <div class="card-header bg-primary text-white d-flex justify-content-between align-items-center">
                <span><i class="bi bi-box-seam me-2"></i>Línea de Crédito</span>
                <span class="badge bg-light text-primary fw-bold border border-primary" id="badgeLineaActual" style="font-size: 0.9rem;">Sin seleccionar</span>
            </div>
            <div class="card-body">
                <div class="row align-items-end">
                    <div class="col-md-6 mb-2 mb-md-0">
                        <label class="form-label fw-bold">Seleccionar línea para configurar:</label>
                        <select class="form-select form-select-lg" id="selectLineaCredito" 
                                onchange="onCambioLineaCredito(this.value)">
                            <option value="">-- Seleccione una línea --</option>
                            ${lineas
                              .map(
                                (l) => `
                                <option value="${l.id}" data-nombre="${
                                  l.nombre
                                }">
                                    ${l.nombre} ${
                                  l.tiene_config_scoring ? "✓" : "⚠️"
                                }
                                    (Score min: ${
                                      l.score_datacredito_minimo || "N/A"
                                    })
                                </option>
                            `
                              )
                              .join("")}
                        </select>
                    </div>
                    <div class="col-md-3 mb-2 mb-md-0">
                        <button type="button" class="btn btn-outline-secondary w-100" 
                                onclick="copiarConfiguracionModal()" 
                                ${lineas.length < 2 ? "disabled" : ""}>
                            <i class="bi bi-clipboard-plus me-1"></i>Copiar de otra línea
                        </button>
                    </div>
                    <div class="col-md-3">
                        <button type="button" class="btn btn-outline-info w-100" 
                                onclick="refrescarConfigLinea()">
                            <i class="bi bi-arrow-clockwise me-1"></i>Refrescar
                        </button>
                    </div>
                </div>
                
                <div id="infoLineaSeleccionada" class="mt-3" style="display:none;">
                    <div class="alert alert-info mb-0">
                        <div class="d-flex justify-content-between align-items-center">
                            <div>
                                <strong id="nombreLineaInfo">-</strong>
                                <span class="ms-2 text-muted" id="estadoConfigInfo">-</span>
                            </div>
                            <div class="text-end">
                                <span class="badge bg-secondary me-1" id="numNivelesInfo">0 niveles</span>
                                <span class="badge bg-secondary" id="numFactoresInfo">0 factores</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;

  container.innerHTML = html;
}

/**
 * Maneja el cambio de línea de crédito seleccionada
 */
async function onCambioLineaCredito(lineaId) {
  if (!lineaId) {
    lineaSeleccionadaId = null;
    lineaSeleccionadaNombre = "";
    configScoringLinea = null;
    ocultarContenidoScoring();
    return;
  }

  const select = document.getElementById("selectLineaCredito");
  const selectedOption = select.options[select.selectedIndex];
  const nombreLinea = selectedOption.dataset.nombre;

  await seleccionarLineaCredito(parseInt(lineaId), nombreLinea);
}

/**
 * Selecciona una línea de crédito y carga su configuración
 */
async function seleccionarLineaCredito(lineaId, nombreLinea) {
  console.log(`🔄 Cargando configuración de línea ${nombreLinea} (ID: ${lineaId})...`);
  
  try {
    lineaSeleccionadaId = lineaId;
    lineaSeleccionadaNombre = nombreLinea;

    // Actualizar UI del selector
    const select = document.getElementById("selectLineaCredito");
    if (select) {
      select.value = lineaId;
    }

    // Actualizar badge principal
    const badge = document.getElementById("badgeLineaActual");
    if (badge) {
      badge.textContent = nombreLinea;
    }
    
    // Actualizar badges en las pestañas
    const badgeNiveles = document.getElementById("badgeLineaNiveles");
    const badgeFactores = document.getElementById("badgeLineaFactores");
    if (badgeNiveles) badgeNiveles.textContent = nombreLinea;
    if (badgeFactores) badgeFactores.textContent = nombreLinea;

    // Cargar configuración de la línea
    const response = await fetch(`/api/scoring/linea/${lineaId}/config`, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCSRFToken(),
      },
    });

    const data = await response.json();

    if (data.success) {
      console.log(`✅ Configuración de ${nombreLinea} cargada correctamente`);
      configScoringLinea = data.config;

      // Actualizar info de línea
      actualizarInfoLinea(data.config);

      // Renderizar contenido de las pestañas
      renderNivelesRiesgoLinea(data.config.niveles_riesgo);
      renderFactoresRechazoLinea(data.config.factores_rechazo);
      renderConfigGeneralLinea(data.config.config_general);

      mostrarContenidoScoring();
      console.log(`✅ Línea ${nombreLinea} lista para editar`);
    } else {
      console.error("❌ Error cargando config:", data.error);
      mostrarAlertaScoring(
        `Error al cargar configuración: ${data.error}`,
        "danger"
      );
    }
  } catch (error) {
    console.error("❌ Error en seleccionarLineaCredito:", error);
    mostrarAlertaScoring("Error de conexión", "danger");
  }
}

/**
 * Actualiza la información de la línea seleccionada
 */
function actualizarInfoLinea(config) {
  const infoContainer = document.getElementById("infoLineaSeleccionada");
  const nombreInfo = document.getElementById("nombreLineaInfo");
  const estadoInfo = document.getElementById("estadoConfigInfo");
  const numNivelesInfo = document.getElementById("numNivelesInfo");
  const numFactoresInfo = document.getElementById("numFactoresInfo");

  if (!infoContainer) return;

  infoContainer.style.display = "block";

  if (nombreInfo) {
    nombreInfo.textContent =
      config.config_general?.linea_nombre || lineaSeleccionadaNombre;
  }

  if (estadoInfo) {
    const tieneConfig =
      config.niveles_riesgo && config.niveles_riesgo.length > 0;
    estadoInfo.innerHTML = tieneConfig
      ? '<span class="text-success"><i class="bi bi-check-circle"></i> Configuración activa</span>'
      : '<span class="text-warning"><i class="bi bi-exclamation-triangle"></i> Sin configuración específica</span>';
  }

  if (numNivelesInfo) {
    numNivelesInfo.textContent = `${
      config.niveles_riesgo?.length || 0
    } niveles`;
  }

  if (numFactoresInfo) {
    numFactoresInfo.textContent = `${
      config.factores_rechazo?.length || 0
    } factores`;
  }
}

// ============================================================================
// RENDERIZADO DE NIVELES DE RIESGO
// ============================================================================

/**
 * Renderiza los niveles de riesgo para la línea seleccionada
 */
function renderNivelesRiesgoLinea(niveles) {
  const container = document.getElementById("nivelesRiesgoLineaContainer");
  if (!container) return;

  // Header con botón agregar
  let html = `
    <div class="mb-3 d-flex justify-content-between align-items-center">
      <h6 class="mb-0">
        <i class="bi bi-bar-chart-steps me-2"></i>Niveles de Riesgo y Tasas Diferenciadas
        <span class="badge bg-primary text-white ms-2">${lineaSeleccionadaNombre}</span>
      </h6>
      <button type="button" class="btn btn-sm btn-outline-success" onclick="agregarNivelRiesgoLinea()">
        <i class="bi bi-plus-lg me-1"></i>Agregar nivel
      </button>
    </div>
  `;

  if (!niveles || niveles.length === 0) {
    html += `
            <div class="alert alert-warning">
                <i class="bi bi-exclamation-triangle me-2"></i>
                No hay niveles de riesgo configurados para esta línea.
                <button type="button" class="btn btn-sm btn-primary ms-2" 
                        onclick="crearNivelesRiesgoPorDefecto()">
                    Crear niveles por defecto
                </button>
            </div>
        `;
    container.innerHTML = html;
    return;
  }

  html += `<div class="row">`;

  niveles.forEach((nivel, index) => {
    html += `
            <div class="col-md-4 mb-3">
                <div class="card h-100" style="border-top: 4px solid ${
                  nivel.color
                };">
                    <div class="card-header d-flex justify-content-between align-items-center" style="background-color: ${
                      nivel.color
                    }20;">
                        <input type="text" class="form-control form-control-sm fw-bold flex-grow-1 me-2"
                               value="${nivel.nombre}"
                               onchange="actualizarNivelLinea(${index}, 'nombre', this.value)"
                               style="background: transparent; border: none;">
                        <button type="button" class="btn btn-sm btn-outline-danger" 
                                onclick="eliminarNivelRiesgoLinea(${index})" title="Eliminar nivel">
                            <i class="bi bi-trash"></i>
                        </button>
                    </div>
                    <div class="card-body">
                        <div class="row g-2 mb-3">
                            <div class="col-6">
                                <label class="form-label small">Score Mín</label>
                                <input type="number" class="form-control form-control-sm"
                                       value="${
                                         nivel.min
                                       }" min="0" max="100" step="0.1"
                                       onchange="actualizarNivelLinea(${index}, 'min', this.value)">
                            </div>
                            <div class="col-6">
                                <label class="form-label small">Score Máx</label>
                                <input type="number" class="form-control form-control-sm"
                                       value="${
                                         nivel.max
                                       }" min="0" max="100" step="0.1"
                                       onchange="actualizarNivelLinea(${index}, 'max', this.value)">
                            </div>
                        </div>
                        
                        <hr>
                        <h6 class="text-muted small">Tasas para ${lineaSeleccionadaNombre}</h6>
                        
                        <div class="mb-2">
                            <label class="form-label small">Tasa E.A. (%)</label>
                            <div class="input-group input-group-sm">
                                <input type="number" class="form-control" step="0.01"
                                       value="${nivel.tasa_ea}"
                                       onchange="actualizarNivelLinea(${index}, 'tasa_ea', this.value)">
                                <span class="input-group-text">%</span>
                            </div>
                        </div>
                        
                        <div class="mb-2">
                            <label class="form-label small">Tasa Nom. Mensual (%) <small class="text-info">(auto)</small></label>
                            <div class="input-group input-group-sm">
                                <input type="number" class="form-control bg-light" step="0.0001"
                                       value="${nivel.tasa_nominal_mensual}" readonly
                                       title="Se calcula automáticamente desde la Tasa E.A.">
                                <span class="input-group-text">%</span>
                            </div>
                        </div>
                        
                        <div class="mb-2">
                            <label class="form-label small">Aval (%)</label>
                            <div class="input-group input-group-sm">
                                <input type="number" class="form-control" step="0.01"
                                       value="${(
                                         nivel.aval_porcentaje * 100
                                       ).toFixed(2)}"
                                       onchange="actualizarNivelLinea(${index}, 'aval_porcentaje', this.value / 100)">
                                <span class="input-group-text">%</span>
                            </div>
                        </div>
                        
                        <div class="mt-3">
                            <label class="form-label small">Color</label>
                            <input type="color" class="form-control form-control-sm"
                                   value="${nivel.color}" style="height: 35px;"
                                   onchange="actualizarNivelLinea(${index}, 'color', this.value)">
                        </div>
                    </div>
                </div>
            </div>
        `;
  });

  html += `</div>`;

  // Botón guardar
  html += `
        <div class="mt-3 text-end">
            <button type="button" class="btn btn-outline-secondary me-2" 
                    onclick="refrescarConfigLinea()">
                <i class="bi bi-arrow-clockwise me-1"></i>Cancelar cambios
            </button>
            <button type="button" class="btn btn-primary" 
                    onclick="guardarNivelesRiesgoLinea()">
                <i class="bi bi-check-lg me-1"></i>Guardar niveles de riesgo
            </button>
        </div>
    `;

  container.innerHTML = html;
}

/**
 * Actualiza un campo de nivel de riesgo en memoria
 */
function actualizarNivelLinea(index, campo, valor) {
  if (!configScoringLinea || !configScoringLinea.niveles_riesgo) return;

  if (
    campo === "min" ||
    campo === "max" ||
    campo === "tasa_ea" ||
    campo === "tasa_nominal_mensual" ||
    campo === "aval_porcentaje"
  ) {
    valor = parseFloat(valor);
  }

  configScoringLinea.niveles_riesgo[index][campo] = valor;

  // Si cambió la tasa EA, calcular automáticamente la tasa nominal mensual
  if (campo === "tasa_ea") {
    const tasaEA = valor / 100; // Convertir a decimal
    // Fórmula: tasa_nominal_mensual = ((1 + tasa_ea)^(1/12) - 1) * 100
    const tasaNominalMensual = (Math.pow(1 + tasaEA, 1/12) - 1) * 100;
    configScoringLinea.niveles_riesgo[index].tasa_nominal_mensual = parseFloat(tasaNominalMensual.toFixed(4));
    // Re-renderizar para mostrar el nuevo valor
    renderNivelesRiesgoLinea(configScoringLinea.niveles_riesgo);
  }

  // Si cambió el color, actualizar visualmente
  if (campo === "color") {
    renderNivelesRiesgoLinea(configScoringLinea.niveles_riesgo);
  }
}

/**
 * Agrega un nuevo nivel de riesgo
 */
function agregarNivelRiesgoLinea() {
  if (!configScoringLinea) return;

  if (!configScoringLinea.niveles_riesgo) {
    configScoringLinea.niveles_riesgo = [];
  }

  // Determinar valores por defecto para el nuevo nivel
  const numNiveles = configScoringLinea.niveles_riesgo.length;
  const colores = ["#28a745", "#ffc107", "#fd7e14", "#dc3545", "#6c757d"];
  const nombres = ["Bajo Riesgo", "Moderado", "Alto Riesgo", "Muy Alto Riesgo", "Nivel " + (numNiveles + 1)];

  const nuevoNivel = {
    nombre: nombres[numNiveles] || "Nivel " + (numNiveles + 1),
    min: 0,
    max: 100,
    tasa_ea: 30,
    tasa_nominal_mensual: 2.21,
    aval_porcentaje: 0.10,
    color: colores[numNiveles] || "#6c757d"
  };

  configScoringLinea.niveles_riesgo.push(nuevoNivel);
  renderNivelesRiesgoLinea(configScoringLinea.niveles_riesgo);
  mostrarAlertaScoring("Nuevo nivel agregado. No olvide guardar los cambios.", "info");
}

/**
 * Elimina un nivel de riesgo
 */
function eliminarNivelRiesgoLinea(index) {
  if (!configScoringLinea || !configScoringLinea.niveles_riesgo) return;

  if (configScoringLinea.niveles_riesgo.length <= 1) {
    mostrarAlertaScoring("Debe mantener al menos un nivel de riesgo.", "warning");
    return;
  }

  const nivel = configScoringLinea.niveles_riesgo[index];
  if (confirm(`¿Está seguro de eliminar el nivel "${nivel.nombre}"?`)) {
    configScoringLinea.niveles_riesgo.splice(index, 1);
    renderNivelesRiesgoLinea(configScoringLinea.niveles_riesgo);
    mostrarAlertaScoring("Nivel eliminado. No olvide guardar los cambios.", "info");
  }
}

/**
 * Guarda los niveles de riesgo de la línea
 */
async function guardarNivelesRiesgoLinea() {
  if (!lineaSeleccionadaId || !configScoringLinea) {
    mostrarAlertaScoring("No hay línea seleccionada", "warning");
    return;
  }

  try {
    const response = await fetch(
      `/api/scoring/linea/${lineaSeleccionadaId}/niveles-riesgo`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCSRFToken(),
        },
        body: JSON.stringify({
          niveles: configScoringLinea.niveles_riesgo,
        }),
      }
    );

    const data = await response.json();

    if (data.success) {
      mostrarAlertaScoring(
        "Niveles de riesgo guardados exitosamente",
        "success"
      );
    } else {
      mostrarAlertaScoring(`Error: ${data.error}`, "danger");
    }
  } catch (error) {
    console.error("Error guardando niveles:", error);
    mostrarAlertaScoring("Error de conexión", "danger");
  }
}

/**
 * Crea niveles de riesgo por defecto para la línea
 */
async function crearNivelesRiesgoPorDefecto() {
  configScoringLinea.niveles_riesgo = [
    {
      nombre: "Bajo riesgo",
      codigo: "BAJO",
      min: 70.1,
      max: 100,
      tasa_ea: 22.0,
      tasa_nominal_mensual: 1.67,
      aval_porcentaje: 0.05,
      color: "#2ECC40",
      orden: 1,
    },
    {
      nombre: "Riesgo moderado",
      codigo: "MODERADO",
      min: 40.1,
      max: 70,
      tasa_ea: 24.0,
      tasa_nominal_mensual: 1.81,
      aval_porcentaje: 0.1,
      color: "#FFDC00",
      orden: 2,
    },
    {
      nombre: "Alto riesgo",
      codigo: "ALTO",
      min: 0,
      max: 40,
      tasa_ea: 30.0,
      tasa_nominal_mensual: 2.21,
      aval_porcentaje: 0.15,
      color: "#FF4136",
      orden: 3,
    },
  ];

  renderNivelesRiesgoLinea(configScoringLinea.niveles_riesgo);
  mostrarAlertaScoring(
    "Niveles por defecto creados. Recuerde guardar los cambios.",
    "info"
  );
}

// ============================================================================
// RENDERIZADO DE FACTORES DE RECHAZO
// ============================================================================

/**
 * Renderiza los factores de rechazo para la línea seleccionada
 */
function renderFactoresRechazoLinea(factores) {
  const container = document.getElementById("factoresRechazoLineaContainer");
  if (!container) return;

  let html = `
        <div class="mb-3 d-flex justify-content-between align-items-center">
            <h6 class="mb-0">
                <i class="bi bi-shield-x me-2"></i>Factores de rechazo automático 
                <span class="badge bg-secondary">${factores?.length || 0}</span>
            </h6>
            <button type="button" class="btn btn-sm btn-outline-primary" 
                    onclick="agregarFactorRechazoLinea()">
                <i class="bi bi-plus-lg me-1"></i>Agregar factor
            </button>
        </div>
    `;

  if (!factores || factores.length === 0) {
    html += `
            <div class="alert alert-warning">
                <i class="bi bi-exclamation-triangle me-2"></i>
                No hay factores de rechazo configurados para esta línea.
            </div>
        `;
  } else {
    html += `
            <div class="table-responsive">
                <table class="table table-sm table-hover">
                    <thead class="table-dark">
                        <tr>
                            <th style="width: 25%;">Criterio</th>
                            <th style="width: 15%;">Operador</th>
                            <th style="width: 15%;">Valor</th>
                            <th style="width: 35%;">Mensaje de rechazo</th>
                            <th style="width: 10%;" class="text-center">Acciones</th>
                        </tr>
                    </thead>
                    <tbody>
        `;

    factores.forEach((factor, index) => {
      html += `
                <tr data-factor-id="${factor.id || index}">
                    <td>
                        <input type="text" class="form-control form-control-sm"
                               value="${
                                 factor.criterio_nombre || factor.criterio
                               }"
                               onchange="actualizarFactorLinea(${index}, 'criterio_nombre', this.value)"
                               data-criterio-key="${factor.criterio}">
                    </td>
                    <td>
                        <select class="form-select form-select-sm"
                                onchange="actualizarFactorLinea(${index}, 'operador', this.value)">
                            <option value="<" ${
                              factor.operador === "<" ? "selected" : ""
                            }>< menor que</option>
                            <option value="<=" ${
                              factor.operador === "<=" ? "selected" : ""
                            }>≤ menor o igual</option>
                            <option value=">" ${
                              factor.operador === ">" ? "selected" : ""
                            }>> mayor que</option>
                            <option value=">=" ${
                              factor.operador === ">=" ? "selected" : ""
                            }>≥ mayor o igual</option>
                            <option value="=" ${
                              factor.operador === "=" ? "selected" : ""
                            }}>= igual a</option>
                        </select>
                    </td>
                    <td>
                        <input type="number" class="form-control form-control-sm"
                               value="${factor.valor}"
                               onchange="actualizarFactorLinea(${index}, 'valor', this.value)">
                    </td>
                    <td>
                        <input type="text" class="form-control form-control-sm"
                               value="${factor.mensaje || ""}"
                               onchange="actualizarFactorLinea(${index}, 'mensaje', this.value)">
                    </td>
                    <td class="text-center">
                        <button type="button" class="btn btn-sm btn-outline-danger"
                                onclick="eliminarFactorLinea(${index})" title="Eliminar">
                            <i class="bi bi-trash"></i>
                        </button>
                    </td>
                </tr>
            `;
    });

    html += `
                    </tbody>
                </table>
            </div>
        `;
  }

  // Botón guardar
  html += `
        <div class="mt-3 text-end">
            <button type="button" class="btn btn-primary" 
                    onclick="guardarFactoresRechazoLinea()">
                <i class="bi bi-check-lg me-1"></i>Guardar factores de rechazo
            </button>
        </div>
    `;

  container.innerHTML = html;
}

/**
 * Actualiza un campo de factor de rechazo en memoria
 */
function actualizarFactorLinea(index, campo, valor) {
  if (!configScoringLinea || !configScoringLinea.factores_rechazo) return;

  if (campo === "valor") {
    valor = parseFloat(valor);
  }

  configScoringLinea.factores_rechazo[index][campo] = valor;
}

/**
 * Agrega un nuevo factor de rechazo
 */
function agregarFactorRechazoLinea() {
  if (!configScoringLinea) return;

  if (!configScoringLinea.factores_rechazo) {
    configScoringLinea.factores_rechazo = [];
  }

  configScoringLinea.factores_rechazo.push({
    criterio: "nuevo_criterio",
    criterio_nombre: "Nuevo criterio",
    operador: "<",
    valor: 0,
    mensaje: "Mensaje de rechazo",
    activo: true,
  });

  renderFactoresRechazoLinea(configScoringLinea.factores_rechazo);
}

/**
 * Elimina un factor de rechazo
 */
function eliminarFactorLinea(index) {
  if (!configScoringLinea || !configScoringLinea.factores_rechazo) return;

  if (confirm("¿Está seguro de eliminar este factor de rechazo?")) {
    configScoringLinea.factores_rechazo.splice(index, 1);
    renderFactoresRechazoLinea(configScoringLinea.factores_rechazo);
  }
}

/**
 * Guarda los factores de rechazo de la línea
 */
async function guardarFactoresRechazoLinea() {
  if (!lineaSeleccionadaId || !configScoringLinea) {
    mostrarAlertaScoring("No hay línea seleccionada", "warning");
    return;
  }

  try {
    const response = await fetch(
      `/api/scoring/linea/${lineaSeleccionadaId}/factores-rechazo`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCSRFToken(),
        },
        body: JSON.stringify({
          factores: configScoringLinea.factores_rechazo,
        }),
      }
    );

    const data = await response.json();

    if (data.success) {
      mostrarAlertaScoring(
        "Factores de rechazo guardados exitosamente",
        "success"
      );
    } else {
      mostrarAlertaScoring(`Error: ${data.error}`, "danger");
    }
  } catch (error) {
    console.error("Error guardando factores:", error);
    mostrarAlertaScoring("Error de conexión", "danger");
  }
}

// ============================================================================
// RENDERIZADO DE CONFIGURACIÓN GENERAL
// ============================================================================

/**
 * Renderiza la configuración general de la línea
 */
function renderConfigGeneralLinea(config) {
  const container = document.getElementById("configGeneralLineaContainer");
  if (!container) return;

  const cg = config || {};

  let html = `
        <div class="row">
            <div class="col-md-6">
                <div class="card mb-3">
                    <div class="card-header">
                        <i class="bi bi-sliders me-2"></i>Parámetros de Aprobación
                    </div>
                    <div class="card-body">
                        <div class="mb-3">
                            <label class="form-label">Puntaje mínimo de aprobación</label>
                            <input type="number" class="form-control" id="cfgPuntajeMinimo"
                                   value="${
                                     cg.puntaje_minimo_aprobacion || 17
                                   }" min="0" max="100"
                                   onchange="actualizarConfigGeneral('puntaje_minimo_aprobacion', this.value)">
                            <small class="text-muted">Puntaje mínimo para aprobación automática</small>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Puntaje para revisión manual</label>
                            <input type="number" class="form-control" id="cfgPuntajeRevision"
                                   value="${
                                     cg.puntaje_revision_manual || 10
                                   }" min="0" max="100"
                                   onchange="actualizarConfigGeneral('puntaje_revision_manual', this.value)">
                            <small class="text-muted">Por debajo de este puntaje, va a comité</small>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Escala máxima</label>
                            <input type="number" class="form-control" id="cfgEscalaMax"
                                   value="${
                                     cg.escala_max || 100
                                   }" min="50" max="200"
                                   onchange="actualizarConfigGeneral('escala_max', this.value)">
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="col-md-6">
                <div class="card mb-3">
                    <div class="card-header">
                        <i class="bi bi-shield-check me-2"></i>Umbrales de Rechazo
                    </div>
                    <div class="card-body">
                        <div class="mb-3">
                            <label class="form-label">Score DataCrédito mínimo</label>
                            <input type="number" class="form-control" id="cfgScoreMin"
                                   value="${
                                     cg.score_datacredito_minimo || 400
                                   }" min="150" max="900"
                                   onchange="actualizarConfigGeneral('score_datacredito_minimo', this.value)">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Umbral mora telcos ($)</label>
                            <input type="number" class="form-control" id="cfgMoraTelcos"
                                   value="${
                                     cg.umbral_mora_telcos || 200000
                                   }" min="0" step="10000"
                                   onchange="actualizarConfigGeneral('umbral_mora_telcos', this.value)">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Consultas máx. (3 meses)</label>
                            <input type="number" class="form-control" id="cfgConsultasMax"
                                   value="${
                                     cg.consultas_max_3meses || 8
                                   }" min="1" max="20"
                                   onchange="actualizarConfigGeneral('consultas_max_3meses', this.value)">
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="row">
            <div class="col-md-6">
                <div class="card mb-3">
                    <div class="card-header">
                        <i class="bi bi-person me-2"></i>Requisitos del Cliente
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-6 mb-3">
                                <label class="form-label">Edad mínima</label>
                                <input type="number" class="form-control" id="cfgEdadMin"
                                       value="${
                                         cg.edad_minima || 18
                                       }" min="18" max="99"
                                       onchange="actualizarConfigGeneral('edad_minima', this.value)">
                            </div>
                            <div class="col-6 mb-3">
                                <label class="form-label">Edad máxima</label>
                                <input type="number" class="form-control" id="cfgEdadMax"
                                       value="${
                                         cg.edad_maxima || 84
                                       }" min="18" max="99"
                                       onchange="actualizarConfigGeneral('edad_maxima', this.value)">
                            </div>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">DTI máximo (%)</label>
                            <div class="input-group">
                                <input type="number" class="form-control" id="cfgDTI"
                                       value="${
                                         cg.dti_maximo || 50
                                       }" min="10" max="100"
                                       onchange="actualizarConfigGeneral('dti_maximo', this.value)">
                                <span class="input-group-text">%</span>
                            </div>
                            <small class="text-muted">Relación deuda/ingreso máxima</small>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="text-end">
            <button type="button" class="btn btn-primary" onclick="guardarConfigGeneralLinea()">
                <i class="bi bi-check-lg me-1"></i>Guardar configuración
            </button>
        </div>
    `;

  container.innerHTML = html;
}

/**
 * Actualiza un campo de configuración general en memoria
 */
function actualizarConfigGeneral(campo, valor) {
  if (!configScoringLinea || !configScoringLinea.config_general) return;

  configScoringLinea.config_general[campo] = parseFloat(valor);
}

/**
 * Guarda la configuración general de la línea
 */
async function guardarConfigGeneralLinea() {
  if (!lineaSeleccionadaId || !configScoringLinea) {
    mostrarAlertaScoring("No hay línea seleccionada", "warning");
    return;
  }

  try {
    const response = await fetch(
      `/api/scoring/linea/${lineaSeleccionadaId}/config`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCSRFToken(),
        },
        body: JSON.stringify({
          config_general: configScoringLinea.config_general,
        }),
      }
    );

    const data = await response.json();

    if (data.success) {
      mostrarAlertaScoring("Configuración guardada exitosamente", "success");
    } else {
      mostrarAlertaScoring(`Error: ${data.error}`, "danger");
    }
  } catch (error) {
    console.error("Error guardando config:", error);
    mostrarAlertaScoring("Error de conexión", "danger");
  }
}

// ============================================================================
// FUNCIONES DE UTILIDAD
// ============================================================================

/**
 * Refresca la configuración de la línea seleccionada
 */
async function refrescarConfigLinea() {
  if (lineaSeleccionadaId) {
    await seleccionarLineaCredito(lineaSeleccionadaId, lineaSeleccionadaNombre);
  }
}

/**
 * Muestra/oculta el contenido de scoring
 */
function mostrarContenidoScoring() {
  const containers = [
    "nivelesRiesgoLineaContainer",
    "factoresRechazoLineaContainer",
    "configGeneralLineaContainer",
  ];

  containers.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.style.display = "block";
  });
}

function ocultarContenidoScoring() {
  const containers = [
    "nivelesRiesgoLineaContainer",
    "factoresRechazoLineaContainer",
    "configGeneralLineaContainer",
  ];

  containers.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.style.display = "none";
  });

  const infoContainer = document.getElementById("infoLineaSeleccionada");
  if (infoContainer) infoContainer.style.display = "none";
}

/**
 * Muestra loading en el contenido de scoring
 */
function mostrarLoadingScoring(show) {
  const loadingId = "scoringLoadingOverlay";
  let loading = document.getElementById(loadingId);

  if (show) {
    if (!loading) {
      loading = document.createElement("div");
      loading.id = loadingId;
      loading.className =
        "position-fixed top-0 start-0 w-100 h-100 d-flex justify-content-center align-items-center";
      loading.style.cssText = "background: rgba(0,0,0,0.3); z-index: 9999;";
      loading.innerHTML = `
                <div class="spinner-border text-primary" role="status" style="width: 3rem; height: 3rem;">
                    <span class="visually-hidden">Cargando...</span>
                </div>
            `;
      document.body.appendChild(loading);
    }
    loading.style.display = "flex";
  } else if (loading) {
    loading.style.display = "none";
  }
}

/**
 * Muestra una alerta en el área de scoring
 */
function mostrarAlertaScoring(mensaje, tipo = "info", duracion = 5000) {
  const alertContainer = document.getElementById("scoringAlertContainer");
  if (!alertContainer) {
    // Crear contenedor si no existe
    const container = document.createElement("div");
    container.id = "scoringAlertContainer";
    container.className = "position-fixed top-0 end-0 p-3";
    container.style.cssText = "z-index: 9999; max-width: 400px;";
    document.body.appendChild(container);
  }

  const alertId = "alert_" + Date.now();
  const alertHtml = `
        <div id="${alertId}" class="alert alert-${tipo} alert-dismissible fade show" role="alert">
            ${mensaje}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;

  document
    .getElementById("scoringAlertContainer")
    .insertAdjacentHTML("beforeend", alertHtml);

  if (duracion > 0) {
    setTimeout(() => {
      const alert = document.getElementById(alertId);
      if (alert) {
        alert.classList.remove("show");
        setTimeout(() => alert.remove(), 150);
      }
    }, duracion);
  }
}

/**
 * Muestra el modal para copiar configuración
 */
function copiarConfiguracionModal() {
  console.log("📋 Abriendo modal copiar configuración...");
  console.log("📋 Línea seleccionada:", lineaSeleccionadaId, lineaSeleccionadaNombre);
  console.log("📋 Líneas disponibles:", lineasCreditoDisponibles.length);
  
  if (lineasCreditoDisponibles.length < 2) {
    mostrarAlertaScoring("Necesita al menos 2 líneas de crédito", "warning");
    return;
  }

  if (!lineaSeleccionadaId || !lineaSeleccionadaNombre) {
    mostrarAlertaScoring("Primero seleccione una línea de crédito destino", "warning");
    return;
  }

  // Eliminar TODOS los modales de copia existentes
  document.querySelectorAll('#copiarConfigModal').forEach(m => {
    try {
      const bsModal = bootstrap.Modal.getInstance(m);
      if (bsModal) bsModal.dispose();
    } catch(e) {}
    m.remove();
  });

  // Crear opciones del select (excluir línea actual)
  const opcionesOrigen = lineasCreditoDisponibles
    .filter((l) => l.id !== lineaSeleccionadaId)
    .map((l) => `<option value="${l.id}">${l.nombre}</option>`)
    .join("");
  
  console.log("📋 Opciones origen (excluye línea actual):", opcionesOrigen);

  const modalHtml = `
    <div class="modal fade" id="copiarConfigModal" tabindex="-1">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header bg-primary text-white">
            <h5 class="modal-title">
              <i class="bi bi-clipboard-plus me-2"></i>Copiar configuración
            </h5>
            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <div class="alert alert-info">
              <i class="bi bi-info-circle me-2"></i>
              Esta acción copiará niveles de riesgo, factores de rechazo y configuración general.
            </div>
            <div class="mb-3">
              <label class="form-label fw-bold">Copiar desde:</label>
              <select class="form-select" id="selectLineaOrigen">
                ${opcionesOrigen}
              </select>
            </div>
            <div class="mb-3">
              <label class="form-label fw-bold">Hacia (línea actual):</label>
              <input type="text" class="form-control bg-warning text-dark fw-bold" 
                     value="${lineaSeleccionadaNombre}" readonly>
              <input type="hidden" id="lineaDestinoId" value="${lineaSeleccionadaId}">
              <small class="text-muted">La configuración se copiará a esta línea</small>
            </div>
            <div class="form-check">
              <input type="checkbox" class="form-check-input" id="chkIncluirCriterios" checked>
              <label class="form-check-label" for="chkIncluirCriterios">
                Incluir criterios y pesos
              </label>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
            <button type="button" class="btn btn-primary" onclick="ejecutarCopiaConfig()">
              <i class="bi bi-clipboard-check me-1"></i>Copiar
            </button>
          </div>
        </div>
      </div>
    </div>
  `;
  
  document.body.insertAdjacentHTML("beforeend", modalHtml);
  const modal = document.getElementById("copiarConfigModal");
  new bootstrap.Modal(modal).show();
}

/**
 * Ejecuta la copia de configuración
 */
async function ejecutarCopiaConfig() {
  const origenId = document.getElementById("selectLineaOrigen").value;
  const destinoId = document.getElementById("lineaDestinoId").value;
  const incluirCriterios = document.getElementById(
    "chkIncluirCriterios"
  ).checked;

  if (!origenId || !destinoId) {
    mostrarAlertaScoring("Seleccione las líneas", "warning");
    return;
  }

  try {
    const response = await fetch("/api/scoring/copiar-config", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCSRFToken(),
      },
      body: JSON.stringify({
        linea_origen_id: parseInt(origenId),
        linea_destino_id: parseInt(destinoId),
        incluir_criterios: incluirCriterios,
      }),
    });

    const data = await response.json();

    if (data.success) {
      bootstrap.Modal.getInstance(
        document.getElementById("copiarConfigModal")
      ).hide();
      mostrarAlertaScoring("Configuración copiada exitosamente", "success");
      // Recargar configuración
      await refrescarConfigLinea();
    } else {
      mostrarAlertaScoring(`Error: ${data.error}`, "danger");
    }
  } catch (error) {
    console.error("Error copiando config:", error);
    mostrarAlertaScoring("Error de conexión", "danger");
  }
}

// ============================================================================
// HELPER PARA CSRF TOKEN
// ============================================================================

function getCSRFToken() {
  // Buscar en input hidden
  const tokenInput = document.querySelector('input[name="csrf_token"]');
  if (tokenInput) return tokenInput.value;

  // Buscar en meta tag
  const metaTag = document.querySelector('meta[name="csrf-token"]');
  if (metaTag) return metaTag.content;

  // Buscar en cualquier formulario
  const allTokens = document.querySelectorAll('input[name="csrf_token"]');
  if (allTokens.length > 0) return allTokens[0].value;

  console.warn("No se encontró token CSRF");
  return "";
}

// ============================================================================
// FUNCIONES PARA CRITERIOS POR LÍNEA (Pendiente implementación completa)
// ============================================================================

/**
 * Función placeholder para agregar criterio
 * La pestaña de criterios está oculta, esta función no debería llamarse
 */
function agregarCriterioLinea() {
  console.log("Función agregarCriterioLinea llamada - pestaña oculta");
}

/**
 * Renderiza los criterios de scoring para la línea seleccionada
 * @param {Array} criterios - Lista de criterios
 */
function renderCriteriosLinea(criterios) {
  const container = document.getElementById("criteriosLineaContainer");
  if (!container) return;

  // Los criterios se comparten entre líneas (catálogo maestro)
  let html = `
        <div class="alert alert-info mb-3">
            <i class="bi bi-info-circle me-2"></i>
            <strong>Criterios de Evaluación</strong>: Los criterios de scoring se aplican a todas las líneas
            de crédito. Lo que diferencia cada línea son los <strong>niveles de riesgo</strong> y los 
            <strong>factores de rechazo</strong> que puede configurar en las pestañas anteriores.
        </div>
    `;

  if (!criterios || Object.keys(criterios).length === 0) {
    html += `
            <div class="text-center py-4 text-muted">
                <i class="bi bi-inbox fs-1 d-block mb-2"></i>
                No hay criterios en el catálogo maestro.
            </div>
        `;
    container.innerHTML = html;
    return;
  }

  const criteriosArray = Object.entries(criterios);
  
  html += `
        <p class="text-muted small mb-3">
            <i class="bi bi-check-circle text-success me-1"></i>
            ${criteriosArray.length} criterios activos en el catálogo maestro
        </p>
        <div class="table-responsive">
            <table class="table table-sm table-hover">
                <thead class="table-light">
                    <tr>
                        <th>Criterio</th>
                        <th class="text-center">Peso</th>
                        <th>Tipo</th>
                        <th class="text-center">Rangos</th>
                    </tr>
                </thead>
                <tbody>
    `;
  
  criteriosArray.forEach(([codigo, c]) => {
    const numRangos = c.rangos ? c.rangos.length : 0;
    html += `
                <tr>
                    <td>
                        <strong>${c.nombre || codigo}</strong>
                        ${c.descripcion ? `<br><small class="text-muted">${c.descripcion}</small>` : ''}
                    </td>
                    <td class="text-center">${c.peso || 5}</td>
                    <td><span class="badge bg-secondary">${c.tipo_campo || 'numerico'}</span></td>
                    <td class="text-center">${numRangos}</td>
                </tr>
            `;
  });
  
  html += `
                </tbody>
            </table>
        </div>
    `;

  container.innerHTML = html;
}
