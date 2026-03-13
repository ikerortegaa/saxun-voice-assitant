# Saxun Voice Assistant — Preguntas Críticas para el Cliente
> Versión 1.0 | Fecha: 2026-03-03

---

## PREGUNTAS ORDENADAS POR BLOQUEO DE PROYECTO

### BLOQUE A — CRÍTICAS (Bloquean el inicio)

**A1. Documentos corporativos**
> ¿En qué estado están los documentos que usará el sistema?
> ¿Son PDFs digitales (nativos) o escaneados? ¿En qué formatos?

*Supuesto si no hay respuesta: PDFs mixtos; se incluye OCR en la solución.*

---

**A2. Volumen de llamadas**
> ¿Cuántas llamadas recibe Saxun al mes en el número de atención al cliente?
> ¿Cuál es la distribución horaria? ¿Hay picos (mañanas, lunes)?

*Supuesto: 2,000-5,000 llamadas/mes. MVP dimensionado para 20 simultáneas.*

---

**A3. Infraestructura de telefonía actual**
> ¿Tiene Saxun ya un número DID? ¿En Twilio, Vonage, centralita propia?
> ¿Existe ya una cola de agentes (ACD/contact center)? ¿Qué sistema usan?

*Supuesto: nueva línea Twilio; cola de agentes existente con número SIP.*

---

**A4. Idiomas requeridos desde el día 1**
> ¿Es obligatorio el catalán/valenciano en el MVP, o puede ser fase 2?
> ¿Qué % de llamadas se reciben en cada idioma?

*Supuesto: español 85%, catalán 12%, inglés 3%. Catalán en MVP limitado.*

---

**A5. Regulación y soberanía de datos**
> ¿Tiene Saxun requisito de que todos los datos permanezcan en EU?
> ¿Hay auditorías de cumplimiento previstas? ¿DPO designado?

*Supuesto: datos en EU obligatorio. Usar servicios con región EU confirmada.*

---

**A6. Casos de uso prioritarios**
> ¿Cuáles son las 5 consultas más frecuentes que recibe atención al cliente hoy?
> ¿Hay consultas que NUNCA debe responder la IA (siempre humano)?

*Supuesto: garantías, horarios, estado de pedido, soporte técnico básico, devoluciones.*

---

### BLOQUE B — IMPORTANTES (Afectan al diseño)

**B1. CRM y sistemas existentes**
> ¿Usan Zendesk, Salesforce, HubSpot, o sistema propio?
> ¿Deben los tickets crearse automáticamente en ese sistema?

*Supuesto: Zendesk. Integración básica en MVP, avanzada en fase 2.*

---

**B2. Identificación de clientes**
> ¿Es necesario autenticar al cliente durante la llamada?
> Si sí, ¿qué datos se usan para verificar identidad? ¿Número de pedido, DNI, cuenta?

*Supuesto: identificación opcional; solo para consultas de pedido o reclamaciones.*

---

**B3. Grabación de llamadas**
> ¿Saxun graba actualmente las llamadas? ¿Es un requisito legal o calidad?
> Si sí: ¿consiente el cliente con aviso al inicio o hay base legal distinta?

*Supuesto: no grabar por defecto. Aviso opcional para mejora de calidad.*

---

**B4. Voz del asistente**
> ¿Prefiere Saxun una voz femenina, masculina, o ambas opciones?
> ¿Tienen ya una "voz de marca" (brand voice) que quieran replicar?

*Supuesto: voz femenina, nombre "Marta". Sin brand voice personalizada en MVP.*

---

**B5. Horario de operación**
> ¿El asistente debe funcionar 24/7 o solo en horario laboral?
> Fuera de horario: ¿mensaje de buzón de voz, SMS, o solo derivar a email?

*Supuesto: 24/7 para consultas informativas; handoff solo en horario laboral.*

---

