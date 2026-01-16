"""
SCORING_SERVICE.PY - Servicio de cálculo de scoring de crédito
===============================================================
"""

import json
from datetime import datetime


class ScoringService:
    """
    Servicio para cálculos de scoring de crédito.
    Centraliza toda la lógica de evaluación de riesgo crediticio.
    """
    
    def __init__(self, scoring_config=None):
        """
        Inicializa el servicio de scoring.
        
        Args:
            scoring_config: Configuración de scoring (opcional)
        """
        self.config = scoring_config or {}
        self.criterios = self.config.get("criterios", {})
        self.niveles_riesgo = self.config.get("niveles_riesgo", [])
        self.factores_rechazo = self.config.get("factores_rechazo_automatico", [])
        self.puntaje_minimo = self.config.get("puntaje_minimo_aprobacion", 17)
        self.escala_max = self.config.get("escala_max", 100)
    
    def cargar_config(self, linea_credito=None):
        """
        Carga la configuración de scoring desde la base de datos.
        
        Args:
            linea_credito: Nombre de la línea de crédito (opcional)
        """
        import sys
        from pathlib import Path
        BASE_DIR = Path(__file__).parent.parent.parent.resolve()
        if str(BASE_DIR) not in sys.path:
            sys.path.insert(0, str(BASE_DIR))
        
        from db_helpers import cargar_scoring
        from db_helpers_scoring_linea import cargar_scoring_por_linea
        
        if linea_credito:
            # Intentar cargar configuración específica de la línea
            config_linea = cargar_scoring_por_linea(linea_credito)
            if config_linea:
                self.config = config_linea
            else:
                self.config = cargar_scoring()
        else:
            self.config = cargar_scoring()
        
        # Actualizar referencias
        self.criterios = self.config.get("criterios", {})
        self.niveles_riesgo = self.config.get("niveles_riesgo", [])
        self.factores_rechazo = self.config.get("factores_rechazo_automatico", [])
        self.puntaje_minimo = self.config.get("puntaje_minimo_aprobacion", 17)
        self.escala_max = self.config.get("escala_max", 100)
    
    def evaluar_criterio(self, codigo, valor, criterio_config):
        """
        Evalúa un criterio individual.
        
        Args:
            codigo: Código del criterio
            valor: Valor a evaluar
            criterio_config: Configuración del criterio
            
        Returns:
            dict: {puntaje, detalle, ...}
        """
        if not criterio_config.get("activo", True):
            return {"puntaje": 0, "evaluado": False}
        
        peso = criterio_config.get("peso", 5)
        rangos = criterio_config.get("rangos", [])
        tipo_campo = criterio_config.get("tipo_campo", "numerico")
        
        puntaje = 0
        detalle = ""
        
        # Convertir valor según tipo
        if tipo_campo == "numerico":
            try:
                valor_num = float(str(valor).replace(",", ".").replace("$", "").replace(".", ""))
            except (ValueError, TypeError):
                valor_num = 0
            
            # Buscar rango que aplica
            for rango in rangos:
                min_val = rango.get("min", float("-inf"))
                max_val = rango.get("max", float("inf"))
                
                if min_val <= valor_num <= max_val:
                    puntaje = rango.get("puntaje", 0)
                    detalle = rango.get("descripcion", "")
                    break
        
        elif tipo_campo == "seleccion":
            # Buscar opción seleccionada
            for rango in rangos:
                if str(rango.get("valor", "")).lower() == str(valor).lower():
                    puntaje = rango.get("puntaje", 0)
                    detalle = rango.get("descripcion", "")
                    break
        
        elif tipo_campo == "booleano":
            valor_bool = str(valor).lower() in ["true", "1", "si", "sí", "yes"]
            for rango in rangos:
                if rango.get("valor") == valor_bool:
                    puntaje = rango.get("puntaje", 0)
                    detalle = rango.get("descripcion", "")
                    break
        
        # Aplicar peso
        puntaje_ponderado = puntaje * (peso / 100.0)
        
        return {
            "puntaje": puntaje,
            "puntaje_ponderado": puntaje_ponderado,
            "peso": peso,
            "detalle": detalle,
            "evaluado": True,
            "valor_original": valor
        }
    
    def verificar_rechazo_automatico(self, valores):
        """
        Verifica si hay factores de rechazo automático.
        
        Args:
            valores: Dict con valores de los criterios
            
        Returns:
            dict: {rechazo: bool, razon: str, factor: str}
        """
        for factor in self.factores_rechazo:
            criterio = factor.get("criterio")
            operador = factor.get("operador", "<")
            umbral = factor.get("valor", 0)
            mensaje = factor.get("mensaje", "Rechazo automático")
            
            if criterio not in valores:
                continue
            
            valor = valores[criterio]
            
            # Convertir a número si es posible
            try:
                valor_num = float(str(valor).replace(",", "."))
                umbral_num = float(umbral)
            except (ValueError, TypeError):
                continue
            
            # Evaluar condición
            rechazado = False
            if operador == "<" and valor_num < umbral_num:
                rechazado = True
            elif operador == "<=" and valor_num <= umbral_num:
                rechazado = True
            elif operador == ">" and valor_num > umbral_num:
                rechazado = True
            elif operador == ">=" and valor_num >= umbral_num:
                rechazado = True
            elif operador == "==" and valor_num == umbral_num:
                rechazado = True
            
            if rechazado:
                return {
                    "rechazo": True,
                    "razon": mensaje,
                    "factor": criterio,
                    "valor": valor,
                    "umbral": umbral
                }
        
        return {"rechazo": False, "razon": None, "factor": None}
    
    def determinar_nivel_riesgo(self, score):
        """
        Determina el nivel de riesgo según el score.
        
        Args:
            score: Score calculado
            
        Returns:
            dict: Info del nivel de riesgo
        """
        for nivel in self.niveles_riesgo:
            min_score = nivel.get("min", 0)
            max_score = nivel.get("max", 100)
            
            if min_score <= score <= max_score:
                return {
                    "nombre": nivel.get("nombre", "Sin clasificar"),
                    "color": nivel.get("color", "#808080"),
                    "tasa_ea": nivel.get("tasa_ea"),
                    "tasa_nominal_mensual": nivel.get("tasa_nominal_mensual"),
                    "aval_porcentaje": nivel.get("aval_porcentaje"),
                    "min": min_score,
                    "max": max_score
                }
        
        return {
            "nombre": "Sin clasificar",
            "color": "#808080",
            "tasa_ea": None,
            "tasa_nominal_mensual": None,
            "aval_porcentaje": None
        }
    
    def calcular_scoring(self, valores, linea_credito=None):
        """
        Calcula el scoring completo.
        
        Args:
            valores: Dict con valores de todos los criterios
            linea_credito: Línea de crédito (opcional)
            
        Returns:
            dict: Resultado completo del scoring
        """
        # Cargar configuración si es necesario
        if linea_credito or not self.criterios:
            self.cargar_config(linea_credito)
        
        # 1. Verificar rechazo automático
        rechazo = self.verificar_rechazo_automatico(valores)
        
        # 2. Evaluar todos los criterios
        evaluaciones = []
        score_total = 0
        peso_total = 0
        
        for codigo, config in self.criterios.items():
            if not config.get("activo", True):
                continue
            
            valor = valores.get(codigo)
            if valor is None:
                continue
            
            resultado = self.evaluar_criterio(codigo, valor, config)
            
            if resultado["evaluado"]:
                evaluaciones.append({
                    "codigo": codigo,
                    "nombre": config.get("nombre", codigo),
                    "valor": valor,
                    "puntaje": resultado["puntaje"],
                    "peso": resultado["peso"],
                    "detalle": resultado["detalle"]
                })
                
                score_total += resultado["puntaje_ponderado"]
                peso_total += resultado["peso"]
        
        # 3. Normalizar score
        if peso_total > 0:
            score_normalizado = (score_total / peso_total) * self.escala_max
        else:
            score_normalizado = 0
        
        score_normalizado = min(self.escala_max, max(0, score_normalizado))
        
        # 4. Determinar nivel de riesgo
        nivel = self.determinar_nivel_riesgo(score_normalizado)
        
        # 5. Determinar si está aprobado
        aprobado = not rechazo["rechazo"] and score_normalizado >= self.puntaje_minimo
        
        return {
            "score": round(score_total, 2),
            "score_normalizado": round(score_normalizado, 2),
            "nivel": nivel["nombre"],
            "nivel_detalle": nivel,
            "aprobado": aprobado,
            "rechazo_automatico": rechazo["rechazo"],
            "razon_rechazo": rechazo["razon"],
            "factor_rechazo": rechazo["factor"],
            "criterios_evaluados": evaluaciones,
            "puntaje_minimo": self.puntaje_minimo,
            "escala_max": self.escala_max
        }
