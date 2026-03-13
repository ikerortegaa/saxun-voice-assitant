# Saxun Voice Assistant — Flujo Conversacional por Voz
> Versión 1.0 | Fecha: 2026-03-03

---

## 1. ESTRUCTURA GENERAL DEL FLUJO

```
┌─────────────────────────────────────────────────────────────────────┐
│                   FLUJO MASTER DE CONVERSACIÓN                      │
│                                                                     │
│  SALUDO         IDENTIFICACIÓN    CAPTACIÓN        RESOLUCIÓN       │
│  (5 seg)   →   MÍNIMA (opt.)  →  DE INTENCIÓN  →  O DERIVACIÓN     │
│                                                                     │
│  • "Hola, soy     • Solo si la     • "¿En qué      • RAG response   │
│    Marta de         consulta        le puedo        ó               │
│    Saxun"           requiere        ayudar?"        • handoff       │
│  • Detectar         datos del     • Desambiguar                     │
│    idioma           cliente       • Confirmar                       │
│                                                                     │
│                          ↓                                          │
│                       CIERRE                                        │
│              "¿Hay algo más en lo que         │
│               pueda ayudarle?"                │
│              → SI → vuelta a captación        │
│              → NO → despedida natural         │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. ESTADOS DEL SISTEMA (State Machine)

```python
class ConversationState(Enum):
    GREETING         = "greeting"
    LANGUAGE_DETECT  = "language_detect"
    INTENT_CAPTURE   = "intent_capture"
    DISAMBIGUATION   = "disambiguation"
    RAG_PROCESSING   = "rag_processing"
    RESPONSE         = "response"
    CONFIRMATION     = "confirmation"
    MULTI_STEP       = "multi_step"
    NO_EVIDENCE      = "no_evidence"
    HANDOFF_PENDING  = "handoff_pending"
    HANDOFF_ACTIVE   = "handoff_active"
    CLOSING          = "closing"
    ENDED            = "ended"

# Transiciones permitidas
TRANSITIONS = {
    GREETING:        [INTENT_CAPTURE],
    INTENT_CAPTURE:  [RAG_PROCESSING, DISAMBIGUATION, HANDOFF_PENDING],
    DISAMBIGUATION:  [RAG_PROCESSING, HANDOFF_PENDING],
    RAG_PROCESSING:  [RESPONSE, NO_EVIDENCE, CONFIRMATION],
    RESPONSE:        [INTENT_CAPTURE, CLOSING, HANDOFF_PENDING],
    NO_EVIDENCE:     [HANDOFF_PENDING, INTENT_CAPTURE],
    CONFIRMATION:    [MULTI_STEP, HANDOFF_PENDING],
    CLOSING:         [ENDED, INTENT_CAPTURE],
    HANDOFF_PENDING: [HANDOFF_ACTIVE],
}
```

---

## 3. MANEJO DE CASOS ESPECIALES DE VOZ

### 3.1 Barge-in (el cliente interrumpe mientras habla el asistente)

```python
def handle_barge_in(session: Session):
    """El cliente empieza a hablar mientras el asistente habla"""
    # 1. Detener TTS inmediatamente
    tts_stream.interrupt()

    # 2. Capturar lo que dijo el cliente
    new_utterance = await stt.listen()

    # 3. Si el cliente dijo algo significativo → procesar como nueva intención
    if new_utterance.confidence > 0.7 and len(new_utterance.text) > 3:
        session.state = ConversationState.INTENT_CAPTURE
        return process_intent(new_utterance.text, session)

    # 4. Si fue ruido → continuar o preguntar
    else:
        return "Disculpe, ¿me decía algo?"
```

### 3.2 Silencio (el cliente no habla)

```
Timeout 3 segundos: "¿Sigue ahí? ¿En qué le puedo ayudar?"
Timeout 6 segundos: "Parece que la línea no va bien. Puede llamarnos de nuevo cuando quiera. ¡Hasta luego!"
→ Fin de llamada limpio + log de "abandoned call"
```

### 3.3 No entendido (ASR confidence bajo)

```
confidence < 0.70:
  Intento 1: "Le escucho pero no le entiendo bien. ¿Puede repetirlo?"
  Intento 2: "Voy a pasarle con uno de nuestros especialistas para atenderle mejor."
  → HANDOFF automático tras 2 intentos fallidos consecutivos
