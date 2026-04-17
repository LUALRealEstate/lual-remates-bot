from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import Settings
from app.state_schema import ConversationState
from app.whatsapp_transport import WhatsAppTransportClient


@dataclass
class LeadSummary:
    name: str
    phone_number: str
    city: str
    zone: str
    city_or_zone: str
    property_reference: str
    customer_profile: str
    has_cash: str
    accepts_timeline: str
    understands_product: str
    objections: list[str]
    appointment_preference: str
    transcript_summary: str
    ready_reason: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "phone_number": self.phone_number,
            "city": self.city,
            "zone": self.zone,
            "city_or_zone": self.city_or_zone,
            "property_reference": self.property_reference,
            "customer_profile": self.customer_profile,
            "has_cash": self.has_cash,
            "accepts_timeline": self.accepts_timeline,
            "understands_product": self.understands_product,
            "objections": self.objections,
            "appointment_preference": self.appointment_preference,
            "transcript_summary": self.transcript_summary,
            "ready_reason": self.ready_reason,
        }

    def to_text(self) -> str:
        objections = ", ".join(self.objections) if self.objections else "sin objeciones fuertes"
        return (
            "Lead listo para closer LUAL\n"
            f"Nombre: {self.name}\n"
            f"Teléfono: {self.phone_number}\n"
            f"Ciudad: {self.city}\n"
            f"Zona: {self.zone}\n"
            f"Propiedad activa: {self.property_reference}\n"
            f"Perfil: {self.customer_profile}\n"
            f"Contado: {self.has_cash}\n"
            f"Acepta proceso: {self.accepts_timeline}\n"
            f"Entiende producto: {self.understands_product}\n"
            f"Objeciones: {objections}\n"
            f"Horario preferido: {self.appointment_preference}\n"
            f"Resumen: {self.transcript_summary}\n"
            f"Motivo handoff: {self.ready_reason}"
        )


class Notifier(Protocol):
    def notify(self, summary: LeadSummary) -> None:
        ...


class ConsoleNotifier:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def notify(self, summary: LeadSummary) -> None:
        payload = {"channel": "console", **summary.to_dict()}
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


class DisabledNotifier:
    def notify(self, summary: LeadSummary) -> None:
        _ = summary


class WhatsAppCloserNotifier:
    def __init__(self, log_path: Path, target_phone: str | None, transport: WhatsAppTransportClient) -> None:
        self.log_path = log_path
        self.target_phone = target_phone
        self.transport = transport
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def notify(self, summary: LeadSummary) -> None:
        payload = {
            "channel": "whatsapp",
            "target_phone": self.target_phone,
            **summary.to_dict(),
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        if self.target_phone:
            self.transport.send_text(
                to_phone=self.target_phone,
                message=summary.to_text(),
                metadata={
                    "direction": "closer_notification",
                    "lead_phone_number": summary.phone_number,
                    "target_phone": self.target_phone,
                },
            )


class CloserHandoffService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        transport = WhatsAppTransportClient(settings)
        if not self.settings.closer_notification_enabled:
            self.notifier = DisabledNotifier()
        elif self.settings.closer_notification_method == "whatsapp":
            self.notifier = WhatsAppCloserNotifier(
                log_path=self.settings.closer_console_log_path,
                target_phone=self.settings.closer_phone_number,
                transport=transport,
            )
        else:
            self.notifier = ConsoleNotifier(log_path=self.settings.closer_console_log_path)

    def build_summary(self, state: ConversationState) -> LeadSummary:
        transcript_summary = " | ".join(
            f"{message.role}: {message.text}" for message in state.recent_messages[-6:]
        )
        city_or_zone = ", ".join(
            [item for item in [state.city_interest, state.zone_interest] if item]
        ) or "Sin zona cerrada"
        property_reference = state.selected_property_summary or "Sin propiedad"
        ready_reason = (
            "Lead calificado con contado, acepta proceso, entiende remate y ya pidió contacto con asesor."
        )
        return LeadSummary(
            name=state.name or "Sin nombre",
            phone_number=state.phone_number,
            city=state.city_interest or "Sin ciudad",
            zone=state.zone_interest or "Sin zona",
            city_or_zone=city_or_zone,
            property_reference=property_reference,
            customer_profile=state.customer_profile.value,
            has_cash=state.has_cash.value,
            accepts_timeline=state.accepts_timeline.value,
            understands_product=state.understands_product.value,
            objections=list(state.handled_objections),
            appointment_preference=state.appointment_preference or "Sin horario",
            transcript_summary=transcript_summary,
            ready_reason=ready_reason,
        )

    def handoff(self, state: ConversationState) -> LeadSummary:
        summary = self.build_summary(state)
        self.notifier.notify(summary)
        return summary
