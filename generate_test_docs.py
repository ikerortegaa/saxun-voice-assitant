"""
generate_test_docs.py — Genera PDFs de prueba para el RAG de Saxun.

Crea 4 documentos que simulan contenido real de una empresa de contact center:
  1. saxun_horarios_contacto.pdf      — Horarios y canales de atención
  2. saxun_garantias_politicas.pdf    — Política de garantías y devoluciones
  3. saxun_productos_catalogo.pdf     — Catálogo básico de productos y precios
  4. saxun_soporte_tecnico.pdf        — Guía de soporte técnico y SAT

Uso:
    .venv/bin/python generate_test_docs.py
"""
from fpdf import FPDF
from pathlib import Path

OUTPUT_DIR = Path("rag-docs")


def make_pdf(filename: str, title: str, sections: list[tuple[str, str]]) -> None:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Título principal
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, title, ln=True, align="C")
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, "Saxun S.A. - Documento interno de referencia", ln=True, align="C")
    pdf.ln(8)

    # Secciones
    for section_title, body in sections:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, section_title, ln=True)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, body)
        pdf.ln(4)

    path = OUTPUT_DIR / filename
    pdf.output(str(path))
    print(f"  Creado: {path}")


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    # ── 1. Horarios y contacto ────────────────────────────────────────────────
    make_pdf(
        "saxun_horarios_contacto.pdf",
        "Horarios de Atención y Canales de Contacto",
        [
            (
                "Horario de atención telefónica",
                "El servicio de atención al cliente de Saxun está disponible de lunes a viernes "
                "de 9:00 a 18:00 horas, y los sábados de 9:00 a 14:00 horas. "
                "Los domingos y festivos nacionales el servicio permanece cerrado.\n\n"
                "Durante los meses de julio y agosto el horario de verano es de lunes a viernes "
                "de 8:00 a 15:00 horas. Los sábados de agosto no hay atención telefónica.",
            ),
            (
                "Teléfono de atención al cliente",
                "Línea general: 900 123 456 (gratuita desde fijos y móviles).\n"
                "Soporte técnico urgente: 900 123 457 (disponible 24h para averías críticas).\n"
                "Clientes empresa (B2B): 900 123 458 (línea preferente, sin espera).",
            ),
            (
                "Atención por email y chat",
                "Email general: atencion@saxun.es - tiempo de respuesta maximo 24h laborables.\n"
                "Email soporte tecnico: soporte@saxun.es - respuesta en menos de 4h laborables.\n"
                "Chat en web: disponible en saxun.es en horario de oficina. "
                "Tiempo de espera habitual: menos de 3 minutos.",
            ),
            (
                "Oficinas y centros de atención presencial",
                "Sede central Barcelona: Calle Gran Via 245, planta 3. "
                "Horario: lunes a viernes 9:00-17:00h. Atención con cita previa.\n\n"
                "Delegación Madrid: Paseo de la Castellana 89, oficina 12. "
                "Horario: lunes a viernes 9:00-17:00h.\n\n"
                "Delegación Valencia: Avenida del Puerto 120. "
                "Horario: lunes a jueves 9:00-17:00h, viernes 9:00-14:00h.",
            ),
        ],
    )

    # ── 2. Garantías y devoluciones ───────────────────────────────────────────
    make_pdf(
        "saxun_garantias_politicas.pdf",
        "Política de Garantías y Devoluciones",
        [
            (
                "Garantía estándar de productos",
                "Todos los productos Saxun incluyen una garantía legal de dos años desde la fecha "
                "de compra, conforme a la normativa europea vigente (Directiva 2019/771/UE).\n\n"
                "La garantía cubre defectos de fabricación y materiales. No cubre daños por uso "
                "incorrecto, golpes, humedad, modificaciones no autorizadas o desgaste normal.",
            ),
            (
                "Garantía extendida Premium",
                "Los clientes que contraten el plan Premium disponen de garantía extendida de "
                "cinco años desde la fecha de compra. La garantía Premium incluye además:\n"
                "- Cobertura por daños accidentales (hasta 2 incidencias por año)\n"
                "- Sustitución de producto en 48h en caso de avería irreparable\n"
                "- Revisiones preventivas anuales sin coste adicional",
            ),
            (
                "Proceso de devolución",
                "El cliente dispone de 30 días naturales desde la recepción del producto para "
                "solicitar la devolución sin necesidad de justificación (derecho de desistimiento).\n\n"
                "Para iniciar una devolución: llamar al 900 123 456 o enviar email a "
                "devoluciones@saxun.es indicando número de pedido y motivo.\n\n"
                "El reembolso se realiza en el mismo método de pago utilizado en la compra, "
                "en un plazo máximo de 14 días hábiles desde la recepción del producto devuelto.",
            ),
            (
                "Exclusiones de garantía",
                "Quedan excluidos de la garantía los siguientes casos:\n"
                "- Daños causados por instalación incorrecta no realizada por técnico certificado Saxun\n"
                "- Uso de accesorios o repuestos no homologados por Saxun\n"
                "- Daños por sobretensión eléctrica no cubiertos por protección adecuada\n"
                "- Productos con número de serie alterado o eliminado\n"
                "- Daños estéticos (arañazos, abolladuras) que no afecten al funcionamiento",
            ),
            (
                "Cómo activar la garantía",
                "Para activar la garantía extendida Premium, el cliente debe registrar el producto "
                "en saxun.es/registro dentro de los 30 días siguientes a la compra. "
                "Sin registro, solo aplica la garantía legal de 2 años.\n\n"
                "El número de serie del producto se encuentra en la etiqueta de la parte trasera "
                "del dispositivo o en la caja de embalaje.",
            ),
        ],
    )

    # ── 3. Catálogo de productos ──────────────────────────────────────────────
    make_pdf(
        "saxun_productos_catalogo.pdf",
        "Catálogo de Productos y Servicios 2025",
        [
            (
                "Gama Residencial - Serie Home",
                "Saxun Home Basic (ref. SHB-200): Sistema de gestión del hogar básico. "
                "Precio de venta recomendado: 299 EUR. Incluye instalación básica.\n\n"
                "Saxun Home Pro (ref. SHP-400): Sistema avanzado con control por voz y app móvil. "
                "Precio: 549 EUR. Incluye instalación y configuración inicial.\n\n"
                "Saxun Home Elite (ref. SHE-800): Solución premium con integración total del hogar. "
                "Precio: 1.200 EUR. Incluye instalación, configuración y formación de 2 horas.",
            ),
            (
                "Gama Empresarial - Serie Business",
                "Saxun Business Starter (ref. SBS-1000): Para oficinas de hasta 20 puestos. "
                "Precio desde 2.400 EUR (licencia anual incluida primer año).\n\n"
                "Saxun Business Pro (ref. SBP-2500): Para empresas medianas, hasta 100 puestos. "
                "Precio desde 5.800 EUR. Soporte técnico prioritario incluido.\n\n"
                "Saxun Business Enterprise: Solución personalizada para grandes empresas. "
                "Precio bajo presupuesto. Contactar con el equipo comercial.",
            ),
            (
                "Planes de mantenimiento",
                "Plan Básico: Revisión anual + soporte telefónico en horario de oficina. "
                "Precio: 120 EUR/año por dispositivo.\n\n"
                "Plan Avanzado: Revisiones semestrales + soporte telefónico 24/7 + "
                "actualizaciones de firmware incluidas. Precio: 220 EUR/año por dispositivo.\n\n"
                "Plan Total: Cobertura completa incluyendo piezas de repuesto y mano de obra. "
                "Precio: 380 EUR/año por dispositivo.",
            ),
            (
                "Accesorios y consumibles",
                "Módulo de expansión ME-100: Compatible con gama Home Pro y Elite. Precio: 89 EUR.\n"
                "Kit de instalación profesional KIP-01: 45 EUR.\n"
                "Cable de conexión certificado CC-200 (2 metros): 24 EUR.\n"
                "Fuente de alimentación de repuesto FA-12V: 35 EUR.\n\n"
                "Todos los accesorios incluyen garantía de 12 meses.",
            ),
        ],
    )

    # ── 4. Soporte técnico ────────────────────────────────────────────────────
    make_pdf(
        "saxun_soporte_tecnico.pdf",
        "Guía de Soporte Técnico y Servicio de Asistencia",
        [
            (
                "Cómo contactar con soporte técnico",
                "Teléfono soporte técnico: 900 123 457 (disponible 24 horas todos los días).\n"
                "Email: soporte@saxun.es (respuesta garantizada en 4 horas laborables).\n"
                "Portal de soporte: soporte.saxun.es (tickets, base de conocimiento, tutoriales).\n\n"
                "Para agilizar la atención, tenga a mano el número de serie del producto "
                "(etiqueta trasera), el número de pedido o factura, y una descripción del problema.",
            ),
            (
                "Niveles de soporte y tiempos de respuesta",
                "Nivel 1 - Incidencia critica (producto completamente inoperativo): "
                "Respuesta en menos de 2 horas. Tecnico en sitio en 24h laborables.\n\n"
                "Nivel 2 - Incidencia grave (funcionalidad parcial): "
                "Respuesta en 4 horas laborables. Resolucion en 48-72h.\n\n"
                "Nivel 3 - Incidencia leve (problema puntual, workaround disponible): "
                "Respuesta en 8 horas laborables. Resolución en 5-7 días hábiles.",
            ),
            (
                "Servicio técnico oficial (SAT)",
                "Saxun dispone de una red de Servicios Técnicos Autorizados (SAT) en toda España.\n\n"
                "SAT Barcelona: Calle Industria 34. Tel: 93 456 78 90. "
                "Horario: L-V 8:00-17:00h.\n\n"
                "SAT Madrid: Calle Alcalá 210. Tel: 91 234 56 78. "
                "Horario: L-V 8:00-17:00h.\n\n"
                "SAT Valencia: Avenida Blasco Ibáñez 78. Tel: 96 345 67 89. "
                "Horario: L-J 8:00-16:30h, V 8:00-14:00h.\n\n"
                "Para reparaciones fuera de garantía, el SAT facilita presupuesto previo "
                "sin compromiso. El diagnóstico tiene un coste de 35 EUR descontables del presupuesto.",
            ),
            (
                "Resolución de problemas frecuentes",
                "El dispositivo no enciende: Verifique que el cable de alimentación está "
                "correctamente conectado y que la toma de corriente funciona. "
                "Si el problema persiste, contacte con soporte técnico.\n\n"
                "El dispositivo no se conecta a la red: Reinicie el router y el dispositivo. "
                "Asegúrese de que la señal WiFi sea suficiente en la ubicación del dispositivo. "
                "La distancia máxima recomendada al router es de 10 metros sin obstáculos.\n\n"
                "La aplicación móvil no sincroniza: Compruebe que dispone de la versión más "
                "reciente de la app (App Store / Google Play). Cierre y vuelva a abrir la app. "
                "Si continúa el problema, desinstale y reinstale la aplicación.\n\n"
                "El dispositivo emite pitidos o luces parpadeantes: Consulte el manual de usuario "
                "o el portal soporte.saxun.es para el significado de los códigos de error.",
            ),
            (
                "Actualizaciones de firmware",
                "Las actualizaciones de firmware se instalan automáticamente durante la noche "
                "si el dispositivo está conectado a internet. No desconecte el dispositivo "
                "durante el proceso de actualización (indicado por luz azul parpadeante).\n\n"
                "Para instalar una actualización manualmente, acceda a la app Saxun, "
                "vaya a Configuración > Mi dispositivo > Actualizar firmware.\n\n"
                "Si necesita hacer un downgrade de firmware por incompatibilidad, "
                "contacte con soporte tecnico - no se recomienda realizarlo sin asistencia.",
            ),
        ],
    )

    print("\nDocumentos generados. Ahora puedes ejecutar la ingestión:")
    print("  .venv/bin/python src/scripts/ingest_docs.py --dir rag-docs")


if __name__ == "__main__":
    main()