```

### 3.4 Ruido de fondo alto

```python
def handle_high_noise(audio_metrics: AudioMetrics):
    if audio_metrics.snr < 10:  # signal-to-noise ratio bajo
        # Opción 1: pedir que repita desde lugar más silencioso
        return "Escucho bastante ruido de fondo. ¿Puede repetir su pregunta?"
        # Si persiste → handoff con nota: "llamada con ruido, cliente puede no haber entendido"
```

---

## 4. EJEMPLOS DE DIÁLOGOS (8 CASOS TÍPICOS)

### DIÁLOGO 1 — Consulta de horario (caso simple, RAG con alta confianza)

```
[Ring... Ring...]

ASISTENTE: "Buenos días, ha llamado a Saxun. Soy Marta. ¿En qué le puedo ayudar?"

CLIENTE: "Hola, quería saber vuestro horario de atención."

ASISTENTE: "Atendemos de lunes a viernes de nueve a seis de la tarde,
            y los sábados de nueve a dos. ¿Necesita algo más?"

CLIENTE: "No, era eso. Gracias."

ASISTENTE: "De nada. Que tenga un buen día."

[FIN — Duración: ~25s — RAG confidence: 0.95 — No handoff]
```

### DIÁLOGO 2 — Consulta de garantía (caso medio, confirmación de comprensión)

```
ASISTENTE: "Buenos días, ha llamado a Saxun. Soy Marta. ¿En qué le puedo ayudar?"

CLIENTE: "Uh... es que compré un producto el año pasado y se ha estropeado
          y no sé si tengo garantía todavía."

ASISTENTE: "Entendido. Me está preguntando si su producto todavía tiene
            garantía, ¿es correcto?"

CLIENTE: "Sí, exactamente."

ASISTENTE: "Los productos Saxun tienen dos años de garantía desde la fecha
            de compra. Si lo compró hace menos de dos años, sigue cubierto.
            ¿Recuerda cuándo fue la compra aproximadamente?"

CLIENTE: "Fue en marzo del año pasado, creo."

ASISTENTE: "Entonces aún tendría garantía hasta marzo del año que viene.
            Para gestionarla necesitaría su número de pedido o el ticket de
            compra. ¿Le paso con nuestro equipo de posventa para abrirlo?"

CLIENTE: "Sí, por favor."

ASISTENTE: "Perfecto. Le transfiero ahora mismo. Un momento."

