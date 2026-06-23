from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    approval_state = fields.Selection(
        [
            ("not_required", "Sin aprobación pendiente"),
            ("pending", "Pendiente de aprobación"),
            ("approved", "Aprobada"),
            ("rejected", "Rechazada"),
        ],
        string="Estado de aprobación",
        default="not_required",
        copy=False,
        tracking=True,
    )
    approval_rule_id = fields.Many2one(
        "aerotec.approval.rule",
        string="Regla aplicable",
        compute="_compute_approval_info",
        store=True,
    )
    approver_id = fields.Many2one(
        "res.users",
        string="Autorizador requerido",
        compute="_compute_approval_info",
        store=True,
    )
    requires_approval = fields.Boolean(
        string="Requiere aprobación",
        compute="_compute_approval_info",
        store=True,
    )
    is_current_user_approver = fields.Boolean(
        compute="_compute_is_current_user_approver",
        store=False,
    )
    approval_date = fields.Datetime(
        string="Fecha de aprobación",
        readonly=True,
        copy=False,
    )
    approval_notes = fields.Text(
        string="Notas de la aprobación",
        copy=False,
    )

    @api.depends("move_type", "amount_total", "currency_id", "company_id")
    def _compute_approval_info(self):
        Rule = self.env["aerotec.approval.rule"]
        for move in self:
            if move.move_type != "in_invoice":
                move.approval_rule_id = False
                move.approver_id = False
                move.requires_approval = False
                continue
            rule = Rule._find_for_document(
                amount=move.amount_total,
                currency=move.currency_id,
                company=move.company_id,
                doc_type="invoice",
            )
            move.approval_rule_id = rule
            move.approver_id = rule.user_id if rule else False
            move.requires_approval = bool(rule)

    @api.depends("approver_id")
    @api.depends_context("uid")
    def _compute_is_current_user_approver(self):
        for move in self:
            move.is_current_user_approver = bool(
                move.approver_id and move.approver_id.id == self.env.uid
            )

    def action_request_approval(self):
        for move in self:
            if move.move_type != "in_invoice":
                raise UserError(
                    _("Solo se puede solicitar aprobación para facturas de proveedor.")
                )
            if not move.requires_approval:
                raise UserError(
                    _("Esta factura no supera ningún tope configurado y no requiere aprobación.")
                )
            if move.approval_state in ("pending", "approved"):
                labels = dict(self._fields["approval_state"].selection)
                raise UserError(
                    _(
                        "La factura ya está en estado '%(state)s'.",
                        state=labels.get(move.approval_state, ""),
                    )
                )
            move.write({"approval_state": "pending"})
            if move.approver_id:
                move.activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=move.approver_id.id,
                    summary=_("Factura de proveedor pendiente de su autorización"),
                    note=_(
                        "La factura <b>%(ref)s</b> de <b>%(partner)s</b> "
                        "por <b>%(currency)s %(amount)s</b> requiere su autorización.",
                        ref=move.name or move.ref or "borrador",
                        partner=move.partner_id.name or "",
                        currency=move.currency_id.name or "",
                        amount=f"{move.amount_total:,.2f}",
                    ),
                )

    def action_approve_invoice(self):
        for move in self:
            if move.approval_state != "pending":
                raise UserError(
                    _("Solo se pueden aprobar facturas que están pendientes de aprobación.")
                )
            if move.approver_id and self.env.user != move.approver_id:
                raise UserError(
                    _(
                        "Solo '%(user)s' está autorizado a aprobar esta factura.",
                        user=move.approver_id.name,
                    )
                )
            move.write({
                "approval_state": "approved",
                "approval_date": fields.Datetime.now(),
            })
            move.activity_feedback(["mail.mail_activity_data_todo"])

    def action_reject_invoice(self):
        for move in self:
            if move.approval_state not in ("pending", "approved"):
                raise UserError(
                    _("Solo se pueden rechazar facturas pendientes o aprobadas.")
                )
            if move.approver_id and self.env.user != move.approver_id:
                raise UserError(
                    _(
                        "Solo '%(user)s' está autorizado a rechazar esta factura.",
                        user=move.approver_id.name,
                    )
                )
            move.write({
                "approval_state": "rejected",
                "approval_date": False,
            })

    def action_cancel_approval_request(self):
        """El creador cancela la solicitud de aprobación para poder editar la factura."""
        for move in self:
            if move.approval_state != "pending":
                raise UserError(_("Solo se puede cancelar una solicitud pendiente."))
            move.write({"approval_state": "not_required"})
            move.activity_unlink(["mail.mail_activity_data_todo"])

    def action_reset_invoice_approval(self):
        """Restablece el estado para re-solicitar aprobación tras un rechazo."""
        for move in self:
            if move.approval_state != "rejected":
                raise UserError(_("Solo se pueden restablecer facturas rechazadas."))
            move.write({"approval_state": "not_required"})

    def action_post(self):
        for move in self:
            if (
                move.move_type == "in_invoice"
                and move.requires_approval
                and move.approval_state != "approved"
            ):
                labels = dict(self._fields["approval_state"].selection)
                raise UserError(
                    _(
                        "La factura '%(name)s' requiere la aprobación de '%(user)s' antes de confirmarse.\n"
                        "Estado actual: %(state)s.",
                        name=move.name or "",
                        user=move.approver_id.name if move.approver_id else "un autorizador configurado",
                        state=labels.get(move.approval_state, move.approval_state),
                    )
                )
        return super().action_post()