**B6. Multicanal**
> En el futuro: ¿el mismo asistente debe responder también por WhatsApp/chat web?
> ¿Se quiere reutilizar la misma base de conocimiento (RAG)?

*Supuesto: sí, mismo RAG. Arquitectura diseñada para ser agnóstica al canal.*

---

**B7. Sensibilidad de precios**
> ¿Los precios de productos están en documentos internos que la IA puede citar?
> ¿O son negociados y no deben revelarse sin intervención comercial?

*Supuesto: precios de catálogo públicos → en RAG. Precios negociados → derivar.*

---

### BLOQUE C — OPERATIVAS (Para afinar el sistema)

**C1. Proceso de actualización de documentos**
> ¿Quién en Saxun será responsable de mantener actualizados los documentos?
> ¿Con qué frecuencia cambia el catálogo o las políticas?

*Supuesto: 1 persona designada, actualizaciones mensuales.*

---

**C2. Feedback loop con agentes**
> ¿Estarán los agentes de Saxun dispuestos a dar feedback sobre la calidad
> de los handoff summaries? (5-10 segundos por llamada transferida)

*Supuesto: sí, formulario embebido en pantalla de agente.*

---

**C3. SLA de respuesta del asistente**
> ¿Cuál es la latencia máxima aceptable para el cliente (tiempo hasta primera respuesta)?
> ¿El cliente de Saxun es paciente o requiere respuesta muy rápida?

*Supuesto: < 2.5 segundos. Clientes de contact center B2C.*

---

**C4. Franja de mantenimiento**
> ¿Existe alguna ventana de mantenimiento preferida (madrugada)?
> ¿Se tolera downtime planificado o necesita 99.9% uptime estricto?

*Supuesto: mantenimiento 2:00-4:00 CET. Tolerancia de 30 min/mes.*

---

**C5. Escalado a supervisor**
> Cuando un agente no puede resolver, ¿hay supervisor disponible?
> ¿El asistente debe saber que puede haber cola de espera larga?

*Supuesto: supervisor en horario laboral. Mensaje de espera si cola > 5 min.*

---

## SUPUESTOS RAZONABLES DOCUMENTADOS

Para comenzar el MVP sin esperar respuestas, aplicamos los siguientes supuestos:

| # | Supuesto | Revisable en |
|---|---|---|
| 1 | 2,000-5,000 llamadas/mes en MVP | Semana 1 kick-off |
| 2 | Documentos en PDF digital (algunos escaneados) | Semana 1 |
| 3 | Nueva línea Twilio, cola SIP existente en Saxun | Semana 1 |
| 4 | Datos en EU obligatorio (Twilio EU, Anthropic EU, Deepgram EU) | Kick-off |
| 5 | Sin autenticación de cliente en MVP | Semana 2 |
| 6 | Voz "Marta", femenina, ElevenLabs | Semana 2 |
| 7 | Español como idioma primario, catalán como P1 | Semana 2 |
| 8 | Zendesk como CRM, integración básica | Semana 3 |
| 9 | No grabar audio por defecto | Kick-off |
| 10 | Equipo Saxun designa 1 responsable de documentos | Kick-off |

---

## PREGUNTAS PARA LA REUNIÓN DE KICK-OFF (TOP 5)

Si solo puedo hacer 5 preguntas en el primer meeting:

1. **"¿Cuáles son las 5 preguntas más frecuentes que recibe vuestro contact center?"**
   → Diseña el 80% del sistema.

2. **"¿En qué estado están los documentos internos y quién los mantiene?"**
   → Define el esfuerzo de preparación del RAG.

3. **"¿Qué sistema de telefonía/contact center tenéis hoy?"**
   → Define la integración de handoff.

4. **"¿Tenéis algún requisito especial de privacidad o que los datos no salgan de España?"**
   → Define el stack completo.

5. **"¿Qué significaría para Saxun que este asistente funcione mal un día?"**
   → Define los criterios de aceptación y los riesgos prioritarios.