[HANDOFF — Summary generado: "Cliente consulta garantía. Compra: ~marzo 2025.
Garantía vigente (2 años desde compra). Solicita apertura de incidencia.
Necesita nº pedido/ticket."]
```

### DIÁLOGO 3 — Pregunta sin evidencia en RAG (anti-alucinación)

```
ASISTENTE: "Buenas tardes, Saxun, soy Marta. ¿En qué le puedo ayudar?"

CLIENTE: "Quiero saber si tenéis el modelo XR-7000 en color azul marino."

ASISTENTE: "Déjeme un momento..."
[RAG: confidence 0.12, evidence_found: false]

ASISTENTE: "Lo siento, no tengo esa información disponible en este momento.
            Para consultarlo con exactitud, ¿le paso con un especialista de
            producto?"

CLIENTE: "Bueno, vale."

ASISTENTE: "Ahora mismo le transfiero. Un momento, por favor."

[HANDOFF — Summary: "Cliente pregunta por modelo XR-7000 en azul marino.
Sin datos en KB. Consulta de disponibilidad de stock/color."]
```

### DIÁLOGO 4 — Desambiguación (intención ambigua)

```
ASISTENTE: "Buenos días, Saxun, soy Marta. ¿En qué le puedo ayudar?"

CLIENTE: "Quería información sobre el mantenimiento."

ASISTENTE: "Claro. ¿Se refiere al mantenimiento de un producto que ya tiene,
            o a nuestros planes de mantenimiento preventivo?"

CLIENTE: "De un producto que tengo."

ASISTENTE: "Entendido. ¿Es un problema concreto que está teniendo, o busca
            instrucciones de cuidado general?"

CLIENTE: "Tengo un problema, hace un ruido raro."

ASISTENTE: "Voy a pasarle con nuestro soporte técnico para que le orienten
            mejor. ¿Me puede dar un número de contacto por si se corta?"

[HANDOFF — Summary: "Cliente tiene producto con ruido anómalo.
Consulta: soporte técnico / diagnóstico. No especificó modelo.
Pedir modelo y nº serie al inicio de atención."]
```

### DIÁLOGO 5 — Barge-in y corrección del cliente

```
ASISTENTE: "Los centros de servicio técnico oficial de Saxun se encuentran en
            Barcelona, Madrid, Valencia..."

CLIENTE: [interrumpe] "Espera espera, yo estoy en Bilbao."

ASISTENTE: [para TTS]
           "Bilbao, por supuesto. El centro más cercano a Bilbao está en
            San Sebastián, en la Calle Mayor número doce."

CLIENTE: "¿Y tienen horario de tarde?"

ASISTENTE: "Sí, abren de diez a dos y de cuatro a siete, de lunes a viernes.
            ¿Necesita algo más?"
```

### DIÁLOGO 6 — Reclamación formal (derivación por política)

```
ASISTENTE: "Buenas tardes, Saxun, soy Marta. ¿En qué le puedo ayudar?"

CLIENTE: "Quiero poner una reclamación formal. Llevo tres semanas esperando
          una reparación y nadie me ha llamado."

ASISTENTE: "Lamento mucho los inconvenientes que está teniendo. Para tramitar
            su reclamación correctamente le voy a pasar con uno de nuestros
            gestores de incidencias ahora mismo."

[HANDOFF INMEDIATO — política: reclamación formal → derivar siempre]
[Summary: "Cliente insatisfecho. Incidencia reparación pendiente >3 semanas
sin contacto. Solicita reclamación formal. PRIORIDAD: alta.
Tono emocional: frustrado."]
```

### DIÁLOGO 7 — Consulta de precio (no en RAG → derivar)

```
CLIENTE: "¿Cuánto cuesta el servicio de instalación?"

ASISTENTE: "El precio de instalación depende del tipo de producto y de su
            ubicación, así que varía. Para darle un presupuesto exacto
            necesitaría consultarlo con nuestro equipo comercial.
            ¿Prefiere que le llamen ellos, o le transfiero ahora?"

CLIENTE: "Que me llamen mejor."

ASISTENTE: "Perfecto. ¿A qué número y en qué horario le viene mejor?"

CLIENTE: "Al seis, tres, dos... [número]... por las mañanas."

ASISTENTE: "Anotado. Nuestro equipo le llamará mañana por la mañana.
            ¿Algo más en lo que pueda ayudarle?"

[TICKET CREADO — datos: teléfono redactado en log, franja horaria,
tipo consulta: presupuesto instalación]
```

### DIÁLOGO 8 — Cliente insistente / múltiples intentos fallidos

```
ASISTENTE: "Saxun, buenos días. Soy Marta."

CLIENTE: "Sí, quiero que me digáis exactamente cuándo llega mi pedido
          número 8734."

ASISTENTE: "Entiendo que quiere consultar el estado de su pedido.
            No tengo acceso al sistema de pedidos en tiempo real, pero
            le puedo pasar con quien puede consultarlo ahora mismo."

CLIENTE: "Es que ya me han dicho eso dos veces hoy."

ASISTENTE: "Le entiendo perfectamente y lamento las molestias. Le voy a
            pasar con el responsable de pedidos directamente para que
            tenga una respuesta definitiva. ¿Le parece bien?"

CLIENTE: "Bueno, pero que alguien me resuelva esto ya."

ASISTENTE: "Así será. Le transfiero ahora con prioridad."

[HANDOFF PRIORIDAD ALTA — Summary: "Cliente con pedido 8734 (pendiente).
Ha llamado múltiples veces hoy sin resolución. Estado emocional: frustrado.
Requiere resolución inmediata de tracking/entrega. ESCALAR A SUPERVISOR."]
```

---

## 5. POLÍTICA DE SALUDO E IDENTIFICACIÓN

### 5.1 Saludo estándar
```
"[Buenos días / Buenas tardes / Buenas noches], ha llamado a Saxun.
 Soy Marta. ¿En qué le puedo ayudar?"
```
- Adaptar saludo por hora local (usando timezone del número de origen)
- Nombre del asistente: configurable por Saxun (ej. "Marta", "Alex")
- NO decir "asistente virtual" ni "IA" en el saludo

### 5.2 Identificación mínima

**Principio**: identificar SOLO cuando sea estrictamente necesario.

| Caso | ¿Pedir identificación? | Qué pedir |
|---|---|---|
| Consulta genérica (horarios, garantías, precios) | NO | — |
| Abrir incidencia o reclamación | SÍ | Nombre + teléfono de contacto |
| Consultar pedido específico | SÍ | Número de pedido |
| Consulta de datos personales del cliente | SÍ + verificación | DNI/NIE (last 4 digits) |
| Baja de servicio | SÍ + derivar | Siempre a humano |

**Script de identificación:**
```
"Para poder ayudarle mejor, ¿me puede decir su nombre y el número de pedido?"
```

### 5.3 Confirmación antes de instrucciones largas

Si la respuesta tiene más de 3 pasos:
```
"Voy a explicarle el proceso en varios pasos. ¿Está en un lugar donde
pueda tomar nota o tiene unos minutos?"
→ SI: continuar con pasos
→ NO: "¿Prefiere que le enviemos las instrucciones por email?"
```

---

## 6. SCRIPTS DE CIERRE Y DESPEDIDA

```python
CLOSING_SCRIPTS = {
    "resolved": [
        "Espero haberle ayudado. ¿Hay algo más en lo que pueda ayudarle?",
        "¿Tiene alguna otra consulta?",
    ],
    "handoff": [
        "Le transfiero ahora mismo. Gracias por su paciencia.",
        "Ahora le atiende uno de nuestros especialistas. Un momento.",
    ],
    "goodbye": [
        "Ha sido un placer ayudarle. ¡Que tenga un buen día!",
        "Muchas gracias por llamar a Saxun. ¡Hasta pronto!",
    ],
    "no_resolution": [
        "Nuestro equipo le contactará en las próximas horas.
         Gracias por su paciencia.",
    ]
}
```

---

## 7. DETECCIÓN DE IDIOMA Y SWITCHING

```
Llamada entrante:
→ Los primeros 3-5 segundos: detección automática de idioma
→ Si es catalán/valenciano: "Bon dia, ha trucat a Saxun. Sóc la Marta.
   En què li puc ajudar?"
→ Si es inglés: "Good morning, you've reached Saxun. I'm Marta.
   How can I help you today?"
→ Si hay mezcla (code-switching): seguir el idioma mayoritario del cliente

Switch en mitad de conversación:
→ El cliente cambia de idioma → el asistente adapta en el siguiente turno
→ "Claro, podemos continuar en [idioma]."
```

---

## 8. REGLAS DE CALIDAD VOCAL

| Regla | Detalle |
|---|---|
| Longitud de turno | Máximo 2 frases, ~25 palabras por frase |
| Confirmación de comprensión | Siempre ante ambigüedad ("Entendido, me está preguntando sobre X, ¿correcto?") |
| Tecnicismos | Prohibidos; traducir siempre a lenguaje natural |
| Números | Verbalizarlos ("dos años", no "2 años") |
| "No sé" | Nunca decirlo solo; siempre con alternativa de derivación |
| Empatía | En quejas/frustración: "Entiendo su situación" antes de la respuesta |
| Velocidad | Pausas naturales (SSML `<break time="300ms"/>`) tras puntos |
| Silencio procesando | Si RAG tarda >2s: "Un momento, lo consulto..." |
